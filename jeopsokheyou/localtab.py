# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Local terminals: a shell of this computer in a tab, with this computer's files in the explorer next to it.

Works like a server tab — split, tear off, find, logs, snippets — and the explorer follows the shell's folder
(cmd, PowerShell, bash/zsh in WSL, Git Bash and macOS).
"""
from __future__ import annotations

import uuid

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from . import applog, localshell
from .config import Session
from .i18n import tr
from .localfs import LocalConnection
from .mainwindow import SessionTab, TerminalPane
from .ssh import ShellReader

log = applog.get("local")


class LocalPane(TerminalPane):
    """A terminal running a shell of this computer."""

    def __init__(self, font, settings, session: Session, profile: localshell.ShellProfile):
        super().__init__(font, settings, session)
        self.profile = profile
        self.reported = ""             # the folder as the shell wrote it (shown in the title bar)

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
        if path.startswith("file://"):
            slash = raw.find("/")
            raw = raw[slash:] if slash >= 0 else "/"
        self.reported = raw
        virtual = localshell.reported_to_virtual(self.profile, raw)
        super()._on_osc7(virtual or raw)

    def cd_command(self, path: str) -> str | None:
        return localshell.cd_line(self.profile, path)

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
        return LocalPane(self.main.term_font, self.main.settings, self.session, self.profile)

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
