# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Local terminals: a shell of this computer in a tab, with this computer's files in the explorer next to it.

Works like a server tab — split, tear off, find, logs, snippets — and the explorer follows the shell's folder
(cmd, PowerShell, bash/zsh in WSL, Git Bash and macOS).
"""
from __future__ import annotations

import uuid

import os

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QToolButton,
                               QVBoxLayout)

from . import applog, localshell
from .config import Session
from .i18n import tr
from .localfs import LocalConnection
from .mainwindow import SessionTab, TerminalPane
from .ssh import ConnectWorker, ShellReader, SshConnection

log = applog.get("local")


class LocalPane(TerminalPane):
    """A terminal running a shell of this computer."""
    hide_echo = not localshell.IS_WIN       # ConPTY keeps its own screen: the explorer's cd is shown, not erased
    remote_changed = Signal(object, str)     # (pane, host): the shell went on to another computer ("" = back here)
    remote_report = Signal(object, str)      # (pane, folder): the other computer's shell reported where it is

    def __init__(self, font, settings, session: Session, profile: localshell.ShellProfile):
        super().__init__(font, settings, session)
        self.profile = profile
        self.reported = ""             # the folder as the shell wrote it (shown in the title bar)
        self.remote_host = ""          # another computer the shell is on now (ssh run in it), "" = this one
        self.ssh_target = None         # what the last ssh command typed here asked for ({"user", "host", …})

    def start(self, conn=None) -> None:
        self.disconnected = False
        self._hiding = self._pending_cd = None
        self._late_cd = None
        self.cwd, self.at_prompt, self.input_dirty = "", False, False
        self.reported = ""
        self.chan = localshell.LocalProcess(self.profile, self.screen.columns, self.screen.lines)
        self.writer = self.chan.sendall
        self.on_resize = self._resize_pty
        self.reader = ShellReader(self.chan)
        self.reader.data.connect(self._on_data)
        self.reader.closed.connect(self._on_closed)
        self.reader.start()
        if localshell.hooked_at_start(self.profile):
            self._inject_state = "done"            # the shell reports its folder from its first prompt on
        elif localshell.injectable(self.profile) and self.session.follow_cwd:
            self._inject_state = "waiting"
            self._settle.start(3000)
        else:
            self._inject_state = "off"
        if self.settings.get("log_sessions") and self.logger is None:
            self.start_log()

    def _on_osc7(self, path: str) -> None:
        raw = path[7:] if path.startswith("file://") else path
        host = ""
        if path.startswith("file://"):
            slash = raw.find("/")
            host = raw[:slash] if slash >= 0 else raw
            raw = raw[slash:] if slash >= 0 else "/"
        if not localshell.is_this_computer(host):
            # a shell on another computer (ssh run here) reports its folder: not a place on this computer, and
            # nothing may be typed into it for the explorer
            self.at_prompt = False
            if host != self.remote_host:
                self.remote_host = host
                self.remote_changed.emit(self, host)
            self.remote_report.emit(self, raw)
            return
        if self.remote_host:
            self.remote_host = ""
            self.remote_changed.emit(self, "")
        self.reported = raw
        virtual = localshell.reported_to_virtual(self.profile, raw)
        super()._on_osc7(virtual or raw)

    def cd_command(self, path: str) -> str | None:
        if self.remote_host:
            return None                         # the shell is on another computer
        return localshell.cd_line(self.profile, path)

    def sync_cd(self, path: str) -> str:
        if self.remote_host:
            return "remote"
        return super().sync_cd(path)

    def _note_user_input(self, text: str) -> None:
        if "\r" in text and self.at_prompt and not self.remote_host:
            # the command line being run: an ssh to another computer can be opened as a server tab
            target = localshell.parse_ssh_command(self._typed_line())
            if target is not None:
                # from now on the shell may be on that computer (until this computer's prompt reports again),
                # even when that computer never reports its folder
                self.ssh_target = target
                self.remote_host = target["host"]
                self.remote_changed.emit(self, target["host"])
        super()._note_user_input(text)

    def _typed_line(self) -> str:
        """The line at the cursor, with the rows a long line was wrapped onto."""
        s = self.screen
        row = s.sb_total + s.cursor.y
        a, b = self._line_bounds(row)
        out = []
        for r in range(a, b + 1):
            line = self._line_at(r)
            if line is not None:
                out.append("".join(line[x].data for x in range(s.columns)))
        return "".join(out).rstrip()

    def _emit_resize(self) -> None:
        rows, cols = self._want_size
        if localshell.IS_WIN and (cols < 20 or rows < 3):
            # a passing size while the window is laid out: ConPTY would wrap its own copy of the screen to it and
            # the two copies would no longer match (input drawn in the wrong place)
            return
        super()._emit_resize()

    def shown_cwd(self) -> str:
        return self.reported or self.cwd


class LocalSessionTab(SessionTab):
    """A tab with a shell of this computer and this computer's files."""

    def __init__(self, profile: localshell.ShellProfile, main):
        self.profile = profile
        session = Session(name=profile.name, host="", follow_cwd=True, encoding="utf-8",
                          id="local-" + uuid.uuid4().hex)
        super().__init__(session, main)

    def _new_pane(self):
        pane = LocalPane(self.main.term_font, self.main.settings, self.session, self.profile)
        pane.remote_changed.connect(self._remote_changed)
        pane.remote_report.connect(self._remote_report)
        return pane

    # -- the shell went on to another computer: offer to open it as a server tab (with its files)
    def _remote_banner(self) -> QFrame:
        if getattr(self, "remote_banner", None) is None:
            b = QFrame()
            b.setObjectName("IdleBanner")
            from PySide6.QtWidgets import QSizePolicy
            b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            lay = QHBoxLayout(b)
            lay.setContentsMargins(14, 6, 8, 6)
            self.remote_label = QLabel()
            self.remote_label.setWordWrap(True)
            close = QToolButton()
            close.setAutoRaise(True)
            close.setText("✕")
            close.setToolTip(tr("Hide"))
            close.clicked.connect(b.hide)
            lay.addWidget(self.remote_label, 1)
            lay.addWidget(close)
            self.layout().insertWidget(0, b)
            b.hide()
            self.remote_banner = b
        return self.remote_banner

    def _remote_changed(self, pane, host: str):
        b = self._remote_banner()
        self._remote_pane = pane
        if host:
            t = pane.ssh_target or {}
            shown = (t.get("user") + "@" if t.get("user") else "") + (t.get("host") or host)
            self._remote_shown = shown
            self.remote_label.setText(tr("The terminal is connected to {host}. The explorer shows this computer, "
                                         "and the terminal is not moved while it is there.", host=shown))
            b.show()
            if self._explorer_for(pane) is self.explorer:
                self._start_remote(pane)
        elif not any(getattr(p, "remote_host", "") for p in self.panes):
            b.hide()
            self._end_remote()

    # -- the explorer follows the terminal to that computer (its own SFTP login; the terminal's ssh is separate)
    _remote = None

    def _start_remote(self, pane):
        """Show the server's files in the explorer: a saved host connects by itself; a password is asked once the
        terminal's own ssh login is over (not while the user types it there) and the host is saved when it works."""
        if self._remote is not None and self._remote["pane"] is pane:
            return
        self._end_remote()
        target = pane.ssh_target
        if not target or not target.get("host"):
            return
        s = localshell.ssh_session(target)
        matches = self.main.saved_matches(s)
        saved = matches[0] if matches else None
        if saved is not None:
            s = saved
        password = (saved.password if saved is not None else "") or ""
        r = {"pane": pane, "session": s, "saved": saved is not None, "password": password, "conn": None,
             "worker": None, "waiting": False, "try_keys": False, "where": "", "cache": {}}
        self._remote = r
        if s.auth == "key" or password:
            self._connect_remote()
        elif any(os.path.isfile(os.path.expanduser(f"~/.ssh/{k}")) for k in ("id_ed25519", "id_ecdsa", "id_rsa")):
            r["try_keys"] = True                 # this computer's keys may open it without asking
            self._connect_remote()
        else:
            self._wait_for_login()

    def _wait_for_login(self):
        r = self._remote
        r["waiting"] = True
        QTimer.singleShot(5000, lambda r=r: self._ask_remote_password(r))

    def _remote_report(self, pane, folder: str):
        r = self._remote
        if r is None or r["pane"] is not pane:
            return
        r["where"] = folder
        if r["waiting"]:
            self._ask_remote_password(r)        # the terminal's login is done: now the explorer may ask
        elif r["conn"] is not None:
            self.explorer.follow(folder)         # cd on that computer: the explorer follows

    def _ask_remote_password(self, r):
        if r is not self._remote or not r["waiting"] or not r["pane"].remote_host:
            return
        r["waiting"] = False
        s = r["session"]
        if not s.user:
            from PySide6.QtWidgets import QInputDialog
            user, ok = QInputDialog.getText(self, tr("User"), tr("Login user for {host}:", host=s.host))
            if not ok or not user.strip():
                return
            s.user = user.strip()
        from .dialogs import ask_password_saving
        pw = ask_password_saving(self, tr("Password for {target}:", target=f"{s.user}@{s.host}"), s,
                                 self.main.store if r["saved"] else None)
        if pw is None:
            return
        r["password"] = pw
        self._connect_remote()

    def _connect_remote(self):
        r = self._remote
        s = r["session"]
        if r["try_keys"]:
            from .config import Session
            s = Session(name=s.name, host=s.host, port=s.port, user=s.user, auth="key", id=s.id)
        from .tunnels import jump_credentials
        jumps = jump_credentials(self, self.main.store, s, r["cache"]) if s.jump else []
        if jumps is None:
            return
        conn = SshConnection(s, r["password"], "", jumps)
        worker = ConnectWorker(conn)
        r["worker"] = worker
        worker.ok.connect(lambda r=r, conn=conn: self._remote_ok(r, conn))
        worker.auth_failed.connect(lambda msg, r=r: self._remote_auth_failed(r, msg))
        worker.failed.connect(lambda msg, r=r: self._remote_failed(r, msg))
        worker.unknown_host.connect(lambda host, key, r=r: self._remote_unknown_host(r, host, key))
        self.remote_label.setText(tr("Opening {host} in the explorer…", host=self._remote_shown))
        worker.start()

    def _remote_ok(self, r, conn):
        if r is not self._remote or not r["pane"].remote_host:
            conn.close()                         # the terminal left that computer meanwhile
            return
        r["conn"] = conn
        s = r["session"]
        if not r["saved"] and not self.main.saved_matches(s):
            try:                                 # a new host that worked: keep it, like a quick connection
                if s.auth == "password" and r["password"] and self.main.settings.get("save_passwords", True):
                    s.password = r["password"]
                self.main.store.upsert(s)
                self.main.reload_sessions()
            except Exception as e:
                log.warning("could not save the new host: %s", e)
        start = r["where"] if r["where"].startswith("/") else ""
        self.explorer.attach(conn, start)
        self.explorer.path_edit.root_label = f"{s.user + '@' if s.user else ''}{s.host}:/"
        self.remote_label.setText(tr("The terminal is connected to {host}. The explorer shows its files; "
                                     "it goes back to this computer when you leave it.", host=self._remote_shown))

    def _remote_auth_failed(self, r, msg: str):
        if r is not self._remote:
            return
        if r["try_keys"]:
            r["try_keys"] = False                # the keys were not accepted: ask for the password
            self._wait_for_login()
            return
        r["password"] = ""
        self.remote_label.setText(msg)
        r["waiting"] = True
        self._ask_remote_password(r)

    def _remote_failed(self, r, msg: str):
        if r is self._remote:
            self.remote_label.setText(tr("The explorer could not open {host}: {error}", host=self._remote_shown,
                                         error=msg))

    def _remote_unknown_host(self, r, host, key):
        from .tunnels import ask_trust_host
        if r is self._remote and ask_trust_host(self, host, key):
            self._connect_remote()

    def _end_remote(self):
        """Back on this computer: the explorer shows it again and the server connection closes."""
        r, self._remote = self._remote, None
        if r is None:
            return
        if r["conn"] is not None:
            pane = r["pane"]
            self.explorer.attach(LocalConnection(), pane.cwd or "")
            r["conn"].close()

    def shutdown(self):
        self._end_remote()
        super().shutdown()


    def idle_limit(self) -> int:
        return 0                                   # a local shell never disconnects for being idle

    def _who(self) -> str:
        return f"{self.profile.name} (local)"

    def connect(self):
        """Start the shell (again, after it ended) and open this computer's files next to it."""
        if self.state == "connecting":
            return
        self.conn = LocalConnection()
        pane = self.panes[0]
        if self.state in ("closed", "failed"):
            pane.write_local("\x1b[2J\x1b[H")
        try:
            pane.start()
        except Exception as e:
            log.warning("local shell failed: %s: %s", self.profile.name, e)
            self.state = "failed"
            self._title()
            pane.disconnected = True
            pane.write_local("\x1b[31m" + tr("Cannot start {shell}: {error}", shell=self.profile.name, error=e)
                             + "\x1b[0m\r\n\x1b[33m[" + tr("Enter or R: start again") + "]\x1b[0m\r\n")
            return
        self.state = "connected"
        self._title()
        pane.setFocus()
        start = localshell.to_virtual(self.profile.start_dir) if self.profile.start_dir else ""
        if self.explorer.conn is None:
            self.explorer.attach(self.conn, start)
        for win in self.pane_windows:
            if win.explorer.conn is None:
                win.start_explorer()

    def _pane_closed(self, pane):
        if pane not in self.panes:
            return
        if len(self.panes) > 1:
            self._remove_pane(pane)
            return
        self.state = "closed"
        log.info("local shell ended: %s", self.profile.name)
        self._title()
        pane.write_local("\r\n\x1b[33m[" + tr("The shell has ended. Press Enter or R to start it again") + "]\x1b[0m\r\n")

    def _save_new_host(self):
        pass


# ---------------------------------------------------------------- Settings: the shells
class LocalShellDialog(QDialog):
    """Add or change a shell of the user's own."""

    def __init__(self, profile: localshell.ShellProfile | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Local terminal"))
        p = profile or localshell.ShellProfile("")
        form = QFormLayout(self)
        self.name = QLineEdit(p.name)
        self.command = QLineEdit(localshell.join_command(p.argv))
        self.command.setPlaceholderText(r"C:\msys64\usr\bin\bash.exe --login -i" if localshell.IS_WIN else "/bin/zsh -l")
        self.start = QLineEdit(p.start_dir)
        self.start.setPlaceholderText(tr("Home folder"))
        pick = QPushButton(tr("Browse…"))
        pick.clicked.connect(self._pick)
        row = QHBoxLayout()
        row.addWidget(self.start, 1)
        row.addWidget(pick)
        form.addRow(tr("Name"), self.name)
        form.addRow(tr("Command"), self.command)
        form.addRow(tr("Start folder"), row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.profile = p
        self.resize(520, self.sizeHint().height())

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, tr("Start folder"), self.start.text())
        if d:
            self.start.setText(d)

    def _ok(self):
        argv = localshell.split_command(self.command.text())
        if not self.name.text().strip() or not argv:
            QMessageBox.warning(self, tr("Local terminal"), tr("Enter a name and a command."))
            return
        self.profile = localshell.ShellProfile(self.name.text().strip(), localshell.guess_kind(argv), argv,
                                               self.start.text().strip(), custom=True,
                                               id=self.profile.id or uuid.uuid4().hex)
        self.accept()


class LocalShellsDialog(QDialog):
    """The shells found on this computer and the user's own; which one opens by default."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Local terminals"))
        self.custom = [localshell.ShellProfile.from_dict(d) for d in settings.get("local_shells") or []]
        for p in self.custom:
            p.custom = True
            p.id = p.id or uuid.uuid4().hex
        self.default = settings.get("local_shell_default", "")
        lay = QVBoxLayout(self)
        note = QLabel(tr("Shells found on this computer, then your own. The default one opens with the terminal button "
                         "and {key}.", key=_key_text()))
        note.setWordWrap(True)
        note.setObjectName("Muted")
        lay.addWidget(note)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._edit())
        self.list.currentRowChanged.connect(lambda _r: self._update_buttons())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.default_btn = QPushButton(tr("Use by default"))
        self.default_btn.clicked.connect(self._set_default)
        self.add_btn = QPushButton(tr("Add…"))
        self.add_btn.clicked.connect(self._add)
        self.edit_btn = QPushButton(tr("Edit…"))
        self.edit_btn.clicked.connect(self._edit)
        self.del_btn = QPushButton(tr("Remove"))
        self.del_btn.clicked.connect(self._remove)
        for b in (self.default_btn, self.add_btn, self.edit_btn, self.del_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(560, 380)
        self._fill()

    def _all(self) -> list:
        return localshell.detect_shells() + self.custom

    def _fill(self, select: int = 0):
        self.list.clear()
        all_ = self._all()
        default = self.default or (all_[0].key() if all_ else "")
        for p in all_:
            text = p.name + ("  ★" if p.key() == default else "")
            sub = tr("your own") if p.custom else tr("found on this computer")
            it = QListWidgetItem(f"{text}\n    {localshell.join_command(p.argv[:1])}  ·  {sub}")
            self.list.addItem(it)
        if all_:
            self.list.setCurrentRow(min(select, len(all_) - 1))
        self._update_buttons()

    def _current(self):
        r = self.list.currentRow()
        all_ = self._all()
        return all_[r] if 0 <= r < len(all_) else None

    def _update_buttons(self):
        p = self._current()
        own = p is not None and p.custom
        self.edit_btn.setEnabled(own)
        self.del_btn.setEnabled(own)
        self.default_btn.setEnabled(p is not None)

    def _set_default(self):
        p = self._current()
        if p:
            self.default = p.key()
            self._fill(self.list.currentRow())

    def _add(self):
        d = LocalShellDialog(None, self)
        if d.exec():
            self.custom.append(d.profile)
            self._fill(len(self._all()) - 1)

    def _edit(self):
        p = self._current()
        if not p or not p.custom:
            return
        d = LocalShellDialog(p, self)
        if d.exec():
            i = self.custom.index(p)
            self.custom[i] = d.profile
            self._fill(self.list.currentRow())

    def _remove(self):
        p = self._current()
        if p and p.custom:
            self.custom.remove(p)
            if self.default == p.key():
                self.default = ""
            self._fill(self.list.currentRow())

    def _ok(self):
        self.settings["local_shells"] = [p.to_dict() for p in self.custom]
        self.settings["local_shell_default"] = self.default
        self.accept()


def _key_text() -> str:
    from . import shortcuts
    return shortcuts.text("local_terminal", first_only=True)
