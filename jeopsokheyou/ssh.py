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

    def __init__(self, session: Session, password: str = "", passphrase: str = ""):
        self.session = session
        self._password = password
        self._passphrase = passphrase
        self.client: paramiko.SSHClient | None = None
        self._lock = threading.Lock()

    # Called from a worker thread
    def connect(self) -> None:
        s = self.session
        client = paramiko.SSHClient()
        if KNOWN_HOSTS_FILE.exists():
            client.load_host_keys(str(KNOWN_HOSTS_FILE))
        client.set_missing_host_key_policy(_AskPolicy())
        kwargs = dict(
            hostname=s.host, port=int(s.port or 22), username=s.user or None,
            timeout=10, banner_timeout=15, auth_timeout=20,
        )
        if s.auth == "key":
            kwargs.update(
                key_filename=s.key_path or None,
                passphrase=self._passphrase or None,
                password=self._password or None,
                allow_agent=True, look_for_keys=not s.key_path,
            )
        else:
            kwargs.update(password=self._password, allow_agent=False, look_for_keys=False)
        client.connect(**kwargs)
        t = client.get_transport()
        if t is not None:
            t.set_keepalive(30)
        self.client = client

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
