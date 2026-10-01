# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""SSH port forwarding over a paramiko transport (no Qt here, so it can be tested on its own).

- Local  (-L): listen on this PC, connect to dest_host:dest_port through the server.
- Remote (-R): the server listens on bind_host:bind_port, connections come back to dest_host:dest_port
  as seen from this PC.
- Dynamic (-D): a SOCKS proxy (SOCKS5 with no authentication, SOCKS4 and SOCKS4a) on this PC.
"""
from __future__ import annotations

import ipaddress
import socket
import struct
import threading
from dataclasses import asdict, dataclass
from typing import Callable

import paramiko

KINDS = ("L", "R", "D")
KIND_LABELS = {"L": "Local", "R": "Remote", "D": "Dynamic (SOCKS)"}   # English source strings, shown with tr()
VALIDATION_MESSAGES = ("Unknown forwarding type", "Enter a listening port between 1 and 65535",
                       "Enter a destination host and port")   # returned by Forward.validate(), shown with tr()


@dataclass
class Forward:
    kind: str = "L"
    bind_host: str = "127.0.0.1"
    bind_port: int = 0
    dest_host: str = ""
    dest_port: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "Forward":
        f = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        f.bind_port, f.dest_port = int(f.bind_port or 0), int(f.dest_port or 0)
        return f

    def to_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> str:
        """Return an English error message, or "" when valid."""
        if self.kind not in KINDS:
            return "Unknown forwarding type"
        if not 0 < self.bind_port < 65536 and not (self.kind == "R" and self.bind_port == 0):
            return "Enter a listening port between 1 and 65535"
        if self.kind != "D" and (not self.dest_host or not 0 < self.dest_port < 65536):
            return "Enter a destination host and port"
        return ""

    def listen_text(self) -> str:
        return f"{_fmt_host(self.bind_host or '127.0.0.1')}:{self.bind_port}"

    def dest_text(self) -> str:
        return "SOCKS" if self.kind == "D" else f"{_fmt_host(self.dest_host)}:{self.dest_port}"

    def describe(self) -> str:
        return f"{self.kind}  {self.listen_text()} → {self.dest_text()}"


def _fmt_host(h: str) -> str:
    return f"[{h}]" if ":" in h else h


def _pump(a, b) -> None:
    """Copy data both ways between a socket and a channel until either side closes."""
    def one_way(src, dst):
        try:
            while True:
                data = src.recv(32768)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        for x in (src, dst):
            try:
                x.close()
            except Exception:
                pass

    threading.Thread(target=one_way, args=(a, b), daemon=True).start()
    one_way(b, a)


class ForwardRunner:
    """One running forward. ``on_change`` is called (from any thread) when status or the connection count changes."""

    def __init__(self, fwd: Forward, transport: paramiko.Transport, on_change: Callable[[], None] | None = None):
        self.fwd = fwd
        self.transport = transport
        self.on_change = on_change or (lambda: None)
        self.error = ""
        self.active = 0          # open connections
        self.total = 0           # connections served
        self.running = False
        self.bound_port = fwd.bind_port
        self._lock = threading.Lock()
        self._server: socket.socket | None = None

    # --------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        try:
            if self.fwd.kind == "R":
                self._start_remote()
            else:
                self._start_listener()
            self.running = True
            self.error = ""
        except Exception as e:
            self.error = _describe_error(e)
            self.running = False
        self.on_change()
        return self.running

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        if self.fwd.kind == "R":
            _RemoteDispatcher.get(self.transport).remove(self)
        elif self._server is not None:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None
        self.on_change()

    # --------------------------------------------------------------- local / dynamic
    def _start_listener(self) -> None:
        host = self.fwd.bind_host or "127.0.0.1"
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        srv = socket.socket(family, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)   # Windows: no port sharing
        else:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((host, self.fwd.bind_port))
            srv.listen(64)
        except Exception:
            srv.close()
            raise
        self._server = srv
        self.bound_port = srv.getsockname()[1]
        threading.Thread(target=self._accept_loop, args=(srv,), daemon=True).start()

    def _accept_loop(self, srv: socket.socket) -> None:
        while self.running or self._server is srv:
            try:
                client, addr = srv.accept()
            except OSError:
                break
            threading.Thread(target=self._serve_client, args=(client, addr), daemon=True).start()

    def _serve_client(self, client: socket.socket, addr) -> None:
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            if self.fwd.kind == "D":
                chan = _socks_handshake(client, self._open_channel)
            else:
                chan = self._open_channel(self.fwd.dest_host, self.fwd.dest_port, addr)
        except Exception:
            chan = None
        if chan is None:
            try:
                client.close()
            except Exception:
                pass
            return
        self._count(+1)
        try:
            _pump(client, chan)
        finally:
            self._count(-1)

    def _open_channel(self, host: str, port: int, origin=("127.0.0.1", 0)):
        return self.transport.open_channel("direct-tcpip", (host, int(port)), (origin[0], int(origin[1])), timeout=15)

    # --------------------------------------------------------------- remote
    def _start_remote(self) -> None:
        self.bound_port = _RemoteDispatcher.get(self.transport).add(self)

    def serve_remote(self, chan: paramiko.Channel) -> None:
        try:
            sock = socket.create_connection((self.fwd.dest_host, int(self.fwd.dest_port)), timeout=15)
            sock.settimeout(None)
        except Exception:
            chan.close()
            return
        self._count(+1)
        try:
            _pump(sock, chan)
        finally:
            self._count(-1)

    def _count(self, d: int) -> None:
        with self._lock:
            self.active += d
            if d > 0:
                self.total += 1
        self.on_change()


class _RemoteDispatcher:
    """paramiko keeps one handler per transport for server-side (-R) forwards, so route by the server port."""

    def __init__(self, transport: paramiko.Transport):
        self.transport = transport
        self.by_port: dict[int, ForwardRunner] = {}
        self.lock = threading.Lock()

    @classmethod
    def get(cls, transport: paramiko.Transport) -> "_RemoteDispatcher":
        d = getattr(transport, "_jh_remote_dispatcher", None)
        if d is None:
            d = cls(transport)
            transport._jh_remote_dispatcher = d
        return d

    def add(self, runner: ForwardRunner) -> int:
        f = runner.fwd
        port = self.transport.request_port_forward(f.bind_host or "localhost", int(f.bind_port), handler=self._handle)
        with self.lock:
            self.by_port[int(port)] = runner
        return int(port)

    def remove(self, runner: ForwardRunner) -> None:
        with self.lock:
            ports = [p for p, r in self.by_port.items() if r is runner]
            for p in ports:
                del self.by_port[p]
        for p in ports:
            try:
                # Not cancel_port_forward(): that also drops the handler other remote forwards still use
                self.transport.global_request("cancel-tcpip-forward", (runner.fwd.bind_host or "localhost", p), wait=True)
            except Exception:
                pass

    def _handle(self, chan, origin, server) -> None:
        with self.lock:
            runner = self.by_port.get(int(server[1]))
        if runner is None or not runner.running:
            chan.close()
            return
        threading.Thread(target=runner.serve_remote, args=(chan,), daemon=True).start()


# ------------------------------------------------------------------- SOCKS
def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        part = sock.recv(n - len(buf))
        if not part:
            raise ConnectionError("SOCKS client closed")
        buf += part
    return buf


def _recv_until_nul(sock: socket.socket, limit: int = 512) -> bytes:
    buf = b""
    while len(buf) < limit:
        c = _recv_exact(sock, 1)
        if c == b"\0":
            return buf
        buf += c
    raise ConnectionError("SOCKS field too long")


def _socks_handshake(client: socket.socket, open_channel):
    """Run the SOCKS4/4a/5 CONNECT handshake. Returns the SSH channel, or None after replying with an error."""
    client.settimeout(30)
    ver = _recv_exact(client, 1)[0]
    if ver == 5:
        n = _recv_exact(client, 1)[0]
        methods = _recv_exact(client, n)
        if 0 not in methods:
            client.sendall(b"\x05\xff")
            return None
        client.sendall(b"\x05\x00")
        _v, cmd, _rsv, atyp = _recv_exact(client, 4)
        if atyp == 1:
            host = socket.inet_ntoa(_recv_exact(client, 4))
        elif atyp == 3:
            host = _recv_exact(client, _recv_exact(client, 1)[0]).decode("ascii", "replace")
        elif atyp == 4:
            host = str(ipaddress.IPv6Address(_recv_exact(client, 16)))
        else:
            client.sendall(b"\x05\x08\x00\x01" + b"\0" * 6)
            return None
        port = struct.unpack(">H", _recv_exact(client, 2))[0]
        if cmd != 1:          # only CONNECT
            client.sendall(b"\x05\x07\x00\x01" + b"\0" * 6)
            return None
        try:
            chan = open_channel(host, port)
        except Exception:
            client.sendall(b"\x05\x05\x00\x01" + b"\0" * 6)
            return None
        client.sendall(b"\x05\x00\x00\x01" + b"\0" * 6)
        client.settimeout(None)
        return chan
    if ver == 4:
        cmd = _recv_exact(client, 1)[0]
        port = struct.unpack(">H", _recv_exact(client, 2))[0]
        ip = _recv_exact(client, 4)
        _recv_until_nul(client)                      # user id
        if ip[:3] == b"\0\0\0" and ip[3] != 0:       # SOCKS4a: host name follows
            host = _recv_until_nul(client).decode("ascii", "replace")
        else:
            host = socket.inet_ntoa(ip)
        if cmd != 1:
            client.sendall(b"\x00\x5b" + b"\0" * 6)
            return None
        try:
            chan = open_channel(host, port)
        except Exception:
            client.sendall(b"\x00\x5b" + b"\0" * 6)
            return None
        client.sendall(b"\x00\x5a" + b"\0" * 6)
        client.settimeout(None)
        return chan
    return None


def _describe_error(e: Exception) -> str:
    if isinstance(e, OSError) and getattr(e, "winerror", None) in (10048, 10013) or \
            isinstance(e, OSError) and e.errno in (48, 98, 13):
        return "port-in-use"
    if isinstance(e, paramiko.SSHException) and "forward" in str(e).lower():
        return "server-refused"
    return f"{type(e).__name__}: {e}"


def start_all(forwards: list[dict], transport: paramiko.Transport,
              on_change: Callable[[], None] | None = None) -> list[ForwardRunner]:
    runners = []
    for d in forwards:
        f = Forward.from_dict(d)
        if f.validate():
            continue
        r = ForwardRunner(f, transport, on_change)
        r.start()
        runners.append(r)
    return runners
