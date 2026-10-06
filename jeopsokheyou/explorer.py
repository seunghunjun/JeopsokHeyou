# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""SFTP remote file explorer.

- Double-click to enter folders (no cd needed), or type a path directly
- Drag & drop from Windows Explorer to upload (folders recursively)
- Download / rename / delete / new folder / copy path
- Double-click a file -> open with the local default program; on save, ask whether to upload it back
- "Sync location": cd in the terminal moves the explorer, and changing folders in the explorer moves the terminal
"""
from __future__ import annotations

import hashlib
import os
import posixpath
import queue
import stat
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QMimeData, QSize, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QGuiApplication, QKeySequence, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QStackedLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu,
                               QMessageBox, QProgressBar, QStyle, QStyledItemDelegate, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import applog, diskusage, diskui, dragout, icons, paths, winopen
from .i18n import tr
from .safenames import UnsafeName, local_name, safe_join
from .ssh import SshConnection


CANCELLED = "\x00cancelled"   # internal marker emitted when a transfer is cancelled
log = applog.get("sftp")


class Cancelled(Exception):
    pass


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def sh_quote(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


class SftpWorker(QThread):
    """Thread that runs jobs sequentially on one dedicated SFTPClient (paramiko SFTP is not thread-safe)."""
    result = Signal(str, object)
    error = Signal(str, str)
    progress = Signal(str, int, int)
    note = Signal(str)                  # status text while a job prepares (e.g. scanning folders)
    ask = Signal(object)                # {"info", "answer", "event"}: a question for the user (UI thread)

    def __init__(self, conn: SshConnection):
        super().__init__()
        self.conn = conn
        self.q: queue.Queue = queue.Queue()
        self.cancel = False
        self.busy = False       # a job is running (used to decide auto-disconnect)
        self.sftp = None

    def submit(self, tag: str, fn) -> None:
        self.q.put((tag, fn))

    def stop(self) -> None:
        self.q.put(None)

    def run(self):
        try:
            self.sftp = self.conn.open_sftp()
        except Exception as e:
            log.warning("SFTP channel could not be opened: %s", e)
            self.error.emit("open", str(e))
            return
        while True:
            item = self.q.get()
            if item is None:
                break
            tag, fn = item
            self.cancel = False
            self.busy = True
            quiet = tag in ("list", "home", "disk")       # browsing: too frequent to log each one
            if not quiet:
                log.info("job %s started", tag)
            try:
                self.result.emit(tag, fn(self.sftp, self))
                if not quiet:
                    log.info("job %s finished", tag)
            except Cancelled:
                log.info("job %s cancelled", tag)
                self.error.emit(tag, CANCELLED)
            except Exception as e:
                log.warning("job %s failed: %s: %s", tag, type(e).__name__, e, exc_info=not quiet)
                self.error.emit(tag, f"{type(e).__name__}: {e}")
            finally:
                self.busy = False
        try:
            self.sftp.close()
        except Exception:
            pass

    def ask_user(self, info: dict) -> str:
        """Ask the UI thread and wait for the answer (Cancel still works while waiting)."""
        req = {"info": info, "answer": "cancel", "event": threading.Event()}
        self.ask.emit(req)
        while not req["event"].wait(0.2):
            if self.cancel:
                raise Cancelled()
        return req["answer"]

    def cb(self, label: str, base: int, total: int):
        def _cb(done, _size):
            if self.cancel:
                raise Cancelled()
            self.progress.emit(label, base + done, total)
        return _cb


# ---------------------------------------------------------------- job functions (run in the worker thread)
def job_list(path: str, origin: str = "user"):
    def fn(sftp, w):
        real = sftp.normalize(path)
        return real, sftp.listdir_attr(real), origin
    return fn


DEFAULT_CONFIRM_GB = 1
DEFAULT_CONFIRM_FILES = 10000
# Pseudo file systems: never walked into from a link (their files can block or never end)
PSEUDO_ROOTS = ("/proc", "/sys", "/dev", "/run")


def confirm_limits(settings: dict) -> tuple[int, int]:
    """(bytes, files) above which a download asks first; 0 means never ask for that measure."""
    try:
        gb = float(settings.get("download_confirm_gb", DEFAULT_CONFIRM_GB))
        n = int(settings.get("download_confirm_files", DEFAULT_CONFIRM_FILES))
    except (TypeError, ValueError):
        gb, n = DEFAULT_CONFIRM_GB, DEFAULT_CONFIRM_FILES
    return max(0, int(gb * (1 << 30))), max(0, n)


class DownloadScan:
    """Walks what to download without opening any remote file (stat / readdir / realpath only).

    items() yields ("dir", local, via_link) and ("file", remote, local, size, via_link), parents first.
    Never downloaded, so a download can never hang or loop:
    - FIFOs, sockets and devices (opening one blocks the server's SFTP process with no way to cancel)
    - a folder already included (link loops such as `x -> ..`, two links to the same place)
    - /proc, /sys, /dev and /run when reached during the walk
    Folder links are followed while follow_links is True (the user may turn that off part way).
    A link the user picked directly is always followed.
    """

    def __init__(self, sftp, w, remote_paths: list[str], local_dir: str):
        self.sftp, self.w = sftp, w
        self.remote_paths, self.local_dir = remote_paths, local_dir
        self.follow_links = True
        self.unsafe: list[str] = []
        self.special: list[str] = []
        self.linked: list[str] = []      # linked folders that were followed
        self.seen: set[str] = set()
        self.files = 0
        self.bytes = 0

    def _real(self, rpath: str) -> str:
        try:
            return self.sftp.normalize(rpath)
        except IOError:
            return rpath

    def items(self):
        stack = [(r, self.local_dir, None, False, True) for r in reversed(self.remote_paths)]
        while stack:
            if self.w.cancel:
                raise Cancelled()
            rpath, ldir, attr, via_link, top = stack.pop()
            if via_link and not self.follow_links:
                continue
            name = posixpath.basename(rpath.rstrip("/")) or "root"
            try:
                lpath = safe_join(ldir, name)   # prevent server-supplied names from writing outside the folder
            except UnsafeName:
                self.unsafe.append(rpath)
                continue
            if attr is None or not stat.S_IFMT(attr.st_mode or 0):
                attr = self.sftp.stat(rpath)     # top level (follows a picked link) or no file type sent
            mode = attr.st_mode or 0
            link = False
            if stat.S_ISLNK(mode):
                try:
                    attr = self.sftp.stat(rpath)
                except IOError:
                    self.special.append(rpath)   # broken link
                    continue
                mode = attr.st_mode or 0
                link = not top
            if stat.S_ISDIR(mode):
                real = self._real(rpath)
                if real in self.seen or (not top and any(real == p or real.startswith(p + "/")
                                                         for p in PSEUDO_ROOTS)):
                    self.special.append(rpath)
                    continue
                if link:
                    if not self.follow_links:
                        self.special.append(rpath)
                        continue
                    self.linked.append(rpath)
                self.seen.add(real)
                inner = via_link or link
                yield ("dir", lpath, inner)
                for a in reversed(self.sftp.listdir_attr(rpath)):   # "." / ".." end up as unsafe names
                    stack.append((posixpath.join(rpath, a.filename), lpath, a, inner, False))
                continue
            if stat.S_ISREG(mode):
                size = attr.st_size or 0
                self.files += 1
                self.bytes += size
                yield ("file", rpath, lpath, size, via_link)   # a link to a file is just a file
                continue
            self.special.append(rpath)           # FIFO, socket, block/character device


def job_download(remote_paths: list[str], local_dir: str, limits: tuple[int, int] | None = None):
    """Count first; past the user's limit stop counting and ask (download all / skip linked folders /
    cancel), then keep counting while downloading so nothing is walked twice."""
    max_bytes, max_files = limits if limits is not None else confirm_limits({})

    def fn(sftp, w):
        scan = DownloadScan(sftp, w, remote_paths, local_dir)
        it = scan.items()
        last = [0.0]

        def note(force=False):
            now = time.monotonic()
            if force or now - last[0] > 0.25:
                last[0] = now
                w.note.emit(tr("Checking folders… {n} files", n=scan.files))

        note(True)
        buffered = []
        over = False
        for item in it:
            buffered.append(item)
            note()
            if (max_bytes and scan.bytes > max_bytes) or (max_files and scan.files > max_files):
                over = True
                break
        skipped_links = 0
        if over:
            choice = w.ask_user({"bytes": scan.bytes, "files": scan.files,
                                 "linked": [posixpath.basename(p.rstrip("/")) for p in scan.linked]})
            log.info("download: limit passed after %d files / %d bytes; user chose %s",
                     scan.files, scan.bytes, choice)
            if choice != "all" and choice != "no_links":
                raise Cancelled()
            if choice == "no_links":
                scan.follow_links = False
                skipped_links = len(scan.linked)
                buffered = [i for i in buffered if not i[-1]]
        total = 0 if over else scan.bytes        # 0: size unknown, progress shows the amount received
        log.info("download: %s -> %s (%s)", ", ".join(remote_paths), local_dir,
                 f"{scan.files} files, {total} bytes" if not over else "counting while downloading")
        done = 0

        def handle(item):
            nonlocal done
            if item[-1] and not scan.follow_links:
                return
            if item[0] == "dir":
                os.makedirs(item[1], exist_ok=True)
                return
            _kind, rpath, lpath, size, _via = item
            if w.cancel:
                raise Cancelled()
            log.info("download: %s", rpath)
            sftp.get(rpath, lpath, callback=w.cb(tr("Downloading: {name}", name=posixpath.basename(lpath)), done, total))
            done += size

        for item in buffered:
            handle(item)
        for item in it:                          # only when the limit was passed: walk on while downloading
            handle(item)
        for p in scan.special:
            log.info("download: skipped (special file or folder already included): %s", p)
        for p in scan.unsafe:
            log.info("download: skipped (unsafe name): %s", p)
        notes = []
        if scan.unsafe:
            notes.append(tr("{n} unsafe names skipped", n=len(scan.unsafe)))
        skipped = len(scan.special) + skipped_links
        if skipped:
            notes.append(tr("{n} special files or linked folders skipped", n=skipped))
        return local_dir + ("  (" + ", ".join(notes) + ")" if notes else "")
    return fn


def job_upload_check(local_paths: list[str], remote_dir: str):
    """Before uploading: which of the dropped names already exist in the remote folder."""
    def fn(sftp, w):
        existing = []
        for lp in local_paths:
            name = os.path.basename(lp.rstrip("\\/"))
            try:
                st = sftp.stat(posixpath.join(remote_dir, name))
            except OSError:
                continue          # not there — nothing to overwrite
            existing.append((name, stat.S_ISDIR(st.st_mode)))
        return local_paths, remote_dir, existing
    return fn


def ask_overwrite(parent, existing: list[tuple[str, bool]], remote_dir: str) -> str:
    """Ask what to do with names that already exist: "overwrite", "skip" or "cancel"."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(tr("File already exists"))
    names = [n + ("/" if is_dir else "") for n, is_dir in existing]
    if len(existing) == 1:
        box.setText(tr("'{name}' already exists in {folder}. Overwrite it?", name=names[0], folder=remote_dir))
    else:
        shown = "\n".join("  • " + n for n in names[:10]) + ("\n  …" if len(names) > 10 else "")
        box.setText(tr("{n} items already exist in {folder}:", n=len(existing), folder=remote_dir) + "\n\n" + shown)
    if any(is_dir for _n, is_dir in existing):
        box.setInformativeText(tr("Existing folders are merged: files with the same name inside them are overwritten."))
    over = box.addButton(tr("Overwrite") if len(existing) == 1 else tr("Overwrite all"), QMessageBox.ButtonRole.AcceptRole)
    skip = box.addButton(tr("Skip") if len(existing) == 1 else tr("Skip existing"), QMessageBox.ButtonRole.ActionRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.exec()
    clicked = box.clickedButton()
    return "overwrite" if clicked is over else "skip" if clicked is skip else "cancel"


def job_upload(local_paths: list[str], remote_dir: str, skip: set | None = None):
    local_paths = [lp for lp in local_paths if os.path.basename(lp.rstrip("\\/")) not in (skip or set())]

    def fn(sftp, w):
        total = 0
        for lp in local_paths:
            if os.path.isdir(lp):
                for root, _, files in os.walk(lp):
                    total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
            else:
                total += os.path.getsize(lp)
        done = [0]

        def put(lp, rdir):
            name = os.path.basename(lp.rstrip("\\/"))
            rpath = posixpath.join(rdir, name)
            if os.path.isdir(lp):
                try:
                    sftp.mkdir(rpath)
                except OSError:
                    pass  # already exists
                for child in sorted(os.listdir(lp)):
                    put(os.path.join(lp, child), rpath)
            else:
                sftp.put(lp, rpath, callback=w.cb(tr("Uploading: {name}", name=name), done[0], total), confirm=True)
                done[0] += os.path.getsize(lp)
        for lp in local_paths:
            put(lp, remote_dir)
        return remote_dir
    return fn


def job_download_drop(remote_paths: list[str], local_dir: str, items, marker: bytes,
                      limits: tuple[int, int] | None = None):
    """Drag-out download: downloaded files overwrite the placeholders; placeholders are cleaned up on failure/cancel."""
    inner = job_download(remote_paths, local_dir, limits)

    def fn(sftp, w):
        try:
            res = inner(sftp, w)
        except BaseException:
            dragout.remove_placeholders(local_dir, items, marker, only_untouched=True)
            raise
        dragout.remove_placeholders(local_dir, items, marker, only_untouched=False)
        return res
    return fn


def file_digest(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def job_put_file(local_path: str, remote_path: str):
    def fn(sftp, w):
        size = os.path.getsize(local_path)
        sftp.put(local_path, remote_path, callback=w.cb(tr("Uploading: {name}", name=posixpath.basename(remote_path)), 0, size))
        return remote_path
    return fn


def job_get_file(remote_path: str, local_path: str):
    def fn(sftp, w):
        st = sftp.stat(remote_path)
        if not stat.S_ISREG(st.st_mode or stat.S_IFREG):
            # FIFOs, sockets and devices: opening one would block the server's SFTP process
            raise IOError(tr("{name} is not a regular file, so it was not opened",
                             name=posixpath.basename(remote_path)))
        size = st.st_size or 0
        log.info("open: %s", remote_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        sftp.get(remote_path, local_path, callback=w.cb(tr("Downloading: {name}", name=posixpath.basename(remote_path)), 0, size))
        return local_path, remote_path
    return fn


def job_delete(paths: list[str]):
    def fn(sftp, w):
        def rm(p):
            st = sftp.lstat(p)
            if stat.S_ISDIR(st.st_mode):
                for a in sftp.listdir_attr(p):
                    rm(posixpath.join(p, a.filename))
                sftp.rmdir(p)
            else:
                sftp.remove(p)
        for p in paths:
            rm(p)
    return fn


def job_simple(action):
    def fn(sftp, w):
        return action(sftp)
    return fn


# ---------------------------------------------------------------- UI
class _Item(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a_dir = self.data(0, Qt.ItemDataRole.UserRole + 1)
        b_dir = other.data(0, Qt.ItemDataRole.UserRole + 1)
        if a_dir != b_dir:
            asc = self.treeWidget().header().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
            return a_dir if asc else b_dir   # folders always on top
        if col in (COL_DATE, COL_SIZE):
            return (self.data(col, Qt.ItemDataRole.UserRole) or 0) < (other.data(col, Qt.ItemDataRole.UserRole) or 0)
        return self.text(col).lower() < other.text(col).lower()


COL_NAME, COL_DATE, COL_SIZE, COL_KIND, COL_PERM = range(5)


class PathBar(QWidget):
    """Finder-style path bar: click a segment to go to that folder, double-click empty space to type a path."""
    path_entered = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("PathBar")
        self.path = ""
        self.stack = QStackedLayout(self)
        self.crumbs = QWidget()
        self.crumb_lay = QHBoxLayout(self.crumbs)
        self.crumb_lay.setContentsMargins(0, 0, 0, 0)
        self.crumb_lay.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Type a path and press Enter (Esc to cancel)"))
        self.edit.returnPressed.connect(self._commit)
        self.edit.editingFinished.connect(lambda: self.stack.setCurrentIndex(0))
        self.stack.addWidget(self.crumbs)
        self.stack.addWidget(self.edit)
        self.setToolTip(tr("Click a path segment to go there · double-click empty space to type a path"))

    # keep the same call interface as the old QLineEdit
    def setText(self, path: str) -> None:
        self.set_path(path)

    def text(self) -> str:
        return self.path

    def set_path(self, path: str) -> None:
        self.path = path
        while self.crumb_lay.count():
            w = self.crumb_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        parts = [p for p in path.split("/") if p]
        segs = [("/", "/")]
        acc = ""
        for part in parts:
            acc += "/" + part
            segs.append((part, acc))
        if len(segs) > 5:   # collapse the leading part when long
            segs = segs[:1] + [("…", None)] + segs[-3:]
        for i, (label, target) in enumerate(segs):
            if i:
                sep = QLabel("›")
                self.crumb_lay.addWidget(sep)
            b = QToolButton()
            b.setText(label)
            if i == len(segs) - 1:
                b.setObjectName("Current")
            if target is None:
                b.clicked.connect(self.start_edit)
                b.setToolTip(path)
            else:
                b.clicked.connect(lambda _=False, t=target: self.path_entered.emit(t))
            self.crumb_lay.addWidget(b)
        self.crumb_lay.addStretch(1)
        self.stack.setCurrentIndex(0)

    def start_edit(self):
        self.edit.setText(self.path)
        self.stack.setCurrentIndex(1)
        self.edit.setFocus()
        self.edit.selectAll()

    def mouseDoubleClickEvent(self, e):
        self.start_edit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.stack.setCurrentIndex(0)
        else:
            super().keyPressEvent(e)

    def _commit(self):
        t = self.edit.text().strip() or "/"
        self.stack.setCurrentIndex(0)
        self.path_entered.emit(t)


def _owner_of(attr) -> str:
    """owner:group from an ls -l style longname (falls back to uid:gid)."""
    parts = (getattr(attr, "longname", "") or "").split()
    if len(parts) >= 4:
        return f"{parts[2]}:{parts[3]}"
    uid, gid = getattr(attr, "st_uid", None), getattr(attr, "st_gid", None)
    return f"{uid}:{gid}" if uid is not None else ""


class MutedDelegate(QStyledItemDelegate):
    """Secondary columns (modified/size/kind/permissions) are grey like Finder; selected rows keep white text."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if not (option.state & QStyle.StateFlag.State_Selected):
            option.palette.setColor(QPalette.ColorRole.Text, QColor(icons.theme.current().muted))


class FileTree(QTreeWidget):
    files_dropped = Signal(list, object)  # local paths, target item(or None)
    drag_out = Signal()                   # started dragging remote items out

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, actions):
        self.drag_out.emit()

    def dragEnterEvent(self, e):
        # don't accept drags from ourselves (download placeholders) as uploads
        if e.mimeData().hasUrls() and e.source() is None:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is None:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths, self.itemAt(e.position().toPoint()))
            e.acceptProposedAction()


class SftpExplorer(QWidget):
    cd_requested = Signal(str)
    navigated = Signal(str)   # user changed folders in the explorer directly (for terminal sync)
    status = Signal(str)
    disk_updated = Signal(object)   # diskusage.Summary or None (server disk space, read once per connection)

    def __init__(self, session_id: str, settings: dict, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.settings = settings
        self.conn: SshConnection | None = None
        self.browse: SftpWorker | None = None
        self.transfer: SftpWorker | None = None
        self.cwd = ""
        self._target = ""
        self.home = ""
        self.history: list[str] = []
        self.forward: list[str] = []
        self._pending_select = None
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_local_changed)
        # local -> (remote, sha256 of the content last synced with the server)
        self.edit_map: dict[str, tuple[str, str]] = {}
        self._downloading: set[str] = set()   # local files being downloaded (ignore change notifications)
        self._asking: set[str] = set()        # files with an upload confirmation dialog open
        self._change_timers: dict[str, QTimer] = {}
        self._locators: list = []
        self.disk_summary = None
        self.disk_time = 0.0
        self.disk_name = ""
        self._disk_card = None
        self._build()

    # ------------------------------------------------------------ layout
    def _build(self):
        self.setObjectName("Explorer")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        top = QWidget()
        top.setObjectName("ExplorerBar")
        tl = QVBoxLayout(top)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(2)

        def btn(name, tip, slot, row=bar):
            b = QToolButton()
            icons.bind(b, name)
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b
        self.back_btn = btn("back", tr("Back"), self.go_back)
        self.fwd_btn = btn("forward", tr("Forward"), self.go_forward)
        btn("up", tr("Parent folder (Backspace)"), self.go_up)
        btn("home", tr("Home folder"), lambda: self.navigate(self.home or "."))
        btn("refresh", tr("Refresh (F5)"), self.refresh)
        bar.addStretch(1)
        btn("upload", tr("Upload… (you can also drag files in from {fm})", fm=paths.file_manager_name()), self.upload_dialog)
        btn("download", tr("Download… (you can also drag items out to {fm})", fm=paths.file_manager_name()), self.download_selected)
        btn("folder_plus", tr("New folder"), self.new_folder)
        btn("terminal", tr("Move the terminal to this folder (cd)"), self.cd_here)
        self.follow_chk = btn("link", "", lambda: None)
        self.follow_chk.setCheckable(True)
        self.follow_chk.setChecked(True)
        self.follow_chk.setToolTip(tr("Sync location — cd in the terminal moves the explorer, and changing folders in the explorer moves the terminal (bash/zsh)\n"
                                      "The terminal is left alone while a command is running or you are typing"))
        tl.addLayout(bar)
        self.path_edit = PathBar()
        self.path_edit.path_entered.connect(lambda p: self.navigate(p))
        tl.addWidget(self.path_edit)
        lay.addWidget(top)
        self._update_nav_buttons()

        self.tree = FileTree()
        self.tree.setHeaderLabels([tr("Name"), tr("Modified"), tr("Size"), tr("Kind"), tr("Permissions")])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.files_dropped.connect(self._on_dropped)
        self.tree.drag_out.connect(self._start_drag_out)
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setMinimumSectionSize(40)
        # Every column can be resized by dragging. Until the user does, the name column takes the free space;
        # widths the user sets are remembered (all tabs, next start).
        saved = self.settings.get("explorer_columns") or {}
        self._cols_user_sized = bool(saved)
        self._sizing = True
        for c, width in ((COL_NAME, 200), (COL_DATE, 118), (COL_SIZE, 64), (COL_KIND, 96), (COL_PERM, 92)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            h.resizeSection(c, int(saved.get(str(c), width)))
        self._sizing = False
        h.sectionResized.connect(self._on_column_resized)
        # columns can be shown/hidden via header right-click (permissions column shown by default)
        h.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        h.customContextMenuRequested.connect(self._header_menu)
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._muted_delegate = MutedDelegate(self.tree)
        for c in (COL_DATE, COL_SIZE, COL_KIND, COL_PERM):
            self.tree.setItemDelegateForColumn(c, self._muted_delegate)
        lay.addWidget(self.tree, 1)

        foot = QWidget()
        foot.setObjectName("StatusBar")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(10, 3, 8, 3)
        self.info = QLabel(tr("Waiting for connection"))
        self.info.setObjectName("Muted")
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(120)
        self.bar.hide()
        self.cancel_btn = QToolButton()
        self.cancel_btn.setText(tr("Cancel"))
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self._cancel_transfer)
        fl.addWidget(self.info, 1)
        fl.addWidget(self.bar)
        fl.addWidget(self.cancel_btn)
        self.disk_pill = diskui.DiskPill()
        self.disk_pill.clicked.connect(self.show_disk_card)
        fl.addWidget(self.disk_pill)
        lay.addWidget(foot)

    def _fit_name_column(self):
        """Give the name column the free width (only while the user has not resized columns)."""
        if self._cols_user_sized:
            return
        h = self.tree.header()
        others = sum(h.sectionSize(c) for c in (COL_DATE, COL_SIZE, COL_KIND, COL_PERM) if not h.isSectionHidden(c))
        self._sizing = True
        h.resizeSection(COL_NAME, max(140, self.tree.viewport().width() - others))
        self._sizing = False

    def _on_column_resized(self, _idx, _old, _new):
        if self._sizing:
            return
        self._cols_user_sized = True
        h = self.tree.header()
        self.settings["explorer_columns"] = {str(c): h.sectionSize(c) for c in range(h.count())}

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_name_column()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit_name_column()

    def _header_menu(self, pos):
        h = self.tree.header()
        m = QMenu(self)
        for c, label in ((COL_DATE, tr("Modified")), (COL_SIZE, tr("Size")), (COL_KIND, tr("Kind")), (COL_PERM, tr("Permissions"))):
            act = m.addAction(label)
            act.setCheckable(True)
            act.setChecked(not h.isSectionHidden(c))
            act.toggled.connect(lambda on, c=c: h.setSectionHidden(c, not on))
        m.exec(h.mapToGlobal(pos))

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Backspace:
            self.go_up()
        elif k == Qt.Key.Key_F5:
            self.refresh()
        elif k == Qt.Key.Key_F2:
            self.rename_selected()
        elif e.matches(QKeySequence.StandardKey.Delete):
            self.delete_selected()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            it = self.tree.currentItem()
            if it:
                self._on_double(it, 0)
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------ connection
    def attach(self, conn: SshConnection, start_dir: str = "") -> None:
        self.detach()
        self.conn = conn
        self.browse = SftpWorker(conn)
        self.browse.result.connect(self._on_result)
        self.browse.error.connect(self._on_error)
        self.browse.start()
        self.transfer = SftpWorker(conn)
        self.transfer.result.connect(self._on_result)
        self.transfer.error.connect(self._on_error)
        self.transfer.progress.connect(self._on_progress)
        self.transfer.note.connect(self._on_note)
        self.transfer.ask.connect(self._on_ask)
        self.transfer.start()
        self.browse.submit("home", job_simple(lambda s: s.normalize(".")))
        self.navigate(start_dir or ".", origin="user" if start_dir else "init")

    def transfer_active(self) -> bool:
        return bool(self.transfer and (self.transfer.busy or not self.transfer.q.empty()))

    def detach(self) -> None:
        for w in (self.browse, self.transfer):
            if w:
                w.cancel = True
                w.stop()
                w.wait(2000)
        self.browse = self.transfer = None
        if self.disk_summary is not None:
            self.disk_summary = None
            self.apply_disk_settings()
            self.disk_updated.emit(None)
        if self._disk_card is not None:
            self._disk_card.hide()

    # ------------------------------------------------------------ server disk space
    def disk_enabled(self) -> bool:
        return bool(self.settings.get("disk_show", True))

    def refresh_disk(self) -> None:
        """Ask the server once (statvfs on the explorer's own SFTP channel; never a scan or a command)."""
        if self.browse and self.disk_enabled():
            home = self.home
            self.browse.submit("disk", job_simple(lambda s: diskusage.query(s, home)))

    def apply_disk_settings(self) -> None:
        warn, crit = diskui.thresholds(self.settings)
        show = self.disk_enabled() and self.disk_summary is not None
        self.disk_pill.set_summary(self.disk_summary if show else None, warn, crit)
        self.disk_pill.setVisible(show)
        if not show and self._disk_card is not None:
            self._disk_card.hide()

    def show_disk_card(self) -> None:
        if self.disk_summary is None:
            return
        if self._disk_card is None:
            self._disk_card = diskui.DiskCard(self)
            self._disk_card.refresh_requested.connect(self.refresh_disk)
        warn, crit = diskui.thresholds(self.settings)
        self._disk_card.fill(self.disk_name, self.disk_summary, warn, crit, self.disk_time)
        self._disk_card.show_at(self.disk_pill)

    # ------------------------------------------------------------ navigation
    def navigate(self, path: str, push: bool = True, origin: str = "user") -> None:
        """origin: user (direct navigation -> sync terminal) | follow (following the terminal) | refresh"""
        if not self.browse:
            return
        if not path.startswith("/") and path not in (".",) and self.cwd:
            path = posixpath.normpath(posixpath.join(self.cwd, path))
        if push and self.cwd and self.cwd != path:
            self.history.append(self.cwd)
            del self.history[:-50]
            self.forward.clear()
        self.info.setText(tr("Loading… {path}", path=path))
        self._target = path   # so comparisons use the intended destination even before the listing arrives
        self.browse.submit("list", job_list(path, origin))

    def refresh(self) -> None:
        if self.cwd:
            self.navigate(self.cwd, push=False, origin="refresh")

    def go_up(self) -> None:
        if self.cwd and self.cwd != "/":
            self._pending_select = posixpath.basename(self.cwd)
            self.navigate(posixpath.dirname(self.cwd.rstrip("/")) or "/")

    def go_back(self) -> None:
        if self.history:
            if self.cwd:
                self.forward.append(self.cwd)
            self.navigate(self.history.pop(), push=False)

    def go_forward(self) -> None:
        if self.forward:
            if self.cwd:
                self.history.append(self.cwd)
            self.navigate(self.forward.pop(), push=False)

    def _update_nav_buttons(self) -> None:
        self.back_btn.setEnabled(bool(self.history))
        self.fwd_btn.setEnabled(bool(self.forward))

    def follow(self, path: str) -> None:
        """Terminal cwd change notification (OSC 7)."""
        if self.follow_chk.isChecked() and path and path != (self._target or self.cwd):
            self.navigate(path, origin="follow")

    # ------------------------------------------------------------ result handling
    def _on_result(self, tag: str, payload):
        if tag == "home":
            self.home = payload
            self.refresh_disk()
        elif tag == "disk":
            self.disk_summary = payload
            self.disk_time = time.time()
            if payload is not None:
                try:
                    diskusage.save_last(self.session_id, payload)
                except OSError:
                    pass
            self.apply_disk_settings()
            if self._disk_card is not None and self._disk_card.isVisible():
                if payload is None:
                    self._disk_card.hide()
                else:
                    warn, crit = diskui.thresholds(self.settings)
                    self._disk_card.fill(self.disk_name, payload, warn, crit, self.disk_time)
            self.disk_updated.emit(payload)
        elif tag == "list":
            path, entries, origin = payload
            self._fill(path, entries)
            if origin == "user":
                self.navigated.emit(path)
        elif tag == "download":
            self._done(tr("Download complete → {path}", path=payload))
        elif tag == "upload_check":
            self._upload_checked(*payload)
        elif tag == "upload":
            self._done(tr("Upload complete"))
            if payload == self.cwd:
                self.refresh()
        elif tag in ("open", "open_with"):
            local, remote = payload
            self._done("")
            self._downloading.discard(local)
            self.edit_map[local] = (remote, file_digest(local))
            if local not in self.watcher.files():
                self.watcher.addPath(local)
            hwnd = int(self.window().winId())
            if tag == "open_with" or not winopen.open_default(local):
                # user chose to pick, or no associated program for the type (.conf, .log, no extension, etc.)
                winopen.open_with_dialog(local, hwnd)
        elif tag == "reupload":
            self._done(tr("Saved to server: {path}", path=payload))
        elif tag in ("delete", "mkdir", "rename"):
            self.refresh()
        elif tag == "stat_open":
            path, is_dir = payload
            if is_dir:
                self.navigate(path)
            else:
                self.open_remote(path)

    def _on_error(self, tag: str, msg: str):
        if tag == "disk":
            return   # disk space is a nice-to-have: never report it as an error
        if tag in ("upload", "download", "open", "open_with", "reupload"):
            self._done("")
        if tag in ("open", "open_with"):
            self._downloading.clear()
        if tag == "list":
            self._target = self.cwd   # drop the unreachable destination from the target
            self.path_edit.setText(self.cwd)
        if msg == CANCELLED:
            self.info.setText(tr("Cancelled"))
            return
        self.info.setText(tr("Error: {msg}", msg=msg))
        if tag in ("upload", "upload_check", "download", "reupload", "delete", "mkdir", "rename"):
            QMessageBox.warning(self, tr("File operation failed"), msg)

    def _on_progress(self, label: str, done: int, total: int):
        self.bar.show()
        self.cancel_btn.show()
        if total <= 0 and done > 0:          # size not known yet (large download counted on the way)
            self.bar.setMaximum(0)
            self.info.setText(tr("{label}  ({done} received)", label=label, done=human_size(done)))
            return
        self.bar.setMaximum(max(1, total // 1024))
        self.bar.setValue(done // 1024)
        pct = (done * 100 // total) if total else 100
        self.info.setText(f"{label}  {pct}%  ({human_size(done)} / {human_size(total)})")

    def _on_ask(self, req: dict):
        info = req["info"]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("Large download"))
        box.setText(tr("This download is at least {size} in {n} files.", size=human_size(info["bytes"]),
                       n=f"{info['files']:,}"))
        detail = tr("Counting stopped once it passed the limit set in Settings.")
        linked = info.get("linked") or []
        if linked:
            names = ", ".join(linked[:5]) + (" …" if len(linked) > 5 else "")
            detail += "\n\n" + tr("It includes linked folders: {names}", names=names)
        box.setInformativeText(detail)
        all_btn = box.addButton(tr("Download all"), QMessageBox.ButtonRole.AcceptRole)
        skip_btn = box.addButton(tr("Skip linked folders"), QMessageBox.ButtonRole.ActionRole) if linked else None
        cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel_btn)
        box.exec()
        clicked = box.clickedButton()
        req["answer"] = "all" if clicked is all_btn else ("no_links" if skip_btn is not None and clicked is skip_btn
                                                         else "cancel")
        req["event"].set()

    def _on_note(self, text: str):
        self.cancel_btn.show()
        self.info.setText(text)

    def _done(self, msg: str):
        self.bar.hide()
        self.cancel_btn.hide()
        if msg:
            self.info.setText(msg)

    def _cancel_transfer(self):
        if self.transfer:
            self.transfer.cancel = True

    def _fill(self, path: str, entries):
        self.cwd = path
        self.path_edit.setText(path)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        select = None
        for a in entries:
            if a.filename in (".", ".."):
                continue
            mode = a.st_mode or 0
            is_dir = stat.S_ISDIR(mode)
            is_link = stat.S_ISLNK(mode)
            kind = tr("Folder") if is_dir else (tr("Link") if is_link else icons.kind_of(a.filename)[0])
            it = _Item([a.filename,
                        time.strftime("%Y-%m-%d %H:%M", time.localtime(a.st_mtime or 0)),
                        "--" if is_dir else human_size(a.st_size or 0),
                        kind,
                        stat.filemode(mode)])
            owner = _owner_of(a)
            it.setToolTip(COL_PERM, f"{stat.filemode(mode)}  ({oct(stat.S_IMODE(mode))[2:]:0>3})"
                                    + ("\n" + tr("Owner: {owner}", owner=owner) if owner else ""))
            it.setIcon(COL_NAME, icons.folder(is_link) if is_dir else icons.file(a.filename, is_link))
            it.setData(0, Qt.ItemDataRole.UserRole, posixpath.join(path, a.filename))
            it.setData(0, Qt.ItemDataRole.UserRole + 1, is_dir)
            it.setData(0, Qt.ItemDataRole.UserRole + 2, is_link)
            it.setData(COL_SIZE, Qt.ItemDataRole.UserRole, a.st_size or 0)
            it.setData(COL_DATE, Qt.ItemDataRole.UserRole, a.st_mtime or 0)
            it.setTextAlignment(COL_SIZE, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.tree.addTopLevelItem(it)
            if a.filename == self._pending_select:
                select = it
        self.tree.setSortingEnabled(True)
        self._pending_select = None
        if select:
            self.tree.setCurrentItem(select)
            self.tree.scrollToItem(select)
        n = self.tree.topLevelItemCount()
        self.info.setText(tr("{n} items", n=n))
        self._update_nav_buttons()

    # ------------------------------------------------------------ actions
    def _selected_paths(self) -> list[str]:
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()]

    def _on_double(self, item, _col):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if item.data(0, Qt.ItemDataRole.UserRole + 1):
            self.navigate(path)
        elif item.data(0, Qt.ItemDataRole.UserRole + 2) and self.browse:
            self.browse.submit("stat_open", job_simple(
                lambda s, p=path: (p, stat.S_ISDIR(s.stat(p).st_mode))))
        else:
            self.open_remote(path)

    def open_remote(self, remote: str, choose: bool = False):
        """Download a remote file to a temp folder and open it. choose=True shows the Open-with dialog."""
        if not self.transfer:
            return
        key = hashlib.sha1(f"{self.session_id}:{posixpath.dirname(remote)}".encode("utf-8")).hexdigest()[:10]
        try:
            local = safe_join(os.path.join(tempfile.gettempdir(), "JeopsokHeyou", key), posixpath.basename(remote))
        except UnsafeName:
            QMessageBox.warning(self, tr("Cannot open"), tr("This file name cannot be used safely on this computer.\n\n{path}", path=remote))
            return
        # so change notifications during re-download are not mistaken for "upload?"
        if local in self.watcher.files():
            self.watcher.removePath(local)
        self._downloading.add(local)
        self.transfer.submit("open_with" if choose else "open", job_get_file(remote, local))

    def _on_local_changed(self, local: str):
        # editors report a save several times, so debounce and handle it once
        t = self._change_timers.get(local)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(700)
            t.timeout.connect(lambda l=local: self._ask_reupload(l))
            self._change_timers[local] = t
        t.start()

    def _ask_reupload(self, local: str):
        if local in self._downloading or local in self._asking:
            return
        info = self.edit_map.get(local)
        if not info or not os.path.exists(local):
            return
        if local not in self.watcher.files():
            self.watcher.addPath(local)  # handle editors that save via rename
        remote, last = info
        digest = file_digest(local)
        if not digest or digest == last:
            return  # only opened, or saved with identical content -> don't ask
        self.edit_map[local] = (remote, digest)
        self._asking.add(local)
        try:
            r = QMessageBox.question(self, tr("Upload changed file"),
                                     tr("Save the locally modified file to the server?\n\n{path}", path=remote))
        finally:
            self._asking.discard(local)
        if r == QMessageBox.StandardButton.Yes and self.transfer:
            self.transfer.submit("reupload", job_put_file(local, remote))
        # if saved again while the dialog was open, ask once more
        if file_digest(local) != self.edit_map.get(local, ("", ""))[1]:
            self._on_local_changed(local)

    def upload_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Select files to upload"))
        if files:
            self.upload(files, self.cwd)

    def upload(self, local_paths: list[str], remote_dir: str):
        """Upload after checking for names that already exist in the remote folder (asks before overwriting)."""
        if self.transfer and remote_dir and local_paths:
            self.transfer.submit("upload_check", job_upload_check(local_paths, remote_dir))

    def _upload_checked(self, local_paths: list[str], remote_dir: str, existing: list):
        skip: set = set()
        if existing:
            choice = ask_overwrite(self, existing, remote_dir)
            if choice == "cancel":
                self.info.setText(tr("Upload cancelled"))
                return
            if choice == "skip":
                skip = {n for n, _d in existing}
        if len(skip) >= len(local_paths):
            self.info.setText(tr("Nothing to upload"))
            return
        self.transfer.submit("upload", job_upload(local_paths, remote_dir, skip))

    def _on_dropped(self, paths: list, target):
        remote_dir = self.cwd
        if target is not None and target.data(0, Qt.ItemDataRole.UserRole + 1):
            remote_dir = target.data(0, Qt.ItemDataRole.UserRole)
        self.upload(paths, remote_dir)

    # ------------------------------------------------------------ drag-out download
    def _start_drag_out(self):
        sel = self.tree.selectedItems()
        if not sel or not self.transfer:
            return
        remote, items = [], []
        for it in sel:
            r = it.data(0, Qt.ItemDataRole.UserRole)
            try:
                name = local_name(posixpath.basename(r))   # same naming rule as when downloading
            except UnsafeName:
                continue
            remote.append(r)
            items.append((name, bool(it.data(0, Qt.ItemDataRole.UserRole + 1))))
        if not items:
            return
        staging, paths, marker = dragout.make_placeholders(items)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        drag = QDrag(self.tree)
        drag.setMimeData(mime)
        drag.setPixmap(sel[0].icon(0).pixmap(QSize(32, 32)))
        result = drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
        if result == Qt.DropAction.IgnoreAction:
            dragout.cleanup_staging(staging)
            return
        self.info.setText(tr("Checking the drop location…"))
        loc = dragout.DropLocator(items[0][0], items[0][1], marker)
        self._locators.append(loc)

        def done_locating():
            dragout.cleanup_staging(staging)
            if loc in self._locators:
                self._locators.remove(loc)

        def on_found(folder):
            done_locating()
            log.info("drag-out: dropped into %s (%d items)", folder, len(remote))
            if self.transfer:
                self.transfer.submit("download", job_download_drop(remote, folder, items, marker,
                                                                   confirm_limits(self.settings)))
            else:
                dragout.remove_placeholders(folder, items, marker, only_untouched=True)

        def on_missing():
            done_locating()
            log.info("drag-out: drop location not found")
            self.info.setText(tr("Couldn't find the drop location — drop onto a {fm} window or the desktop", fm=paths.file_manager_name()))
        loc.found.connect(on_found)
        loc.not_found.connect(on_missing)
        loc.start()

    def download_selected(self):
        paths = self._selected_paths()
        if not paths or not self.transfer:
            return
        start = self.settings.get("download_dir") or str(Path.home() / "Downloads")
        d = QFileDialog.getExistingDirectory(self, tr("Save to folder"), start)
        if not d:
            return
        self.settings["download_dir"] = d
        self.transfer.submit("download", job_download(paths, d, confirm_limits(self.settings)))

    def new_folder(self):
        if not self.browse or not self.cwd:
            return
        name, ok = QInputDialog.getText(self, tr("New folder"), tr("Folder name:"))
        if ok and name.strip():
            p = posixpath.join(self.cwd, name.strip())
            self._pending_select = name.strip()
            self.browse.submit("mkdir", job_simple(lambda s: s.mkdir(p)))

    def rename_selected(self):
        it = self.tree.currentItem()
        if not it or not self.browse:
            return
        old = it.data(0, Qt.ItemDataRole.UserRole)
        name, ok = QInputDialog.getText(self, tr("Rename"), tr("New name:"), text=posixpath.basename(old))
        if ok and name.strip() and name.strip() != posixpath.basename(old):
            new = posixpath.join(posixpath.dirname(old), name.strip())
            self._pending_select = name.strip()
            self.browse.submit("rename", job_simple(lambda s: s.rename(old, new)))

    def delete_selected(self):
        paths = self._selected_paths()
        if not paths or not self.browse:
            return
        names = "\n".join(posixpath.basename(p) for p in paths[:10])
        more = "\n" + tr("… and {n} more", n=len(paths) - 10) if len(paths) > 10 else ""
        r = QMessageBox.warning(self, tr("Confirm delete"),
                                tr("The following {n} items will be permanently deleted from the server.\n"
                                   "(Folders are deleted along with everything inside)", n=len(paths))
                                + f"\n\n{names}{more}",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self.browse.submit("delete", job_delete(paths))

    def cd_here(self, path: str | None = None):
        target = path if isinstance(path, str) and path else self.cwd
        if target:
            self.cd_requested.emit(target)

    def _context_menu(self, pos):
        it = self.tree.itemAt(pos)
        m = QMenu(self)
        if it:
            path = it.data(0, Qt.ItemDataRole.UserRole)
            is_dir = it.data(0, Qt.ItemDataRole.UserRole + 1)
            m.addAction(tr("Open"), lambda: self._on_double(it, 0))
            if not is_dir:
                m.addAction(tr("Open with…"), lambda: self.open_remote(path, choose=True))
            if is_dir:
                m.addAction(tr("Go to this folder in the terminal (cd)"), lambda: self.cd_here(path))
            m.addAction(tr("Download…"), self.download_selected)
            m.addSeparator()
            m.addAction(tr("Rename (F2)"), self.rename_selected)
            m.addAction(tr("Delete (Del)"), self.delete_selected)
            m.addSeparator()
            m.addAction(tr("Copy path"), lambda: QGuiApplication.clipboard().setText(path))
            m.addAction(tr("Copy name"), lambda: QGuiApplication.clipboard().setText(posixpath.basename(path)))
            m.addSeparator()
        m.addAction(tr("Upload…"), self.upload_dialog)
        m.addAction(tr("New folder…"), self.new_folder)
        m.addAction(tr("Copy current path"), lambda: QGuiApplication.clipboard().setText(self.cwd))
        m.addAction(tr("Go to the current folder in the terminal (cd)"), self.cd_here)
        m.addAction(tr("Refresh (F5)"), self.refresh)
        m.exec(self.tree.viewport().mapToGlobal(pos))


def cleanup_temp(max_age_days: float = 3.0) -> int:
    """Clean up temp copies of opened remote files: remove folders not modified for max_age_days
    (recent files that may still be edited are kept). Returns the number of folders removed."""
    import shutil
    base = os.path.join(tempfile.gettempdir(), "JeopsokHeyou")
    if not os.path.isdir(base):
        return 0
    limit = time.time() - max_age_days * 86400
    removed = 0
    for entry in os.scandir(base):
        if not entry.is_dir(follow_symlinks=False):
            continue
        newest = entry.stat().st_mtime
        for root, _dirs, files in os.walk(entry.path):
            for f in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, f)))
                except OSError:
                    pass
        age_limit = time.time() - 86400 if entry.name == "drag" else limit   # drag placeholders: one day
        if newest < age_limit:
            shutil.rmtree(entry.path, ignore_errors=True)
            removed += 1
    return removed
