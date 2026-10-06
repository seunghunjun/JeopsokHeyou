# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Main window: session list + tabs + split terminals + SFTP explorer."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QFontDialog, QFrame, QHBoxLayout, QLabel, QInputDialog, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QSplitter,
                               QTabWidget, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import config, icons, paths, theme
from .config import Session, SessionStore
from .dialogs import SessionDialog
from .explorer import SftpExplorer, cleanup_temp, sh_quote
from .i18n import tr
from .ssh import ConnectWorker, ShellReader, SshConnection
from .terminal import TerminalWidget, pick_font
from . import __version__, applog, diskui, diskusage, forwarding, library, sshconfig, vault, vaultui
from .home import HomeTab, SnippetPicker
from .tunnels import (TunnelManager, ask_trust_host, error_text, import_mobaxterm_tunnels,
                      jump_credentials)

log = applog.get("session")

# Hook the shell (bash/zsh) so the terminal reports its current folder via OSC 7 on every cd.
# The final printf doubles as the "injection done" marker and the initial location report.
FOLLOW_CMD = (
    " if [ -n \"$ZSH_VERSION\" ]; then _mt_osc7(){ printf '\\033]7;%s\\007' \"$PWD\"; };"
    " precmd_functions+=(_mt_osc7); elif [ -n \"$BASH_VERSION\" ]; then"
    " PROMPT_COMMAND='printf \"\\033]7;%s\\007\" \"$PWD\"'\"${PROMPT_COMMAND:+; $PROMPT_COMMAND}\"; fi;"
    " printf '\\033]7;%s\\007' \"$PWD\"\r"
)
OSC7_MARK = "\x1b]7;"


class TerminalPane(TerminalWidget):
    """Terminal bound to a single shell channel."""
    closed = Signal(object)
    focused = Signal(object)
    close_requested = Signal(object)

    def __init__(self, font, settings, session: Session, parent=None):
        super().__init__(font, settings.get("scrollback", 5000), session.encoding, parent)
        self.screen.reflow = bool(settings.get("terminal_reflow", True))
        scheme = (settings.get("color_schemes") or {}).get(settings.get("terminal_scheme", ""))
        if scheme:
            self.apply_scheme(scheme)
        self.settings = settings
        self.apply_highlights(settings)
        self.session = session
        self.chan = None
        self.reader = None
        # Location-sync hook injection state
        self._inject_state = "off"   # off | waiting | injecting | done
        # Whether we are hiding the echo of commands typed by the app (hook injection, sync cd): None | "inject" | "cd"
        self._hiding: str | None = None
        self._pending_cd: str | None = None
        self._swallow = b""
        self._swallow_since = 0.0
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(350)
        self._settle.timeout.connect(self._inject)
        self._swallow_timeout = QTimer(self)
        self._swallow_timeout.setSingleShot(True)
        self._swallow_timeout.setInterval(2000)
        self._swallow_timeout.timeout.connect(self._flush_swallow)
        # Close button for a split pane (visible only when split)
        self.close_btn = QToolButton(self)
        self.close_btn.setText("✕")
        self.close_btn.setToolTip(tr("Close this split pane (Ctrl+Shift+W)"))
        self.close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.setStyleSheet(
            "QToolButton{color:#9aa0a6;background:rgba(43,45,48,200);border:1px solid #3a3d41;"
            "border-radius:3px;padding:0 4px;font-size:11px}"
            "QToolButton:hover{color:#fff;background:#c42b1c;border-color:#c42b1c}")
        self.close_btn.clicked.connect(lambda: self.close_requested.emit(self))
        self.close_btn.hide()

    def start(self, conn: SshConnection) -> None:
        self.disconnected = False
        self._hiding = self._pending_cd = None
        self.cwd, self.at_prompt, self.input_dirty = "", False, False
        self.chan = conn.open_shell(self.screen.columns, self.screen.lines)
        self.writer = self.chan.sendall
        self.on_resize = self._resize_pty
        self.reader = ShellReader(self.chan)
        self.reader.data.connect(self._on_data)
        self.reader.closed.connect(self._on_closed)
        self.reader.start()
        if self.session.follow_cwd:
            self._inject_state = "waiting"
            self._settle.start(3000)  # Inject after 3 s even if there is no output
        if self.settings.get("log_sessions") and self.logger is None:
            self.start_log()

    # ------------------------------------------------------------ keyword highlighting / session log
    def apply_highlights(self, settings) -> None:
        from .highlights import DEFAULT_RULES, compile_rules
        on = settings.get("highlight_enabled", True)
        self.highlight_rules = compile_rules(settings.get("highlight_rules", DEFAULT_RULES)) if on else []
        self.update()

    def start_log(self) -> str:
        from . import sessionlog
        if self.logger is not None:
            return str(self.logger.path)
        base = self.settings.get("log_dir") or str(sessionlog.default_dir())
        n = 1
        tab = self.parent()
        while tab is not None and not hasattr(tab, "panes"):
            tab = tab.parent()
        if tab is not None and self in tab.panes:
            n = tab.panes.index(self) + 1
        try:
            self.logger = sessionlog.SessionLog(sessionlog.log_path(base, self.session.title(), n),
                                                bool(self.settings.get("log_timestamps", True)))
        except OSError as e:
            self.write_local("\x1b[33m" + tr("Cannot write the session log: {error}", error=e) + "\x1b[0m\r\n")
            return ""
        self.write_local("\x1b[90m" + tr("Logging to {path}", path=self.logger.path) + "\x1b[0m\r\n")
        return str(self.logger.path)

    def stop_log(self) -> None:
        if self.logger is not None:
            path = self.logger.path
            self.logger.close()
            self.logger = None
            self.write_local("\x1b[90m" + tr("Logging stopped ({path})", path=path) + "\x1b[0m\r\n")

    def _resize_pty(self, cols, rows):
        if self.chan and not self.chan.closed:
            try:
                self.chan.resize_pty(width=cols, height=rows)
            except Exception:
                pass

    def _on_data(self, data: bytes):
        if self._inject_state == "waiting":
            self._settle.start(350)  # Inject once the login banner/prompt output settles
        if not self._hiding:
            self.feed(data)
            return
        self._swallow += data
        if len(self._swallow) > 65536 or time.monotonic() - self._swallow_since > 10:
            self._flush_swallow()   # Safety net: if the marker never arrives, show the output as is
            return
        self._swallow_timeout.start()  # Keep extending while echo keeps arriving
        text = self._swallow.decode(self.encoding, errors="replace")
        i = text.find(OSC7_MARK)
        if i < 0:
            return
        kind, self._hiding = self._hiding, None
        self._swallow_timeout.stop()
        self._swallow = b""
        if kind == "cd" and "cd:" in text[:i]:
            # If cd failed (permission denied etc.), show the output instead of hiding it
            self.feed(text.encode(self.encoding, errors="replace"))
        else:
            # Hide the command echo and draw the new prompt where the old one was erased
            if kind == "cd":
                self._erase_prompt()
            else:
                self.write_local("\r\x1b[K")
            self.feed(text[i:].encode(self.encoding, errors="replace"))
        if kind == "inject":
            self._inject_state = "done"
        if self._pending_cd:
            path, self._pending_cd = self._pending_cd, None
            self.sync_cd(path)

    def _erase_prompt(self):
        s = self.screen
        up = (s.sb_total + s.cursor.y) - self.prompt_start
        self.write_local("\r" + (f"\x1b[{up}A" if up > 0 else "") + "\x1b[J")

    def _hide_and_send(self, kind: str, cmd: str) -> None:
        self._hiding = kind
        self._swallow = b""
        self._swallow_since = time.monotonic()
        self._swallow_timeout.start()
        try:
            self.chan.sendall(cmd.encode(self.encoding, errors="replace"))
        except Exception:
            self._flush_swallow()

    def _inject(self):
        if self._inject_state != "waiting" or not self.chan:
            return
        self._inject_state = "injecting"
        self._hide_and_send("inject", FOLLOW_CMD)

    def _flush_swallow(self):
        if not self._hiding:
            return
        if self._hiding == "inject":
            self._inject_state = "done"
        self._hiding = None
        self._pending_cd = None
        data, self._swallow = self._swallow, b""
        if data:
            self.feed(data)

    def sync_cd(self, path: str) -> str:
        """Quietly cd the terminal to the explorer location. Result: sent|queued|same|busy|typing|unsupported|offline"""
        if not self.chan or self.disconnected:
            return "offline"
        if path == self.cwd:
            return "same"
        if self._hiding or self._inject_state in ("waiting", "injecting"):
            self._pending_cd = path   # Continue once the previous job finishes
            return "queued"
        if self._inject_state != "done" or not self.cwd:
            return "unsupported"      # Shell does not send OSC 7 (not bash/zsh)
        if self.screen.alt is not None or not self.at_prompt:
            return "busy"             # vim, tail -f, etc. running
        if self.input_dirty:
            return "typing"           # Don't clobber a command being typed
        self.at_prompt = False
        self._hide_and_send("cd", f" cd -- {sh_quote(path)}\r")
        return "sent"

    def _on_closed(self):
        self.disconnected = True
        self.closed.emit(self)

    def close_channel(self):
        if self.logger is not None:
            self.logger.close()
            self.logger = None
        if self.chan:
            try:
                self.chan.close()
            except Exception:
                pass
        if self.reader:
            self.reader.wait(1000)

    def focusInEvent(self, e):
        self.focused.emit(self)
        super().focusInEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.close_btn.adjustSize()
        self.close_btn.move(self.width() - self.SB_W - self.close_btn.width() - 4, 4)
        self.close_btn.raise_()


class SessionTab(QWidget):
    title_changed = Signal(object, str)

    def __init__(self, session: Session, main: "MainWindow", password: str = "", passphrase: str = ""):
        super().__init__()
        self.session = session
        self.main = main
        self.password = password or session.password
        self.passphrase = passphrase or session.passphrase
        self.conn: SshConnection | None = None
        self.worker: ConnectWorker | None = None
        self.panes: list[TerminalPane] = []
        self.active: TerminalPane | None = None
        self.state = "idle"
        self.last_activity = time.monotonic()
        self._close_reason = ""
        self.forward_runners: list[forwarding.ForwardRunner] = []
        self._jump_cache: dict = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # Idle auto-disconnect warning banner
        self.idle_banner = QFrame()
        self.idle_banner.setObjectName("IdleBanner")
        bl = QHBoxLayout(self.idle_banner)
        bl.setContentsMargins(14, 6, 8, 6)
        self.idle_label = QLabel()
        keep = QPushButton(tr("Stay connected"))
        keep.setDefault(True)
        keep.clicked.connect(self.touch)
        bl.addWidget(self.idle_label, 1)
        bl.addWidget(keep)
        self.idle_banner.hide()
        lay.addWidget(self.idle_banner)
        # Low disk space banner (only when a disk is below the user's warning level)
        self.disk_banner = QFrame()
        self.disk_banner.setObjectName("DiskBanner")
        self.disk_banner.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        dl = QHBoxLayout(self.disk_banner)
        dl.setContentsMargins(14, 5, 6, 5)
        self.disk_label = QLabel()
        self.disk_label.setObjectName("DiskBannerText")
        disk_more = QPushButton(tr("Details"))
        disk_more.setObjectName("DiskBannerButton")
        disk_more.clicked.connect(lambda: self.explorer.show_disk_card())
        disk_close = QToolButton()
        disk_close.setAutoRaise(True)
        disk_close.setToolTip(tr("Hide until the next connection"))
        icons.bind(disk_close, "close")
        disk_close.clicked.connect(self._dismiss_disk_banner)
        dl.addWidget(self.disk_label, 1)
        dl.addWidget(disk_more)
        dl.addWidget(disk_close)
        self.disk_banner.hide()
        self._disk_dismissed = False
        lay.addWidget(self.disk_banner)
        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(1000)
        self.idle_timer.timeout.connect(self._check_idle)
        self.idle_timer.start()
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.explorer = SftpExplorer(session.id, main.settings)
        self.explorer.follow_chk.setChecked(session.follow_cwd)
        self.explorer.cd_requested.connect(self._cd)
        self.explorer.navigated.connect(self._sync_terminal)
        self.explorer.disk_name = session.name
        self.explorer.disk_updated.connect(lambda _s: self.update_disk_banner())
        self.term_split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.explorer)
        self.split.addWidget(self.term_split)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([440, 820])
        # Dragging the divider stops at each side's minimum width instead of folding a pane away
        # (the explorer is hidden with View > Show/hide SFTP explorer, Ctrl+Shift+B).
        self.split.setCollapsible(0, False)
        self.split.setCollapsible(1, False)
        lay.addWidget(self.split)
        self._add_pane()

    # ------------------------------------------------------------ pane
    def _add_pane(self, orientation=None) -> TerminalPane:
        pane = TerminalPane(self.main.term_font, self.main.settings, self.session)
        pane.closed.connect(self._pane_closed)
        pane.focused.connect(self._pane_focused)
        pane.close_requested.connect(self.close_pane)
        pane.cwd_changed.connect(lambda path, p=pane: self._pane_cwd(p, path))
        pane.reconnect_requested.connect(self.connect)
        pane.font_zoom.connect(self.main.zoom_font)
        pane.title_changed.connect(lambda t: self.title_changed.emit(self, t))
        if orientation is not None and self.active is not None:
            parent = self.active.parentWidget()
            if isinstance(parent, QSplitter):
                if parent.count() == 1:
                    parent.setOrientation(orientation)
                    parent.addWidget(pane)
                elif parent.orientation() == orientation:
                    parent.insertWidget(parent.indexOf(self.active) + 1, pane)
                else:
                    # Different orientation: nest a new splitter in the current pane's place
                    idx = parent.indexOf(self.active)
                    sizes = parent.sizes()
                    sub = QSplitter(orientation)
                    parent.insertWidget(idx, sub)
                    sub.addWidget(self.active)
                    sub.addWidget(pane)
                    parent.setSizes(sizes)
                self._equalize(pane.parentWidget())
        else:
            self.term_split.addWidget(pane)
        self.panes.append(pane)
        self.active = pane
        self._update_close_buttons()
        return pane

    @staticmethod
    def _equalize(sp: QSplitter):
        n = sp.count()
        total = sum(sp.sizes()) or 1000
        sp.setSizes([total // n] * n)

    def split_pane(self, orientation):
        if self.state != "connected":
            return
        pane = self._add_pane(orientation)
        try:
            pane.start(self.conn)
        except Exception as e:
            pane.write_local("\x1b[31m" + tr("Cannot open shell: {error}", error=e) + "\x1b[0m\n")
        pane.setFocus()

    def _pane_focused(self, pane):
        self.active = pane
        # In split view, clicking another terminal moves the explorer to that terminal's location
        if pane.cwd:
            self.explorer.follow(pane.cwd)

    def _pane_cwd(self, pane, path: str):
        if pane is self.active:
            self.explorer.follow(path)

    SYNC_MSG = {
        "busy": "A command is running in the terminal, so the terminal location was left unchanged",
        "typing": "A command is being typed in the terminal, so the terminal location was left unchanged",
        "unsupported": "This shell does not support location sync (bash/zsh required) — use the 'Move the terminal to this folder' button",
    }

    def _sync_terminal(self, path: str):
        """When the user moves to another folder in the explorer, move the terminal there too."""
        if not self.explorer.follow_chk.isChecked() or not self.active:
            return
        msg = self.SYNC_MSG.get(self.active.sync_cd(path))
        if msg:
            self.explorer.info.setText(tr(msg))

    def _remove_pane(self, pane: TerminalPane):
        self.panes.remove(pane)
        parent = pane.parentWidget()
        pane.setParent(None)
        pane.deleteLater()
        # Clean up nested splitters left empty
        while isinstance(parent, QSplitter) and parent is not self.term_split and parent.count() == 0:
            gp = parent.parentWidget()
            parent.setParent(None)
            parent.deleteLater()
            parent = gp
        self.active = self.panes[-1]
        self.active.setFocus()
        self._update_close_buttons()

    def close_pane(self, pane: TerminalPane | None = None) -> bool:
        """Close one split pane. Returns False for the last pane (the caller decides whether to close the tab)."""
        pane = pane or self.active
        if pane is None or pane not in self.panes or len(self.panes) <= 1:
            return False
        pane.closed.disconnect(self._pane_closed)
        pane.close_channel()
        self._remove_pane(pane)
        return True

    def _update_close_buttons(self):
        multi = len(self.panes) > 1
        for p in self.panes:
            p.close_btn.setVisible(multi)

    def _pane_closed(self, pane: TerminalPane):
        if pane not in self.panes:
            return
        if len(self.panes) > 1:
            self._remove_pane(pane)
            return
        # Last shell closed -> treat as disconnected
        self.state = "closed"
        log.info("disconnected: %s%s", self._who(), " (idle)" if self._close_reason == "idle" else "")
        self._title()
        self.idle_banner.hide()
        if self._close_reason == "idle":
            mins = self.idle_limit() // 60
            pane.write_local("\n\x1b[33m[" + tr("Disconnected automatically after {mins} min of inactivity. "
                                                   "Press Enter or R to reconnect", mins=mins) + "]\x1b[0m\n")
        else:
            pane.write_local("\n\x1b[33m[" + tr("Connection closed. Press Enter or R to reconnect") + "]\x1b[0m\n")
        self._close_reason = ""
        self.explorer.detach()
        self.explorer.info.setText(tr("Disconnected"))
        self._stop_forwards()
        if self.conn:
            self.conn.close()

    # ------------------------------------------------------------ low disk space banner
    def update_disk_banner(self):
        s = self.explorer.disk_summary
        settings = self.main.settings
        worst = s.worst() if s is not None else None
        if (worst is None or self._disk_dismissed or not settings.get("disk_show", True)
                or not settings.get("disk_banner", True)):
            self.disk_banner.hide()
            return
        warn, crit = diskui.thresholds(settings)
        lv = diskusage.level(worst.free_pct, warn, crit)
        if lv == "ok":
            self.disk_banner.hide()
            return
        low = [d for d in s.measured if diskusage.level(d.free_pct, warn, crit) != "ok"]
        text = tr("Low disk space · {mount} has {pct} free ({free})", mount=worst.mount,
                  pct=diskui.pct_text(worst.free_pct), free=diskui.size_text(worst.avail))
        if len(low) > 1:
            text += "  " + tr("(+{n} more)", n=len(low) - 1)
        self.disk_label.setText(text)
        self.disk_banner.setProperty("level", lv)
        self.disk_banner.style().unpolish(self.disk_banner)
        self.disk_banner.style().polish(self.disk_banner)
        for w in self.disk_banner.findChildren(QWidget):
            w.style().unpolish(w)
            w.style().polish(w)
        self.disk_banner.show()

    def _dismiss_disk_banner(self):
        self._disk_dismissed = True
        self.disk_banner.hide()

    def _cd(self, path: str):
        if self.active and not self.active.disconnected:
            self.active.send_text(f" cd -- {sh_quote(path)}\r")
            self.active.setFocus()

    # ------------------------------------------------------------ connection
    def _title(self):
        prefix = {"connecting": "⏳ ", "closed": "✕ ", "failed": "✕ "}.get(self.state, "")
        self.title_changed.emit(self, prefix + self.session.title())

    def connect(self):
        if self.state == "connecting":
            return
        s = self.session
        if s.auth == "password" and not self.password:
            pw, ok = QInputDialog.getText(self, tr("Password"), tr("Password for {target}:", target=f"{s.user}@{s.host}"),
                                          QLineEdit.EchoMode.Password)
            if not ok:
                self.state = "failed"
                self._title()
                return
            self.password = pw
        if not s.user:
            user, ok = QInputDialog.getText(self, tr("User"), tr("Login user for {host}:", host=s.host))
            if not ok or not user.strip():
                return
            s.user = user.strip()
        jumps = jump_credentials(self, self.main.store, s, self._jump_cache)
        if jumps is None:
            self.state = "failed"
            self._title()
            return
        self.state = "connecting"
        self._title()
        pane = self.panes[0]
        via = " → ".join(j.title() for j, _pw, _pp in jumps)
        pane.write_local("\x1b[90m" + tr("Connecting to {target}…", target=f"{s.user}@{s.host}:{s.port}")
                         + (" (" + tr("via {hosts}", hosts=via) + ")" if via else "") + "\x1b[0m\n")
        self.conn = SshConnection(s, self.password, self.passphrase, jumps)
        self.worker = ConnectWorker(self.conn)
        self.worker.ok.connect(self._on_ok)
        self.worker.failed.connect(self._on_failed)
        self.worker.auth_failed.connect(self._on_auth_failed)
        self.worker.unknown_host.connect(self._on_unknown_host)
        self.worker.start()

    # ------------------------------------------------------------ idle auto-disconnect
    def idle_limit(self) -> int:
        """Seconds until auto-disconnect (0 = off). The session setting wins, otherwise the global setting."""
        m = self.session.idle_minutes
        if m is None or m < 0:
            m = int(self.main.settings.get("idle_minutes", 30) or 0)
        return max(0, int(m)) * 60

    def touch(self):
        """Mark as in use — called on keyboard/mouse activity or file transfer."""
        self.last_activity = time.monotonic()
        if self.idle_banner.isVisible():
            self.idle_banner.hide()

    def _check_idle(self):
        limit = self.idle_limit()
        if self.state != "connected" or not limit:
            self.idle_banner.hide()
            return
        if self.explorer.transfer_active():
            self.touch()          # Never disconnect during a file transfer
            return
        idle = time.monotonic() - self.last_activity
        left = limit - idle
        warn = min(60, limit // 2)
        if left <= 0:
            self.idle_disconnect()
        elif left <= warn:
            self.idle_label.setText(tr("Idle — disconnecting in {seconds} s", seconds=int(left) + 1))
            self.idle_banner.show()
        else:
            self.idle_banner.hide()

    def idle_disconnect(self):
        self._close_reason = "idle"
        self.idle_banner.hide()
        for p in list(self.panes[1:]):
            self.close_pane(p)
        if self.conn:
            self.conn.close()     # When the shell channel closes, _pane_closed cleans up and shows a notice

    def _on_ok(self):
        self.state = "connected"
        log.info("connected: %s", self._who())
        self.touch()
        self._title()
        # Clean up leftover panes, then start the shell in the first pane
        pane = self.panes[0]
        pane.write_local("\x1b[2J\x1b[H")
        try:
            pane.start(self.conn)
        except Exception as e:
            self._on_failed(tr("Failed to open shell: {error}", error=e))
            return
        pane.setFocus()
        self._disk_dismissed = False
        self.explorer.attach(self.conn, self.session.init_dir)
        self._start_forwards()
        try:
            library.add_history(self.session)
        except OSError:
            pass

    # ------------------------------------------------------------ port forwarding
    def _start_forwards(self):
        self._stop_forwards()
        if not self.session.forwards or not self.conn or not self.conn.transport:
            return
        self.forward_runners = forwarding.start_all(self.session.forwards, self.conn.transport)
        pane = self.panes[0]
        for r in self.forward_runners:
            rule = r.fwd.describe()
            if r.fwd.kind == "R" and r.fwd.bind_port == 0:
                rule += f" (:{r.bound_port})"
            if r.running:
                pane.write_local("\x1b[90m" + tr("Port forwarding {rule}", rule=rule) + " ✓\x1b[0m\r\n")
            else:
                pane.write_local("\x1b[33m" + tr("Port forwarding {rule} failed: {error}", rule=rule,
                                                  error=error_text(r.error)) + "\x1b[0m\r\n")

    def _stop_forwards(self):
        for r in self.forward_runners:
            r.stop()
        self.forward_runners = []

    def _who(self) -> str:
        s = self.session
        return f"{s.title()} ({s.user + '@' if s.user else ''}{s.host}:{s.port or 22})"

    def _on_failed(self, msg: str):
        log.info("connection failed: %s: %s", self._who(), msg)
        self._jump_cache.clear()     # a typed jump-host password may have been wrong
        self.state = "failed"
        self._title()
        pane = self.panes[0]
        pane.disconnected = True
        pane.write_local(f"\x1b[31m{msg}\x1b[0m\n\x1b[33m[{tr('Enter or R: reconnect')}]\x1b[0m\n")

    def _on_auth_failed(self, msg: str):
        self.password = ""
        self.state = "failed"
        self.panes[0].write_local(f"\x1b[31m{msg}\x1b[0m\n")
        if self.session.auth == "password":
            QTimer.singleShot(0, self.connect)
        else:
            self._on_failed(tr("Key authentication failed. Check the key file/passphrase."))

    def _on_unknown_host(self, hostname: str, key):
        trusted = ask_trust_host(self, hostname, key)
        self.state = "failed"
        if trusted:
            self.connect()
        else:
            self._on_failed(tr("Connection cancelled."))

    def shutdown(self):
        self._stop_forwards()
        self.explorer.detach()
        for p in self.panes:
            p.close_channel()
        if self.conn:
            self.conn.close()


GROUP_ROLE = Qt.ItemDataRole.UserRole + 1   # group name for group items
DEFAULT_THEME = "light"
THEME_CHOICES = (("light", "Light (default)"), ("dark", "Dark"), ("system", "Follow Windows setting"))


class SessionTree(QTreeWidget):
    """Session list. Drag sessions into/out of groups (the actual move is redrawn from the store)."""
    sessions_dropped = Signal(list, str)   # session ids, target group ("" = no group)

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)

    press_on_arrow = False

    def mousePressEvent(self, e):
        # Record whether the press hit the arrow (indent area) so it doesn't clash with the group-name click toggle
        it = self.itemAt(e.position().toPoint())
        self.press_on_arrow = bool(it) and e.position().x() < self.visualItemRect(it).x()
        super().mousePressEvent(e)

    def selected_session_ids(self) -> list[str]:
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self.selectedItems()
                if it.data(0, Qt.ItemDataRole.UserRole)]

    def target_group(self, item, indicator) -> str:
        """Drop position -> target group name."""
        if item is None:
            return ""                                    # empty area -> no group
        g = item.data(0, GROUP_ROLE)
        if g is not None:
            Pos = QTreeWidget.DropIndicatorPosition
            return g if indicator == Pos.OnItem else ""   # on a group = into it, between groups = out
        parent = item.parent()                           # next to a session -> that session's group
        return parent.data(0, GROUP_ROLE) if parent is not None else ""

    def dragEnterEvent(self, e):
        if e.source() is self:
            super().dragEnterEvent(e)
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.source() is not self:
            e.ignore()
            return
        group = self.target_group(self.itemAt(e.position().toPoint()), self.dropIndicatorPosition())
        ids = self.selected_session_ids()
        # Don't let the tree move items itself; update the store, then redraw
        e.setDropAction(Qt.DropAction.IgnoreAction)
        e.accept()
        if ids:
            self.sessions_dropped.emit(ids, group)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"JeopsokHeyou {__version__}")
        self.resize(1400, 850)
        self.settings = config.load_settings()
        self.store = SessionStore()
        self.term_font = pick_font(self.settings.get("font_family", ""), int(self.settings.get("font_size", 11)))

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)   # Remove the default base line under tabs (white line in dark mode)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tabs)

        self._build_sessions_dock()
        self._build_toolbar()
        self._build_menu()
        self.reload_sessions()
        self.tunnels = TunnelManager(self.store, self)
        self.snippets = library.SnippetStore()
        # Home tab (menu: Start page, Hosts, Keychain, Port Forwarding, …) — always the first tab
        self.home = HomeTab(self)
        self.tabs.insertTab(0, self.home, icons.line("home"), tr("Home"))
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        self.tabs.setCurrentIndex(0)
        self.last_session_tab: SessionTab | None = None
        self.tabs.currentChanged.connect(self._on_tab_changed)
        # Session list on the left: shown with terminal tabs (Home has its own menu)
        self._apply_sessions_panel()
        # Optional master password: ask to unlock whenever a saved secret is needed, lock when idle
        vaultui.install_unlock_hook(self.store, self)
        self._last_input = time.monotonic()
        self._started = False
        self.vault_timer = QTimer(self)
        self.vault_timer.setInterval(15000)
        self.vault_timer.timeout.connect(self._auto_lock)
        self.vault_timer.start()
        QApplication.instance().installEventFilter(self)   # Detect keyboard/mouse activity (idle auto-disconnect)
        QTimer.singleShot(3000, cleanup_temp)   # Clean up old temp copies (slightly delayed to keep startup light)

    # ------------------------------------------------------------ UI setup
    def _build_sessions_dock(self):
        dock = QDockWidget(tr("Sessions"), self)
        dock.setObjectName("sessions")
        dock.setTitleBarWidget(QWidget())   # No title bar, like the Finder sidebar
        w = QWidget()
        w.setObjectName("Sidebar")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(6)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Search sessions"))
        self.filter.addAction(icons.line("server"), QLineEdit.ActionPosition.LeadingPosition)
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.reload_sessions)
        self.filter.returnPressed.connect(self._connect_first_visible)
        self.session_tree = SessionTree()
        self.session_tree.itemDoubleClicked.connect(self._on_session_double)
        self.session_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_tree.customContextMenuRequested.connect(self._session_menu)
        self.session_tree.sessions_dropped.connect(self._move_sessions)
        self.session_tree.setIndentation(16)
        self.session_tree.setExpandsOnDoubleClick(False)
        self.session_tree.itemClicked.connect(self._toggle_group)   # Clicking a group name collapses/expands it, like Finder
        self.session_tree.itemCollapsed.connect(lambda it: self._collapsed.add(it.data(0, GROUP_ROLE) or ""))
        self.session_tree.itemExpanded.connect(lambda it: self._collapsed.discard(it.data(0, GROUP_ROLE) or ""))
        self._collapsed: set[str] = set()
        add = QPushButton(tr("New session"))
        add.setObjectName("Flat")
        icons.bind(add, "plus")
        add.clicked.connect(self.new_session)
        add_group = QPushButton(tr("Group"))
        add_group.setObjectName("Flat")
        icons.bind(add_group, "plus")
        add_group.clicked.connect(self.add_group)
        btns = QHBoxLayout()
        btns.addWidget(add, 1)
        btns.addWidget(add_group)
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.filter, 1)
        self.sessions_collapse_btn = QToolButton()
        icons.bind(self.sessions_collapse_btn, "sidebar")
        self.sessions_collapse_btn.setToolTip(tr("Hide session list (Ctrl+Shift+S)"))
        self.sessions_collapse_btn.clicked.connect(self.toggle_sessions_panel)
        top.addWidget(self.sessions_collapse_btn)
        lay.addLayout(top)
        lay.addWidget(self.session_tree, 1)
        lay.addLayout(btns)
        w.setMinimumWidth(200)
        # Collapsed: a slim strip with a button to bring the list back
        strip = QWidget()
        strip.setObjectName("Sidebar")
        sl = QVBoxLayout(strip)
        sl.setContentsMargins(4, 10, 4, 8)
        self.sessions_expand_btn = QToolButton()
        icons.bind(self.sessions_expand_btn, "sidebar")
        self.sessions_expand_btn.setToolTip(tr("Show session list (Ctrl+Shift+S)"))
        self.sessions_expand_btn.clicked.connect(self.toggle_sessions_panel)
        sl.addWidget(self.sessions_expand_btn)
        sl.addStretch(1)
        self.sessions_full, self.sessions_strip = w, strip
        from PySide6.QtWidgets import QStackedWidget
        self.sessions_stack = QStackedWidget()
        self.sessions_stack.addWidget(w)
        self.sessions_stack.addWidget(strip)
        dock.setWidget(self.sessions_stack)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.resizeDocks([dock], [240], Qt.Orientation.Horizontal)
        self.sessions_dock = dock

    def _build_toolbar(self):
        tb = QToolBar(tr("Tools"))
        tb.setObjectName("quick")
        self.main_toolbar = tb
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))

        def tool(name, tip, slot):
            b = QToolButton()
            icons.bind(b, name)
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            tb.addWidget(b)
            return b
        self.home_btn = tool("home", tr("Home (Ctrl+Shift+H)"), lambda: self.show_home())
        tool("plus", tr("New session (Ctrl+Shift+N)"), self.new_session)
        tb.addSeparator()
        tool("split_h", tr("Split left/right (Ctrl+Shift+D)"), lambda: self.split(Qt.Orientation.Horizontal))
        tool("split_v", tr("Split top/bottom (Ctrl+Shift+E)"), lambda: self.split(Qt.Orientation.Vertical))
        tool("folder_plus", tr("Show/hide SFTP explorer (Ctrl+Shift+B)"), self.toggle_explorer)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.quick = QLineEdit()
        self.quick.setPlaceholderText(tr("Quick connect — user@host:port"))
        self.quick.setFixedWidth(300)
        self.quick.addAction(icons.line("bolt"), QLineEdit.ActionPosition.LeadingPosition)
        self.quick.returnPressed.connect(self.quick_connect)
        tb.addWidget(self.quick)
        self.addToolBar(tb)

    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        self._act(m, tr("New session…"), self.new_session, "Ctrl+Shift+N")
        self._act(m, tr("Quick connect"), lambda: self.quick.setFocus(), "Ctrl+Shift+Q")
        self._act(m, tr("Import PuTTY sessions"), self.import_putty)
        self._act(m, tr("Import Tabby sessions"), self.import_tabby)
        self._act(m, tr("Import MobaXterm sessions…"), self.import_mobaxterm)
        self._act(m, tr("Import OpenSSH config…"), self.import_ssh_config)
        self._act(m, tr("Import iTerm2 profiles…"), self.import_iterm)
        self._act(m, tr("Import SecureCRT sessions…"), self.import_securecrt)
        m.addSeparator()
        self._act(m, tr("Lock saved passwords"), self.lock_vault, "Ctrl+Shift+L")
        self._act(m, tr("Exit"), self.close)

        m = mb.addMenu(tr("&Terminal"))
        self._act(m, tr("Split horizontally (left/right)"), lambda: self.split(Qt.Orientation.Horizontal), "Ctrl+Shift+D")
        self._act(m, tr("Split vertically (top/bottom)"), lambda: self.split(Qt.Orientation.Vertical), "Ctrl+Shift+E")
        self._act(m, tr("Duplicate tab (new connection to the same server)"), self.duplicate_tab, "Ctrl+Shift+T")
        self._act(m, tr("Close pane (split pane → tab)"), self.close_pane_or_tab, "Ctrl+Shift+W")
        self._act(m, tr("Next tab"), lambda: self._cycle(1), "Ctrl+Tab")
        self._act(m, tr("Previous tab"), lambda: self._cycle(-1), "Ctrl+Shift+Tab")
        self._act(m, tr("Snippets…"), self.pick_snippet, "Ctrl+Shift+P")
        # Find: ⌘F on macOS (like iTerm2); Ctrl+Shift+G elsewhere (Ctrl+F belongs to the shell, Ctrl+Shift+F is port forwarding)
        self._act(m, tr("Find…"), self.find_in_terminal, "Ctrl+F" if paths.IS_MAC else "Ctrl+Shift+G")
        self._act(m, tr("Start/stop logging this pane"), self.toggle_log)
        self._act(m, tr("Open log folder"), self.open_log_folder)
        m.addSeparator()
        self._act(m, tr("Copy  (Ctrl+Shift+C / drag)"), lambda: None)
        self._act(m, tr("Paste  (Ctrl+Shift+V / right-click)"), lambda: None)

        m = mb.addMenu(tr("&View"))
        self._act(m, tr("Home"), lambda: self.show_home(), "Ctrl+Shift+H")
        self._act(m, tr("Show/hide SFTP explorer"), self.toggle_explorer, "Ctrl+Shift+B")
        self.sessions_act = QAction(tr("Session list panel"), self)
        self.sessions_act.setCheckable(True)
        self.sessions_act.setChecked(bool(self.settings.get("show_sessions", True)))
        self.sessions_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.sessions_act.triggered.connect(lambda _c=False: self.toggle_sessions_panel())
        m.addAction(self.sessions_act)
        m.addSeparator()
        self._act(m, tr("Font…"), self.choose_font)
        self._act(m, tr("Larger text"), lambda: self.zoom_font(1), "Ctrl+Shift+=")
        self._act(m, tr("Smaller text"), lambda: self.zoom_font(-1), "Ctrl+Shift+-")
        m.addSeparator()
        self._theme_actions = {}
        tm = m.addMenu(tr("Appearance"))
        grp = QActionGroup(self)
        for mode, label in THEME_CHOICES:
            a = tm.addAction(tr(label))
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, mode=mode: self.apply_appearance(mode=mode))
            grp.addAction(a)
            self._theme_actions[mode] = a
        self._font_actions = {}
        fm = m.addMenu(tr("UI font"))
        grp2 = QActionGroup(self)
        for key, (label, _fam, _px) in theme.UI_FONTS.items():
            a = fm.addAction(tr(label))
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, key=key: self.apply_appearance(ui_font=key))
            grp2.addAction(a)
            self._font_actions[key] = a
        m.addSeparator()
        self._act(m, tr("Settings…"), self.open_settings, "Ctrl+,")
        self._act(m, tr("Master password…"), self.open_vault_settings)
        self._sync_appearance_menu()

        m = mb.addMenu(tr("T&ools"))
        self._act(m, tr("Port forwarding…"), self.show_tunnels, "Ctrl+Shift+F")
        self._act(m, tr("Keychain"), lambda: self.show_home("keychain"))
        self._act(m, tr("Known Hosts"), lambda: self.show_home("known_hosts"))
        self._act(m, tr("History"), lambda: self.show_home("history"))

        m = mb.addMenu(tr("&Help"))
        self._act(m, tr("Getting started guide"), lambda: self.start_tour(from_help=True))
        self._act(m, tr("Open app log folder"), self.open_app_log_folder)
        self._act(m, tr("About JeopsokHeyou"), self.show_about)

    def show_about(self):
        from . import __version__
        notices = (paths.DOCS_DIR / "THIRD-PARTY-NOTICES.md").as_uri()
        license_ = (paths.DOCS_DIR / "LICENSE").as_uri()
        QMessageBox.about(self, tr("About JeopsokHeyou"), (
            f"<h3>JeopsokHeyou {__version__}</h3>"
            f"<p>{tr('A tabbed SSH terminal and SFTP explorer for Windows and macOS.')}</p>"
            "<p>© 2026 Seunghun Jun<br/>"
            f"{tr('Free software under the GNU General Public License v3.0 or later.')}</p>"
            f"<p><a href='{license_}'>{tr('License')}</a> · "
            f"<a href='{notices}'>{tr('Third-party notices')}</a></p>"
            f"<p><small>{tr('Provided as is, without warranty of any kind.')}</small></p>"))

    def _sync_appearance_menu(self):
        mode = self.settings.get("theme", DEFAULT_THEME)
        font = self.settings.get("ui_font", "default")
        for k, a in self._theme_actions.items():
            a.setChecked(k == mode)
        for k, a in self._font_actions.items():
            a.setChecked(k == font)

    def apply_appearance(self, mode: str | None = None, ui_font: str | None = None):
        """Change the appearance (light/dark/Windows setting) and UI font; apply and save immediately."""
        if mode:
            self.settings["theme"] = mode
        if ui_font:
            self.settings["ui_font"] = ui_font
        config.save_settings(self.settings)
        theme.manager.apply(QApplication.instance(), self.settings.get("theme", DEFAULT_THEME),
                            self.settings.get("ui_font", "default"))
        self._sync_appearance_menu()
        self.reload_sessions()   # Repaint section/icon colors
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, SessionTab):
                w.explorer.refresh()

    # Backward-compatible old name
    def set_theme(self, mode: str):
        self.apply_appearance(mode=mode)

    def open_settings(self):
        from .dialogs import SettingsDialog
        d = SettingsDialog(self.settings, self.term_font, self)
        if d.exec():
            v = d.values()
            self.settings["idle_minutes"] = v["idle_minutes"]
            self.settings["terminal_reflow"] = v["terminal_reflow"]
            self.settings["terminal_scheme"] = v["terminal_scheme"]
            for key in ("log_sessions", "log_timestamps", "log_dir", "highlight_enabled", "highlight_rules",
                        "disk_show", "disk_banner", "disk_card", "disk_warn_pct", "disk_crit_pct",
                        "download_confirm_gb", "download_confirm_files", "card_last_connected"):
                self.settings[key] = v[key]
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if isinstance(tab, SessionTab):
                    if v["disk_show"] and tab.explorer.disk_summary is None:
                        tab.explorer.refresh_disk()
                    tab.explorer.apply_disk_settings()
                    tab.update_disk_banner()
            self.home.refresh_current()
            scheme = (self.settings.get("color_schemes") or {}).get(v["terminal_scheme"])
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                for p in getattr(tab, "panes", []):
                    p.screen.reflow = v["terminal_reflow"]
                    p.apply_scheme(scheme)
                    p.apply_highlights(self.settings)
            if v["language"] != self.settings.get("language", "system"):
                self.settings["language"] = v["language"]
                config.save_settings(self.settings)
                QMessageBox.information(self, tr("Language"),
                                        tr("The new language will be used the next time JeopsokHeyou starts."))
            self.term_font = pick_font(v["term_family"], v["term_size"])
            self._apply_font()
            self.apply_appearance(mode=v["theme"], ui_font=v["ui_font"])

    _ACTIVITY_EVENTS = None

    def eventFilter(self, obj, e):
        if MainWindow._ACTIVITY_EVENTS is None:
            T = QEvent.Type
            MainWindow._ACTIVITY_EVENTS = {T.KeyPress, T.MouseButtonPress, T.Wheel, T.InputMethod}
        if e.type() in MainWindow._ACTIVITY_EVENTS and isinstance(obj, QWidget):
            self._last_input = time.monotonic()
            t = self.tabs.currentWidget()
            if isinstance(t, SessionTab) and (obj is t or t.isAncestorOf(obj)):
                t.touch()
        return False

    def showEvent(self, e):
        super().showEvent(e)
        theme.style_window(self, theme.current())
        if not self._started:
            self._started = True
            QTimer.singleShot(0, self._startup)

    def _startup(self):
        """After the window first appears: unlock (when a master password is set), then autostart tunnels."""
        if vault.enabled() and not vault.unlocked():
            vaultui.ask_unlock(self.store, self)
        self.tunnels.autostart()

    def _auto_lock(self):
        mins = int(self.settings.get("vault_lock_minutes", vaultui.DEFAULT_LOCK_MINUTES) or 0)
        if mins and vault.unlocked() and time.monotonic() - self._last_input > mins * 60:
            vault.lock()

    def lock_vault(self):
        if not vault.enabled():
            QMessageBox.information(self, tr("Master password"),
                                    tr("No master password is set. Turn it on in Settings → Master password."))
            return
        vault.lock()

    def open_vault_settings(self):
        vaultui.VaultDialog(self.store, self.settings, self).exec()

    def _act(self, menu: QMenu, text, slot, shortcut=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        menu.addAction(a)
        return a

    # ------------------------------------------------------------ session list
    def reload_sessions(self):
        q = self.filter.text().strip().lower() if hasattr(self, "filter") else ""
        tree = self.session_tree
        tree.clear()
        t = theme.current()
        comp = icons.line_selectable("server", t.accent, t.accent_text)
        section_font = QFont(self.font())
        section_font.setPixelSize(11)
        section_font.setBold(True)
        Flag = Qt.ItemFlag
        groups: dict[str, QTreeWidgetItem] = {}
        # Subgroups ("A / B") are shown nested under their parent; missing parent levels are filled in
        paths = set()
        for name in self.store.groups():
            parts = name.split(config.GROUP_SEP)
            for i in range(1, len(parts) + 1):
                paths.add(config.GROUP_SEP.join(parts[:i]))
        for name in sorted(paths, key=lambda x: (x.count(config.GROUP_SEP), x.lower())):
            g = QTreeWidgetItem([config.group_leaf(name)])
            g.setFont(0, section_font)
            g.setForeground(0, QColor(t.faint))
            g.setData(0, GROUP_ROLE, name)
            # Groups: sessions can be dropped in, but the group itself can't be dragged
            g.setFlags(Flag.ItemIsEnabled | Flag.ItemIsSelectable | Flag.ItemIsDropEnabled)
            parent = groups.get(config.group_parent(name))
            if parent is not None:
                parent.addChild(g)
            else:
                tree.addTopLevelItem(g)
            groups[name] = g
        for s in sorted(self.store.sessions, key=lambda x: x.title().lower()):
            hay = f"{s.title()} {s.host} {s.user} {s.group}".lower()
            if q and q not in hay:
                continue
            it = QTreeWidgetItem([s.title()])
            it.setIcon(0, comp)
            it.setToolTip(0, f"{s.user}@{s.host}:{s.port}")
            it.setData(0, Qt.ItemDataRole.UserRole, s.id)
            it.setFlags(Flag.ItemIsEnabled | Flag.ItemIsSelectable | Flag.ItemIsDragEnabled)
            if s.group in groups:
                # A group's own sessions come right under it, before its subgroups
                g = groups[s.group]
                pos = sum(1 for i in range(g.childCount()) if g.child(i).data(0, GROUP_ROLE) is None)
                g.insertChild(pos, it)
            else:
                tree.addTopLevelItem(it)
        def sessions_under(name: str) -> int:
            return sum(1 for s in self.store.sessions if config.in_group(s.group, name)
                       and (not q or q in f"{s.title()} {s.host} {s.user} {s.group}".lower()))
        for name, g in groups.items():
            n = sessions_under(name)
            if q and n == 0 and q not in name.lower():
                g.setHidden(True)  # Hide groups with no results while searching
            g.setExpanded(bool(q) or name not in self._collapsed)
            g.setToolTip(0, tr("{name} — {count} sessions", name=name, count=n))
        if hasattr(self, "home"):
            self.home.hosts.refresh()
            self.home.start.refresh()

    def _toggle_group(self, item, _col=0):
        if item.data(0, GROUP_ROLE) is None or not item.childCount():
            return
        if self.session_tree.press_on_arrow:
            return   # A click on the arrow itself is already handled by the tree
        item.setExpanded(not item.isExpanded())

    def _connect_first_visible(self):
        tree = self.session_tree

        def first_session(items):   # depth first, through subgroups
            for it in items:
                if it.isHidden():
                    continue
                if it.data(0, GROUP_ROLE) is None:
                    return it
                found = first_session([it.child(i) for i in range(it.childCount())])
                if found is not None:
                    return found
            return None
        it = first_session([tree.topLevelItem(i) for i in range(tree.topLevelItemCount())])
        if it is not None:
            self._on_session_double(it)

    def _on_session_double(self, item, _col=0):
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        s = self.store.get(sid) if sid else None
        if s:
            self.open_session(s)

    def _session_menu(self, pos):
        item = self.session_tree.itemAt(pos)
        m = QMenu(self)
        sid = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        group = item.data(0, GROUP_ROLE) if item else None
        s = self.store.get(sid) if sid else None
        if s:
            ids = self.session_tree.selected_session_ids() or [s.id]
            m.addAction(tr("Connect"), lambda: self.open_session(s))
            m.addAction(tr("Edit…"), lambda: self.edit_session(s))
            m.addAction(tr("Duplicate"), lambda: self._clone_session(s))
            mv = m.addMenu(tr("Move to group"))
            for g in self.store.groups():
                a = mv.addAction(g, lambda g=g: self._move_sessions(ids, g))
                a.setEnabled(g != s.group or len(ids) > 1)
            mv.addSeparator()
            mv.addAction(tr("(No group)"), lambda: self._move_sessions(ids, "")).setEnabled(bool(s.group) or len(ids) > 1)
            mv.addAction(tr("Move to new group…"), lambda: self.add_group(move_ids=ids))
            m.addAction(tr("Delete"), lambda: self._delete_session(s))
            m.addSeparator()
        elif group is not None:
            m.addAction(tr("New session in this group…"), lambda: self.new_session(group))
            m.addAction(tr("Rename group…"), lambda: self.rename_group(group))
            m.addAction(tr("Delete group"), lambda: self.remove_group(group))
            m.addSeparator()
        m.addAction(tr("New session…"), self.new_session)
        m.addAction(tr("Add group…"), self.add_group)
        m.addSeparator()
        m.addAction(tr("Import PuTTY sessions"), self.import_putty)
        m.addAction(tr("Import Tabby sessions"), self.import_tabby)
        m.addAction(tr("Import MobaXterm sessions…"), self.import_mobaxterm)
        m.addAction(tr("Import OpenSSH config…"), self.import_ssh_config)
        m.addAction(tr("Import iTerm2 profiles…"), self.import_iterm)
        m.addAction(tr("Import SecureCRT sessions…"), self.import_securecrt)
        m.exec(self.session_tree.viewport().mapToGlobal(pos))

    def _groups(self):
        return self.store.groups()

    # ------------------------------------------------------------ groups
    def add_group(self, move_ids: list[str] | None = None, parent: str = ""):
        label = tr("Name of the new group inside '{parent}':", parent=parent) if parent else tr("Group name:")
        name, ok = QInputDialog.getText(self, tr("Add group"), label)
        name = name.strip().replace(config.GROUP_SEP.strip(), "-") if ok else ""
        if not ok or not name:
            return
        if parent:
            name = parent + config.GROUP_SEP + name
        if name in self.store.groups() and not move_ids:
            QMessageBox.information(self, tr("Add group"), tr("Group '{name}' already exists.", name=name))
            return
        self.store.add_group(name)
        if move_ids:
            self.store.move_sessions(move_ids, name)
        self._collapsed.discard(name)
        self.reload_sessions()

    def rename_group(self, old: str):
        new, ok = QInputDialog.getText(self, tr("Rename group"), tr("New name:"), text=config.group_leaf(old))
        new = new.strip().replace(config.GROUP_SEP.strip(), "-") if ok else ""
        if not ok or not new:
            return
        if config.group_parent(old):
            new = config.group_parent(old) + config.GROUP_SEP + new
        if new == old:
            return
        if not self.store.rename_group(old, new):
            QMessageBox.information(self, tr("Rename group"), tr("Group '{name}' already exists.", name=new))
            return
        if old in self._collapsed:
            self._collapsed.discard(old)
            self._collapsed.add(new)
        self.reload_sessions()

    def remove_group(self, name: str):
        n = sum(1 for s in self.store.sessions if config.in_group(s.group, name))
        msg = tr("Delete group '{name}'?", name=name)
        if n:
            msg += "\n\n" + tr("The {n} sessions in it won't be deleted; they will be moved out of the group.", n=n)
        if QMessageBox.question(self, tr("Delete group"), msg) != QMessageBox.StandardButton.Yes:
            return
        self.store.remove_group(name)
        self._collapsed.discard(name)
        self.reload_sessions()

    def _move_sessions(self, ids: list[str], group: str):
        if ids and self.store.move_sessions(ids, group):
            self.reload_sessions()

    def move_items(self, host_ids: list[str], groups: list[str], target: str) -> bool:
        """Hosts and groups dropped onto ``target`` ("" = top level) in the Hosts screen."""
        groups = [g for g in groups if not any(o != g and config.in_group(g, o) for o in groups)]
        moved, failed = False, []
        page = self.home.hosts
        for g in groups:
            if config.group_parent(g) == target:
                continue
            new = self.store.move_group(g, target)
            if new is None:
                failed.append(g)
                continue
            moved = True
            if page.group and config.in_group(page.group, g):     # keep the open group open after the move
                page.group = new + page.group[len(g):]
        if host_ids and self.store.move_sessions(host_ids, target):
            moved = True
        if moved:
            self.reload_sessions()
        if failed:
            QMessageBox.information(self, tr("Move group"),
                                    tr("Couldn't move {names}: a group with the same name is already there.",
                                       names=", ".join(config.group_leaf(g) for g in failed)))
        return moved

    def new_session(self, group: str = ""):
        d = SessionDialog(None, self._groups(), self, sessions=self.store.sessions)
        if isinstance(group, str) and group:
            d.group.setCurrentText(group)
        if d.exec():
            self.store.upsert(d.session)
            self.reload_sessions()
            self.open_session(d.session, d.transient_password, d.transient_passphrase)

    def edit_session(self, s: Session):
        d = SessionDialog(Session.from_dict(dict(s.__dict__)), self._groups(), self, sessions=self.store.sessions)
        if d.exec():
            self.store.upsert(d.session)
            self.reload_sessions()

    def _clone_session(self, s: Session):
        c = Session.from_dict({k: v for k, v in s.__dict__.items() if k != "id"})
        c.name = (s.name or s.title()) + " " + tr("(copy)")
        # Secrets are tied to the session id (macOS Keychain), so store them again for the copy
        c.password = s.password if s.password_enc else ""
        c.passphrase = s.passphrase if s.passphrase_enc else ""
        self.store.upsert(c)
        self.reload_sessions()

    def _delete_session(self, s: Session):
        if QMessageBox.question(self, tr("Delete session"), tr("Delete session '{name}'?", name=s.title())) == QMessageBox.StandardButton.Yes:
            self.store.remove(s.id)
            self.reload_sessions()

    def _import_sessions(self, label: str, found: list[Session], note: str):
        existing = {(s.host, s.port, s.user): s.id for s in self.store.sessions}
        new = [s for s in found if (s.host, s.port, s.user) not in existing]
        # Jump hosts that were already present: point to the existing session instead
        remap = {s.id: existing[(s.host, s.port, s.user)] for s in found if (s.host, s.port, s.user) in existing}
        for s in new:
            s.jump = remap.get(s.jump, s.jump)
        for s in new:
            self.store.sessions.append(s)
        self.store.save()
        self.reload_sessions()
        dup = len(found) - len(new)
        QMessageBox.information(self, tr("Import {source}", source=label),
                                tr("Imported {new} of {total} {source} sessions.",
                                   new=len(new), total=len(found), source=label)
                                + ("\n" + tr("({dup} already present were skipped)", dup=dup) if dup else "")
                                + f"\n\n{note}")

    def import_putty(self):
        self._import_sessions("PuTTY", config.import_putty_sessions(),
                              tr("PuTTY does not store passwords, so enter the password when you first connect."))

    def import_securecrt(self):
        from PySide6.QtWidgets import QFileDialog
        from . import securecrt
        found = securecrt.default_dirs()
        start = str(found[0]) if found else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, tr("Select the SecureCRT Sessions folder"), start)
        if not folder:
            return
        sessions, skipped = securecrt.import_securecrt_sessions(Path(folder))
        note = tr("Sub-folders became groups. Saved passwords are not imported; enter them when you first connect.")
        if skipped:
            note += "\n" + tr("{n} sessions that are not SSH (Telnet, Serial, RDP, …) were skipped.", n=skipped)
        self._import_sessions("SecureCRT", sessions, note)

    def import_iterm(self):
        from PySide6.QtWidgets import QFileDialog
        from . import itermimport
        found = itermimport.default_files()
        start = str(found[0]) if found else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Select iTerm2 profiles"), start,
            tr("iTerm2 profiles (*.plist *.json)") + ";;" + tr("All files (*)"))
        if not path:
            return
        sessions, skipped = itermimport.import_iterm_sessions(Path(path))
        note = tr("Profiles that run ssh became sessions; their first tag became the group. "
                  "Passwords are not stored in iTerm2 profiles; enter them when you first connect.")
        if skipped:
            note += "\n" + tr("{n} profiles without an ssh command (local shells) were skipped.", n=skipped)
        self._import_sessions("iTerm2", sessions, note)

    def import_mobaxterm(self):
        from PySide6.QtWidgets import QFileDialog
        found = config.mobaxterm_default_files()
        start = str(found[0]) if found else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Select a MobaXterm session file"), start,
            tr("MobaXterm sessions (MobaXterm.ini *.mxtsessions)") + ";;" + tr("All files (*)"))
        if not path:
            return
        note = tr("Passwords are kept in MobaXterm's own store and are not imported; enter them when you first connect.")
        # The same file also holds the MobaSSHTunnel list
        added, dup, _new = import_mobaxterm_tunnels(Path(path), self.store, self.tunnels.tunnels)
        if added or dup:
            self.tunnels.changed.emit()
            note += "\n\n" + tr("Port forwarding: imported {n} MobaSSHTunnel tunnels (Tools → Port forwarding).", n=added) \
                + (" " + tr("({dup} already present were skipped)", dup=dup) if dup else "") \
                + "\n" + tr("Autostart and auto-reconnect are not stored in MobaXterm.ini — set them in each tunnel.") \
                + "\n" + tr("Tunnels that listened on all network interfaces now listen on this PC only (127.0.0.1).")
        self._import_sessions("MobaXterm", config.import_mobaxterm_sessions(Path(path)), note)

    def import_ssh_config(self):
        from PySide6.QtWidgets import QFileDialog
        default = sshconfig.default_file()
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Select an OpenSSH config file"), str(default if default.exists() else default.parent),
            tr("OpenSSH config (config *.conf *.config)") + ";;" + tr("All files (*)"))
        if not path:
            return
        self._import_sessions("SSH config", sshconfig.import_ssh_config(Path(path)),
                              tr("Passwords are not part of an SSH config file; enter them when you first connect."))

    def import_tabby(self):
        if not config.TABBY_CONFIG.exists():
            QMessageBox.information(self, tr("Import {source}", source="Tabby"),
                                    tr("Tabby settings file not found.\n{path}", path=config.TABBY_CONFIG))
            return
        try:
            found = config.import_tabby_sessions()
        except ImportError:
            QMessageBox.warning(self, tr("Import {source}", source="Tabby"),
                                tr("pyyaml is not installed.\nReinstall with run.bat, or run: {cmd}",
                                   cmd=".venv\\Scripts\\pip install pyyaml"))
            return
        self._import_sessions("Tabby", found,
                              tr("Passwords are kept in Tabby's vault and were not imported — enter them when you first connect.\n"
                                 "Profiles without a user name were imported as root, as Tabby does."))

    def quick_connect(self):
        s = Session.parse_quick(self.quick.text())
        if s:
            self.quick.clear()
            self.open_session(s)

    # ------------------------------------------------------------ tabs
    def open_session(self, s: Session, password: str = "", passphrase: str = ""):
        if self.store.get(s.id):
            recent = [x for x in self.settings.get("recent", []) if x != s.id]
            self.settings["recent"] = [s.id] + recent[:19]
            config.save_settings(self.settings)
        tab = SessionTab(s, self, password, passphrase)
        tab.title_changed.connect(self._on_tab_title)
        idx = self.tabs.addTab(tab, s.title())
        self.tabs.setCurrentIndex(idx)
        tab.explorer.setVisible(self.settings.get("show_explorer", True))
        tab.connect()

    def _on_tab_title(self, tab, text):
        idx = self.tabs.indexOf(tab)
        if idx >= 0:
            if text.startswith(("⏳", "✕")) or not text:
                self.tabs.setTabText(idx, text or tab.session.title())
            else:
                # Window titles sent by the shell go to the tooltip only (the tab keeps the session name)
                if tab.state == "connected" and text != tab.session.title():
                    self.tabs.setTabToolTip(idx, text)
                    self.tabs.setTabText(idx, tab.session.title())
                else:
                    self.tabs.setTabText(idx, text)

    def current_tab(self) -> SessionTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, SessionTab) else None

    def close_tab(self, idx: int):
        w = self.tabs.widget(idx)
        if isinstance(w, SessionTab):
            w.shutdown()
            self.tabs.removeTab(idx)
            w.deleteLater()

    def close_pane_or_tab(self):
        """Close only the selected pane if split, otherwise close the tab."""
        t = self.current_tab()
        if t and t.close_pane():
            return
        self.close_tab(self.tabs.currentIndex())

    def duplicate_tab(self):
        t = self.current_tab()
        if t:
            self.open_session(t.session, t.password, t.passphrase)

    def split(self, orientation):
        t = self.current_tab()
        if t:
            t.split_pane(orientation)

    def toggle_explorer(self):
        show = not self.settings.get("show_explorer", True)
        self.settings["show_explorer"] = show
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, SessionTab):
                w.explorer.setVisible(show)
        config.save_settings(self.settings)

    def _cycle(self, d):
        n = self.tabs.count()
        if n:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + d) % n)
            t = self.current_tab()
            if t and t.active:
                t.active.setFocus()

    # ------------------------------------------------------------ fonts
    def _apply_font(self):
        self.settings["font_family"] = self.term_font.family()
        self.settings["font_size"] = self.term_font.pointSize()
        config.save_settings(self.settings)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, SessionTab):
                for p in w.panes:
                    p.set_font(self.term_font)

    def zoom_font(self, d: int):
        size = max(6, min(40, self.term_font.pointSize() + d))
        self.term_font.setPointSize(size)
        self._apply_font()

    def choose_font(self):
        ok, font = QFontDialog.getFont(self.term_font, self, tr("Terminal font"),
                                       QFontDialog.FontDialogOption.MonospacedFonts)
        if ok:
            self.term_font = pick_font(font.family(), font.pointSize())
            self._apply_font()

    def show_tunnels(self):
        self.show_home("forwarding")

    def show_home(self, page: str = "start"):
        self.tabs.setCurrentWidget(self.home)
        if page:
            self.home.show_page(page)

    def _on_tab_changed(self, idx: int):
        w = self.tabs.widget(idx)
        if isinstance(w, SessionTab):
            self.last_session_tab = w
        elif w is self.home:
            self.home.refresh_current()
        self._apply_sessions_panel()

    def _apply_sessions_panel(self):
        """Session list next to terminal tabs (full, or collapsed to a slim strip); none on Home."""
        on_terminal = isinstance(self.tabs.currentWidget(), SessionTab)
        expanded = bool(self.settings.get("show_sessions", True))
        dock = self.sessions_dock
        dock.setVisible(on_terminal)
        if expanded:
            self.sessions_stack.setCurrentWidget(self.sessions_full)
            self.sessions_stack.setMaximumWidth(16777215)
            self.sessions_stack.setMinimumWidth(200)
            if on_terminal and dock.width() < 200:
                self.resizeDocks([dock], [240], Qt.Orientation.Horizontal)
        else:
            self.sessions_stack.setCurrentWidget(self.sessions_strip)
            self.sessions_stack.setMinimumWidth(0)
            self.sessions_stack.setMaximumWidth(36)
            if on_terminal:
                self.resizeDocks([dock], [36], Qt.Orientation.Horizontal)
        if hasattr(self, "sessions_act"):
            self.sessions_act.setChecked(expanded)

    def toggle_sessions_panel(self):
        self.settings["show_sessions"] = not bool(self.settings.get("show_sessions", True))
        self._apply_sessions_panel()

    def _snippet_target(self) -> "SessionTab | None":
        t = self.current_tab()
        if t is None and self.last_session_tab is not None and self.tabs.indexOf(self.last_session_tab) >= 0:
            t = self.last_session_tab
        return t

    def send_snippet(self, snip):
        tab = self._snippet_target()
        pane = (tab.active or tab.panes[0]) if tab and tab.panes else None
        if pane is None or pane.disconnected:
            QMessageBox.information(self, tr("Snippets"), tr("Open a connected terminal first."))
            return
        self.tabs.setCurrentWidget(tab)
        pane.send_text(snip.text_to_send())
        pane.setFocus()

    def toggle_log(self):
        tab = self.current_tab()
        pane = (tab.active or tab.panes[0]) if tab and tab.panes else None
        if pane is None:
            QMessageBox.information(self, tr("Session log"), tr("Open a connected terminal first."))
            return
        if pane.logger is not None:
            pane.stop_log()
        else:
            pane.start_log()

    def open_log_folder(self):
        from . import sessionlog
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        d = Path(self.settings.get("log_dir") or sessionlog.default_dir())
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def start_tour(self, from_help: bool = False):
        from . import tour
        return tour.start(self, from_help=from_help)

    def open_app_log_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(applog.log_dir())))

    def find_in_terminal(self):
        tab = self.current_tab()
        pane = (tab.active or tab.panes[0]) if tab and tab.panes else None
        if pane is not None:
            pane.open_search()

    def pick_snippet(self):
        if not self.snippets.snippets:
            QMessageBox.information(self, tr("Snippets"), tr("No snippets yet. Add one on Home → Snippets."))
            self.show_home("snippets")
            return
        d = SnippetPicker(self.snippets, self)
        if d.exec() and d.chosen:
            self.send_snippet(d.chosen)

    def closeEvent(self, e):
        self.tunnels.stop_all()
        config.save_settings(self.settings)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, SessionTab):
                w.shutdown()
        super().closeEvent(e)


def apply_dark_theme(app: QApplication):
    """Backward-compatible old name — apply the saved appearance/font settings."""
    st = config.load_settings()
    theme.manager.apply(app, st.get("theme", DEFAULT_THEME), st.get("ui_font", "default"))
