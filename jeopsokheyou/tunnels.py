# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Port forwarding UI: saved tunnels that run on their own (like MobaXterm's MobaSSHTunnel),
the forward editor shared with the session dialog, and the Port Forwarding page."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import config, icons
from .config import Session, SessionStore
from .forwarding import KIND_LABELS, KINDS, Forward, ForwardRunner
from .i18n import tr
from .ssh import ConnectWorker, SshConnection, trust_host_key

TUNNELS_FILE = config.app_dir() / "tunnels.json"
RECONNECT_DELAY_MS = 5000
NO_SERVER_MESSAGE = "Choose the SSH server to connect through (add a session first)"
WATCH_MS = 3000

KIND_HINTS = {
    "L": "Connections to the listening port on this PC are forwarded through the SSH server to the destination.",
    "R": "The SSH server listens on the port; connections come back to the destination as seen from this PC.",
    "D": "A SOCKS4/5 proxy on this PC. Point a browser or other app at it to reach hosts through the SSH server.",
}


def error_text(code: str) -> str:
    return {"port-in-use": tr("the port is already in use"),
            "server-refused": tr("the server refused the forwarding request")}.get(code, code)


# ------------------------------------------------------------------ data
@dataclass
class Tunnel:
    name: str = ""
    session_id: str = ""
    forward: dict = field(default_factory=lambda: Forward().to_dict())
    autostart: bool = False       # start when JeopsokHeyou starts
    reconnect: bool = True        # reconnect automatically when the connection drops
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def from_dict(cls, d: dict) -> "Tunnel":
        t = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        t.forward = Forward.from_dict(t.forward if isinstance(t.forward, dict) else {}).to_dict()
        return t

    @property
    def fwd(self) -> Forward:
        return Forward.from_dict(self.forward)


class TunnelStore:
    def __init__(self, path=TUNNELS_FILE):
        self.path = path
        self.tunnels: list[Tunnel] = []
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.tunnels = [Tunnel.from_dict(d) for d in data.get("tunnels", []) if isinstance(d, dict)]
        except (OSError, ValueError):
            self.tunnels = []

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"tunnels": [asdict(t) for t in self.tunnels]}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)

    def upsert(self, t: Tunnel) -> None:
        for i, cur in enumerate(self.tunnels):
            if cur.id == t.id:
                self.tunnels[i] = t
                break
        else:
            self.tunnels.append(t)
        self.save()

    def remove(self, tid: str) -> None:
        self.tunnels = [t for t in self.tunnels if t.id != tid]
        self.save()

    def get(self, tid: str) -> Tunnel | None:
        return next((t for t in self.tunnels if t.id == tid), None)


# ------------------------------------------------------------------ MobaXterm (MobaSSHTunnel)
MOBA_KINDS = {"local": "L", "remote": "R", "dynamic": "D"}
MOBA_NO_KEY = "no ssh key selected"


def _moba_hostport(text: str) -> tuple[str, int] | None:
    host, _, port = text.strip().rpartition(":")
    host = host.strip("[]")
    if not host or host == "-" or not port.isdigit():
        return None
    return host, int(port)


def parse_mobaxterm_tunnels(path) -> list[dict]:
    """Tunnels from the [PortForwarding] section of MobaXterm.ini. Each line looks like::

        0000.name=Local;user@ssh-host:22;dest-host:3306;13306;0;No SSH key selected;0.0.0.0;No proxy selected;0

    (type; SSH server; destination, "-:0" for Dynamic; forwarded port; ?; private key; listen address; proxy; ?).
    Autostart/auto-reconnect are not written to the file, so they are not imported.
    """
    from pathlib import Path
    try:
        text = config._read_text_any(Path(path))
    except OSError:
        return []
    out, in_section = [], False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_section = line[1:-1].strip().lower() == "portforwarding"
            continue
        if not in_section or "=" not in line:
            continue
        key, value = line.split("=", 1)
        f = value.split(";")
        if len(f) < 4 or f[0].strip().lower() not in MOBA_KINDS:
            continue
        kind = MOBA_KINDS[f[0].strip().lower()]
        user, _, server = f[1].strip().rpartition("@")
        ssh = _moba_hostport(server)
        if not ssh or not f[3].strip().isdigit():
            continue
        dest = _moba_hostport(f[2]) if kind != "D" else ("", 0)
        if dest is None:
            continue
        key_field = f[5].strip() if len(f) > 5 else ""
        key_path = "" if not key_field or key_field.lower() == MOBA_NO_KEY else \
            (config._moba_key_path([key_field]) or key_field)
        bind = f[6].strip() if len(f) > 6 and f[6].strip() else ""
        if kind != "R" and bind in ("", "0.0.0.0", "*"):
            # MobaXterm listens on every network interface by default; keep imported tunnels to this PC only
            # (a SOCKS proxy open to the whole LAN is easy to miss). Can be changed per tunnel.
            bind = "127.0.0.1"
        elif kind == "R" and not bind:
            bind = "localhost"
        name = key.split(".", 1)[1].strip() if "." in key else ""
        out.append({"name": name, "user": user, "host": ssh[0], "port": ssh[1], "key_path": key_path,
                    "forward": Forward(kind, bind, int(f[3]), dest[0], dest[1]).to_dict()})
    return out


def import_mobaxterm_tunnels(path, store: SessionStore, tunnel_store: "TunnelStore") -> tuple[int, int, int]:
    """Add MobaXterm tunnels (and the SSH sessions they need). Returns (added, already present, new sessions)."""
    added = dup = new_sessions = 0
    for t in parse_mobaxterm_tunnels(path):
        s = next((x for x in store.sessions if (x.host, x.port, x.user) == (t["host"], t["port"], t["user"])), None)
        if s is None:
            s = Session(name=f"{t['user']}@{t['host']}" if t["user"] else t["host"], host=t["host"], port=t["port"],
                        user=t["user"], group="MobaXterm", auth="key" if t["key_path"] else "password",
                        key_path=t["key_path"])
            store.sessions.append(s)
            new_sessions += 1
        if any(x.session_id == s.id and x.forward == t["forward"] for x in tunnel_store.tunnels):
            dup += 1
            continue
        tunnel_store.tunnels.append(Tunnel(name=t["name"] or Forward.from_dict(t["forward"]).describe(),
                                           session_id=s.id, forward=t["forward"]))
        added += 1
    store.save()
    tunnel_store.save()
    return added, dup, new_sessions


# ------------------------------------------------------------------ connecting with prompts
def ask_trust_host(parent, hostname: str, key) -> bool:
    r = QMessageBox.question(
        parent, tr("First connection to server"),
        tr("This server's host key is not registered.\n\n"
           "Host: {host}\nKey type: {key_type}\nFingerprint: {fingerprint}\n\n"
           "Trust it and connect? (You won't be asked again)",
           host=hostname, key_type=key.get_name(), fingerprint=key.fingerprint))
    if r == QMessageBox.StandardButton.Yes:
        trust_host_key(hostname, key)
        return True
    return False


def ask_password(parent, s: Session, jump: bool = False, store: SessionStore | None = None) -> str | None:
    """Saved password, or ask for it (None = cancelled). Key sessions never ask.
    With ``store``, the prompt offers to save the password with the session."""
    pw = s.password
    if pw or s.auth != "password":
        return pw
    from .dialogs import ask_password_saving
    target = f"{s.user}@{s.host}"
    label = tr("Password for jump host {target}:", target=target) if jump else tr("Password for {target}:", target=target)
    return ask_password_saving(parent, label, s, store)


def jump_credentials(parent, store: SessionStore, s: Session, cache: dict) -> list[tuple[Session, str, str]] | None:
    """(session, password, passphrase) for each jump host; ``cache`` keeps typed passwords for reconnects."""
    out = []
    for j in store.jump_chain(s):
        pw = cache.get(j.id)
        if pw is None:
            pw = ask_password(parent, j, jump=True, store=store)
            if pw is None:
                return None
            cache[j.id] = pw
        out.append((j, pw, j.passphrase))
    return out


# ------------------------------------------------------------------ running tunnels
class TunnelRunner(QObject):
    """Keeps one saved tunnel running: its own SSH connection, the forward, and automatic reconnects."""
    changed = Signal()
    _forward_changed = Signal()

    def __init__(self, tunnel: Tunnel, manager: "TunnelManager"):
        super().__init__(manager)
        self.tunnel = tunnel
        self.manager = manager
        self.state = "stopped"      # stopped | connecting | running | reconnecting | error
        self.error = ""
        self.conn: SshConnection | None = None
        self.worker: ConnectWorker | None = None
        self.forward: ForwardRunner | None = None
        self._password = ""
        self._jump_cache: dict = {}
        self._jumps: list = []
        self._wanted = False
        self._forward_changed.connect(self.changed)
        self._watch = QTimer(self)
        self._watch.setInterval(WATCH_MS)
        self._watch.timeout.connect(self._check)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._connect)

    @property
    def session(self) -> Session | None:
        return self.manager.store.get(self.tunnel.session_id)

    def status_text(self) -> str:
        if self.state == "running" and self.forward:
            n = self.forward.active
            return tr("Running") + (" · " + tr("{n} connections", n=n) if n else "")
        return {"stopped": tr("Stopped"), "connecting": tr("Connecting…"),
                "reconnecting": tr("Reconnecting…"), "error": tr("Error: {error}", error=self.error)}.get(self.state, "")

    def start(self, parent=None) -> None:
        s = self.session
        if s is None:
            self._set("error", tr("the SSH session was deleted"))
            return
        if s.auth == "password" and not self._password:
            pw = ask_password(parent, s)
            if pw is None:
                return
            self._password = pw
        jumps = jump_credentials(parent, self.manager.store, s, self._jump_cache)
        if jumps is None:
            return
        self._jumps = jumps
        self._wanted = True
        self._connect()

    def stop(self) -> None:
        self._wanted = False
        self._retry.stop()
        self._watch.stop()
        self._teardown()
        self._set("stopped")

    def _teardown(self) -> None:
        if self.forward:
            self.forward.stop()
            self.forward = None
        if self.conn:
            self.conn.close()
            self.conn = None

    def _connect(self) -> None:
        s = self.session
        if not self._wanted or s is None:
            return
        self._teardown()
        self._set("connecting" if self.state != "reconnecting" else "reconnecting")
        self.conn = SshConnection(s, self._password, s.passphrase, self._jumps)
        self.worker = ConnectWorker(self.conn)
        self.worker.ok.connect(self._on_ok)
        self.worker.failed.connect(self._on_failed)
        self.worker.auth_failed.connect(self._on_auth_failed)
        self.worker.unknown_host.connect(self._on_unknown_host)
        self.worker.start()

    def _on_ok(self) -> None:
        if not self._wanted:
            self._teardown()
            return
        self.forward = ForwardRunner(self.tunnel.fwd, self.conn.transport, self._forward_changed.emit)
        if not self.forward.start():
            err = error_text(self.forward.error)
            self._teardown()
            self._wanted = False
            self._set("error", err)
            return
        self._set("running")
        self._watch.start()

    def _on_failed(self, msg: str) -> None:
        self._teardown()
        if self._wanted and self.tunnel.reconnect:
            self.error = msg
            self._set("reconnecting")
            self._retry.start(RECONNECT_DELAY_MS)
        else:
            self._wanted = False
            self._set("error", msg)

    def _on_auth_failed(self, msg: str) -> None:
        self._password = ""
        self._wanted = False
        self._teardown()
        self._set("error", msg)

    def _on_unknown_host(self, hostname: str, key) -> None:
        if ask_trust_host(self.manager.dialog_parent(), hostname, key):
            self._connect()
        else:
            self._wanted = False
            self._teardown()
            self._set("error", tr("Connection cancelled."))

    def _check(self) -> None:
        if self.state != "running":
            return
        t = self.conn.transport if self.conn else None
        if t is None or not t.is_active():
            self._watch.stop()
            self._on_failed(tr("Connection lost"))

    def _set(self, state: str, error: str = "") -> None:
        self.state = state
        if error or state in ("running", "stopped"):
            self.error = error
        self.changed.emit()


class TunnelManager(QObject):
    changed = Signal()

    def __init__(self, store: SessionStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.tunnels = TunnelStore()
        self.runners: dict[str, TunnelRunner] = {}

    def dialog_parent(self):
        p = self.parent()
        return p if isinstance(p, QWidget) else None

    def runner(self, tid: str) -> TunnelRunner:
        r = self.runners.get(tid)
        t = self.tunnels.get(tid)
        if r is None:
            r = TunnelRunner(t, self)
            r.changed.connect(self.changed)
            self.runners[tid] = r
        elif t is not None:
            r.tunnel = t
        return r

    def start(self, tid: str) -> None:
        self.runner(tid).start(self.dialog_parent())

    def stop(self, tid: str) -> None:
        if tid in self.runners:
            self.runners[tid].stop()

    def start_all(self) -> None:
        for t in self.tunnels.tunnels:
            if self.runner(t.id).state in ("stopped", "error"):
                self.start(t.id)

    def stop_all(self) -> None:
        for r in self.runners.values():
            r.stop()

    def autostart(self) -> None:
        for t in self.tunnels.tunnels:
            if t.autostart:
                self.start(t.id)

    def remove(self, tid: str) -> None:
        self.stop(tid)
        self.runners.pop(tid, None)
        self.tunnels.remove(tid)
        self.changed.emit()

    def upsert(self, t: Tunnel) -> None:
        was_running = t.id in self.runners and self.runners[t.id].state == "running"
        if was_running:
            self.stop(t.id)
        self.tunnels.upsert(t)
        if t.id in self.runners:
            self.runners[t.id].tunnel = t
        if was_running:
            self.start(t.id)
        self.changed.emit()

    def running_count(self) -> int:
        return sum(1 for r in self.runners.values() if r.state == "running")


# ------------------------------------------------------------------ editing
class ForwardDialog(QDialog):
    """Edit one forward; with ``store`` it edits a whole saved tunnel (name, SSH server, options)."""

    def __init__(self, fwd: Forward | None = None, parent=None, tunnel: Tunnel | None = None,
                 store: SessionStore | None = None):
        super().__init__(parent)
        self.tunnel = tunnel
        editing = fwd is not None or (tunnel is not None and bool(tunnel.name))
        self.setWindowTitle(tr("Edit Port Forwarding") if editing else tr("New Port Forwarding"))
        self.setMinimumWidth(480)
        f = fwd or (tunnel.fwd if tunnel else Forward())
        form = QFormLayout(self)
        form.setVerticalSpacing(10)
        if tunnel is not None:
            self.name = QLineEdit(tunnel.name)
            self.name.setPlaceholderText(tr("e.g. Production database"))
            form.addRow(tr("Name"), self.name)
            self.session = QComboBox()
            for s in sorted(store.sessions, key=lambda x: (x.group.lower(), x.title().lower())):
                self.session.addItem(icons.line("server"), (f"{s.group} / " if s.group else "") + s.title(), s.id)
            self.session.setCurrentIndex(max(0, self.session.findData(tunnel.session_id)))
            form.addRow(tr("SSH server"), self.session)
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(f"{tr(KIND_LABELS[k])}  (-{k})", k)
        self.kind.setCurrentIndex(KINDS.index(f.kind) if f.kind in KINDS else 0)
        self.kind.currentIndexChanged.connect(self._sync)
        form.addRow(tr("Type"), self.kind)
        self.hint = QLabel()
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        form.addRow("", self.hint)
        self.bind_host = QLineEdit(f.bind_host)
        self.bind_port = QSpinBox()
        self.bind_port.setRange(0, 65535)
        self.bind_port.setValue(f.bind_port)
        form.addRow(tr("Listen address"), self._row(self.bind_host, self.bind_port))
        self.bind_note = QLabel()
        self.bind_note.setObjectName("Muted")
        self.bind_note.setWordWrap(True)
        form.addRow("", self.bind_note)
        self.dest_host = QLineEdit(f.dest_host)
        self.dest_host.setPlaceholderText(tr("e.g. localhost or db.internal"))
        self.dest_port = QSpinBox()
        self.dest_port.setRange(0, 65535)
        self.dest_port.setValue(f.dest_port)
        self.dest_row = self._row(self.dest_host, self.dest_port)
        form.addRow(tr("Destination"), self.dest_row)
        if tunnel is not None:
            self.autostart = QCheckBox(tr("Start when JeopsokHeyou starts"))
            self.autostart.setChecked(tunnel.autostart)
            self.reconnect = QCheckBox(tr("Reconnect automatically when the connection drops"))
            self.reconnect.setChecked(tunnel.reconnect)
            form.addRow("", self.autostart)
            form.addRow("", self.reconnect)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._last_kind = None
        self._sync()

    @staticmethod
    def _row(host: QLineEdit, port: QSpinBox) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(host, 1)
        lay.addWidget(QLabel(":"))
        lay.addWidget(port)
        return w

    def _sync(self):
        k = self.kind.currentData()
        self.hint.setText(tr(KIND_HINTS[k]))
        self.dest_row.setEnabled(k != "D")
        # Switching between "this PC" and "the server" listen side: swap in the matching default
        if self._last_kind is not None and (k == "R") != (self._last_kind == "R"):
            if self.bind_host.text() in ("127.0.0.1", "localhost", ""):
                self.bind_host.setText("localhost" if k == "R" else "127.0.0.1")
        self._last_kind = k
        self.bind_note.setText(tr("On the SSH server. 0 lets the server choose a port.") if k == "R" else
                               tr("On this PC. Use 0.0.0.0 to allow other computers to connect."))

    def forward(self) -> Forward:
        return Forward(self.kind.currentData(), self.bind_host.text().strip(), self.bind_port.value(),
                       self.dest_host.text().strip() if self.kind.currentData() != "D" else "",
                       self.dest_port.value() if self.kind.currentData() != "D" else 0)

    def _accept(self):
        err = self.forward().validate()
        if not err and self.tunnel is not None and not self.session.currentData():
            err = NO_SERVER_MESSAGE
        if err:
            QMessageBox.warning(self, tr("Check Input"), tr(err))
            return
        if self.tunnel is not None:
            t = self.tunnel
            t.name = self.name.text().strip()
            t.session_id = self.session.currentData()
            t.forward = self.forward().to_dict()
            t.autostart = self.autostart.isChecked()
            t.reconnect = self.reconnect.isChecked()
            if not t.name:
                t.name = self.forward().describe()
        self.accept()


class ForwardListEditor(QWidget):
    """Forwards opened together with a session (used in the session dialog)."""

    def __init__(self, forwards: list[dict], parent=None):
        super().__init__(parent)
        self.forwards = [Forward.from_dict(d) for d in forwards]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMaximumHeight(96)
        self.list.itemDoubleClicked.connect(lambda _i: self._edit())
        lay.addWidget(self.list, 1)
        btns = QVBoxLayout()
        for text, slot in ((tr("Add…"), self._add), (tr("Edit…"), self._edit), (tr("Remove"), self._remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)
        self._refresh()

    def _refresh(self):
        self.list.clear()
        for f in self.forwards:
            QListWidgetItem(f.describe(), self.list)
        if not self.forwards:
            it = QListWidgetItem(tr("None — opened when you connect to this session"), self.list)
            it.setFlags(Qt.ItemFlag.NoItemFlags)

    def _add(self):
        d = ForwardDialog(None, self)
        if d.exec():
            self.forwards.append(d.forward())
            self._refresh()

    def _edit(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.forwards):
            d = ForwardDialog(self.forwards[row], self)
            if d.exec():
                self.forwards[row] = d.forward()
                self._refresh()

    def _remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.forwards):
            del self.forwards[row]
            self._refresh()

    def values(self) -> list[dict]:
        return [f.to_dict() for f in self.forwards]


# ------------------------------------------------------------------ page
STATE_COLORS = {"running": "#34C759", "connecting": "#FF9F0A", "reconnecting": "#FF9F0A",
                "error": "#FF3B30", "stopped": "#8E8E93"}


class TunnelsPage(QWidget):
    """Port Forwarding page: saved tunnels with start/stop, status and live connection counts."""
    COLS = ("Name", "Type", "Listen", "Destination", "SSH server", "Status")

    def __init__(self, manager: TunnelManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        top = QHBoxLayout()
        title = QLabel(tr("Port Forwarding"))
        title.setObjectName("PageTitle")
        top.addWidget(title)
        top.addStretch(1)
        self.new_btn = QPushButton(icons.line("plus"), tr("New tunnel"))
        self.new_btn.clicked.connect(self.new_tunnel)
        self.start_btn = QPushButton(tr("Start"))
        self.start_btn.clicked.connect(lambda: self._each(self.manager.start))
        self.stop_btn = QPushButton(tr("Stop"))
        self.stop_btn.clicked.connect(lambda: self._each(self.manager.stop))
        self.start_all_btn = QPushButton(tr("Start all"))
        self.start_all_btn.clicked.connect(self.manager.start_all)
        self.stop_all_btn = QPushButton(tr("Stop all"))
        self.stop_all_btn.clicked.connect(self.manager.stop_all)
        for b in (self.start_btn, self.stop_btn, self.start_all_btn, self.stop_all_btn, self.new_btn):
            top.addWidget(b)
        lay.addLayout(top)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in self.COLS])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.edit_tunnel(self._id_at(r)))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        lay.addWidget(self.table, 1)
        self.empty = QLabel(tr("No tunnels yet. Add one to keep a port forward running without opening a terminal."))
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)
        self._refresh_pending = False
        manager.changed.connect(self._schedule_refresh)
        self.refresh()

    def _schedule_refresh(self):
        if not self._refresh_pending:     # connection counts can change often — coalesce
            self._refresh_pending = True
            QTimer.singleShot(150, self.refresh)

    def refresh(self):
        self._refresh_pending = False
        selected = set(self.selected_ids())
        tunnels = self.manager.tunnels.tunnels
        self.table.setRowCount(len(tunnels))
        for row, t in enumerate(tunnels):
            f = t.fwd
            s = self.manager.store.get(t.session_id)
            r = self.manager.runners.get(t.id)
            state = r.state if r else "stopped"
            values = (t.name, f"{tr(KIND_LABELS[f.kind])} (-{f.kind})", f.listen_text() if f.kind != "R" or not r
                      or not r.forward else f"{f.bind_host}:{r.forward.bound_port}",
                      f.dest_text() if f.kind != "D" else "SOCKS", s.title() if s else tr("(deleted session)"),
                      r.status_text() if r else tr("Stopped"))
            for col, v in enumerate(values):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, t.id)
                if col == 0:
                    it.setIcon(icons.dot(STATE_COLORS.get(state, "#8E8E93")))
                if col == 5 and state == "error":
                    it.setForeground(QColor(STATE_COLORS["error"]))
                    it.setToolTip(r.error if r else "")
                self.table.setItem(row, col, it)
            if t.id in selected:
                self.table.selectRow(row)
        self.empty.setVisible(not tunnels)
        self._sync_buttons()

    def _id_at(self, row: int) -> str:
        it = self.table.item(row, 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else ""

    def selected_ids(self) -> list[str]:
        return list(dict.fromkeys(self._id_at(i.row()) for i in self.table.selectedIndexes()))

    def _each(self, fn):
        for tid in self.selected_ids():
            fn(tid)

    def _sync_buttons(self):
        ids = self.selected_ids()
        states = [self.manager.runners[i].state if i in self.manager.runners else "stopped" for i in ids]
        self.start_btn.setEnabled(any(s in ("stopped", "error") for s in states))
        self.stop_btn.setEnabled(any(s not in ("stopped", "error") for s in states))
        has = bool(self.manager.tunnels.tunnels)
        self.start_all_btn.setEnabled(has)
        self.stop_all_btn.setEnabled(self.manager.running_count() > 0 or
                                     any(r.state in ("connecting", "reconnecting") for r in self.manager.runners.values()))

    def _menu(self, pos):
        ids = self.selected_ids()
        if not ids:
            return
        m = QMenu(self)
        m.addAction(tr("Start"), lambda: self._each(self.manager.start))
        m.addAction(tr("Stop"), lambda: self._each(self.manager.stop))
        m.addSeparator()
        m.addAction(tr("Edit…"), lambda: self.edit_tunnel(ids[0]))
        m.addAction(tr("Duplicate"), lambda: self.duplicate(ids[0]))
        m.addAction(tr("Delete"), lambda: self.delete(ids))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def new_tunnel(self, session_id: str = ""):
        if not self.manager.store.sessions:
            QMessageBox.information(self, tr("Port Forwarding"),
                                    tr("A tunnel connects through a saved session. Add a session first."))
            return
        t = Tunnel(session_id=session_id if isinstance(session_id, str) else "")
        t.forward = Forward("L", "127.0.0.1", 0).to_dict()
        d = ForwardDialog(None, self, tunnel=t, store=self.manager.store)
        if d.exec():
            self.manager.upsert(t)

    def edit_tunnel(self, tid: str):
        t = self.manager.tunnels.get(tid)
        if t is None:
            return
        copy = Tunnel.from_dict(asdict(t))
        d = ForwardDialog(None, self, tunnel=copy, store=self.manager.store)
        if d.exec():
            self.manager.upsert(copy)

    def duplicate(self, tid: str):
        t = self.manager.tunnels.get(tid)
        if t:
            c = Tunnel.from_dict({k: v for k, v in asdict(t).items() if k != "id"})
            c.name = t.name + " " + tr("(copy)")
            c.autostart = False
            self.manager.upsert(c)

    def delete(self, ids: list[str]):
        names = ", ".join(self.manager.tunnels.get(i).name for i in ids if self.manager.tunnels.get(i))
        if QMessageBox.question(self, tr("Delete tunnel"), tr("Delete {names}?", names=names)) == \
                QMessageBox.StandardButton.Yes:
            for i in ids:
                self.manager.remove(i)
