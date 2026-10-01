# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""SSH connection based on paramiko. Connecting/receiving run in a QThread so the UI thread is not blocked."""
from __future__ import annotations

import socket
import threading

import paramiko
from PySide6.QtCore import QThread, Signal

from .config import KNOWN_HOSTS_FILE, Session
from .i18n import tr


class UnknownHostKey(Exception):
    def __init__(self, hostname: str, key: paramiko.PKey):
        super().__init__(hostname)
        self.hostname = hostname
        self.key = key


class JumpFailed(Exception):
    def __init__(self, via: str, target: str, error: Exception):
        super().__init__(f"{via} → {target}: {error}")
        self.via, self.target = via, target


class JumpAuthFailed(Exception):
    def __init__(self, via: str):
        super().__init__(via)
        self.via = via


class _AskPolicy(paramiko.MissingHostKeyPolicy):
    """Reject unknown host keys and ask the UI for confirmation (same behavior as PuTTY)."""

    def missing_host_key(self, client, hostname, key):
        raise UnknownHostKey(hostname, key)


def fingerprint(key: paramiko.PKey) -> str:
    return key.fingerprint  # 'SHA256:...'


def trust_host_key(hostname: str, key: paramiko.PKey) -> None:
    hk = paramiko.HostKeys()
    if KNOWN_HOSTS_FILE.exists():
        hk.load(str(KNOWN_HOSTS_FILE))
    hk.add(hostname, key.get_name(), key)
    hk.save(str(KNOWN_HOSTS_FILE))


class SshConnection:
    """SSH connection for one session. Multiple shell channels/SFTP can be opened on the same transport."""

    def __init__(self, session: Session, password: str = "", passphrase: str = "",
                 jumps: list[tuple[Session, str, str]] | None = None):
        """``jumps``: (session, password, passphrase) of the jump hosts to go through, outermost first."""
        self.session = session
        self._password = password
        self._passphrase = passphrase
        self._jumps = list(jumps or [])
        self.client: paramiko.SSHClient | None = None
        self._jump_clients: list[paramiko.SSHClient] = []
        self._lock = threading.Lock()

    @staticmethod
    def _connect_one(s: Session, password: str, passphrase: str, sock=None) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        if KNOWN_HOSTS_FILE.exists():
            client.load_host_keys(str(KNOWN_HOSTS_FILE))
        client.set_missing_host_key_policy(_AskPolicy())
        kwargs = dict(
            hostname=s.host, port=int(s.port or 22), username=s.user or None,
            timeout=10, banner_timeout=15, auth_timeout=20, sock=sock,
        )
        if s.auth == "key":
            kwargs.update(
                key_filename=s.key_path or None,
                passphrase=passphrase or None,
                password=password or None,
                allow_agent=True, look_for_keys=not s.key_path,
            )
        else:
            kwargs.update(password=password, allow_agent=False, look_for_keys=False)
        client.connect(**kwargs)
        t = client.get_transport()
        if t is not None:
            t.set_keepalive(30)
        return client

    # Called from a worker thread
    def connect(self) -> None:
        self._close_jumps()
        sock = None
        chain = self._jumps + [(self.session, self._password, self._passphrase)]
        try:
            for i, (s, pw, pp) in enumerate(chain):
                try:
                    client = self._connect_one(s, pw, pp, sock)
                except paramiko.AuthenticationException as e:
                    if i < len(chain) - 1:
                        raise JumpAuthFailed(s.title()) from e
                    raise
                if i == len(chain) - 1:
                    self.client = client
                    break
                self._jump_clients.append(client)
                nxt = chain[i + 1][0]
                try:
                    sock = client.get_transport().open_channel(
                        "direct-tcpip", (nxt.host, int(nxt.port or 22)), ("127.0.0.1", 0), timeout=15)
                except paramiko.ChannelException as e:
                    raise JumpFailed(s.title(), nxt.host, e) from e
        except Exception:
            self._close_jumps()
            raise

    @property
    def transport(self) -> paramiko.Transport | None:
        return self.client.get_transport() if self.client else None

    def _close_jumps(self) -> None:
        for c in reversed(self._jump_clients):
            try:
                c.close()
            except Exception:
                pass
        self._jump_clients = []

    @property
    def alive(self) -> bool:
        t = self.client.get_transport() if self.client else None
        return bool(t and t.is_active())

    def open_shell(self, cols: int, rows: int) -> paramiko.Channel:
        with self._lock:
            chan = self.client.invoke_shell(term="xterm-256color", width=cols, height=rows)
        chan.settimeout(None)
        return chan

    def open_sftp(self) -> paramiko.SFTPClient:
        with self._lock:
            return self.client.open_sftp()

    def close(self) -> None:
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
        self._close_jumps()


class ConnectWorker(QThread):
    ok = Signal()
    failed = Signal(str)
    auth_failed = Signal(str)
    unknown_host = Signal(str, object)  # hostname, key

    def __init__(self, conn: SshConnection):
        super().__init__()
        self.conn = conn

    def run(self):
        try:
            self.conn.connect()
            self.ok.emit()
        except UnknownHostKey as e:
            self.unknown_host.emit(e.hostname, e.key)
        except paramiko.BadHostKeyException as e:
            self.failed.emit(tr(
                "⚠ The server host key does not match the stored one! (possible man-in-the-middle attack)\n"
                "Host: {host}\nReceived key: {fingerprint}\n"
                "To trust it, delete the matching line in {known_hosts}.",
                host=e.hostname, fingerprint=e.key.fingerprint, known_hosts=KNOWN_HOSTS_FILE,
            ))
        except paramiko.AuthenticationException as e:
            self.auth_failed.emit(tr("Authentication failed: {error}", error=e))
        except JumpAuthFailed as e:
            self.failed.emit(tr("Authentication to the jump host {via} failed. "
                                "Check the password or key saved in that session.", via=e.via))
        except JumpFailed as e:
            self.failed.emit(tr("The jump host {via} could not reach {target}.", via=e.via, target=e.target))
        except (socket.timeout, TimeoutError):
            self.failed.emit(tr("Connection timed out"))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class ShellReader(QThread):
    """Read shell channel output and forward it to the UI."""
    data = Signal(bytes)
    closed = Signal()

    def __init__(self, chan: paramiko.Channel):
        super().__init__()
        self.chan = chan

    def run(self):
        try:
            while True:
                buf = self.chan.recv(65536)
                if not buf:
                    break
                self.data.emit(buf)
        except Exception:
            pass
        self.closed.emit()
