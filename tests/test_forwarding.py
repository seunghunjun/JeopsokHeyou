# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Port forwarding (local, remote, dynamic SOCKS4/4a/5) through an in-process SSH server."""
import os
import socket
import struct
import sys
import threading
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
os.environ["APPDATA"] = os.path.join(TESTS, ".work", "appdata-forwarding")
sys.path.insert(0, os.path.dirname(TESTS))
import paramiko  # noqa: E402

from jeopsokheyou.forwarding import Forward, ForwardRunner  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---------------------------------------------------------------- an echo service on this PC
def echo_server() -> int:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)

    def serve(c):
        try:
            while True:
                d = c.recv(4096)
                if not d:
                    break
                c.sendall(b"echo:" + d)
        except OSError:
            pass
        c.close()

    def loop():
        while True:
            c, _ = srv.accept()
            threading.Thread(target=serve, args=(c,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1]


ECHO = echo_server()


# ---------------------------------------------------------------- minimal SSH server with forwarding
class Server(paramiko.ServerInterface):
    def __init__(self, transport):
        self.transport = transport
        self.listeners = {}

    def check_auth_password(self, u, p):
        return paramiko.AUTH_SUCCESSFUL if p == "pw" else paramiko.AUTH_FAILED

    def get_allowed_auths(self, u):
        return "password"

    def check_channel_request(self, kind, cid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_direct_tcpip_request(self, chanid, origin, destination):
        self.pending = destination
        return paramiko.OPEN_SUCCEEDED if destination[0] != "refuse.invalid" else \
            paramiko.OPEN_FAILED_CONNECT_FAILED

    def check_port_forward_request(self, address, port):
        srv = socket.socket()
        srv.bind(("127.0.0.1", port))
        srv.listen(8)
        bound = srv.getsockname()[1]
        self.listeners[bound] = srv

        def loop():
            while True:
                try:
                    c, addr = srv.accept()
                except OSError:
                    return
                ch = self.transport.open_forwarded_tcpip_channel(addr, (address, bound))
                threading.Thread(target=bridge, args=(c, ch), daemon=True).start()

        threading.Thread(target=loop, daemon=True).start()
        return bound

    def cancel_port_forward_request(self, address, port):
        srv = self.listeners.pop(port, None)
        if srv:
            srv.close()


def bridge(a, b):
    def one(x, y):
        try:
            while True:
                d = x.recv(4096)
                if not d:
                    break
                y.sendall(d)
        except Exception:
            pass
        for z in (x, y):
            try:
                z.close()
            except Exception:
                pass
    threading.Thread(target=one, args=(a, b), daemon=True).start()
    one(b, a)


HOST_KEY = paramiko.RSAKey.generate(2048)
SSH_PORT = free_port()


def ssh_server():
    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", SSH_PORT))
    ls.listen(4)
    while True:
        c, _ = ls.accept()
        t = paramiko.Transport(c)
        t.add_server_key(HOST_KEY)
        srv = Server(t)
        t.start_server(server=srv)

        def accept_loop(t=t, srv=srv):
            while t.is_active():
                ch = t.accept(1)
                if ch is None:
                    continue
                host, port = srv.pending
                try:
                    s = socket.create_connection((host, port), timeout=5)
                except OSError:
                    ch.close()
                    continue
                threading.Thread(target=bridge, args=(s, ch), daemon=True).start()

        threading.Thread(target=accept_loop, daemon=True).start()


threading.Thread(target=ssh_server, daemon=True).start()
time.sleep(0.3)
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("127.0.0.1", SSH_PORT, "tester", "pw", allow_agent=False, look_for_keys=False)
transport = client.get_transport()


def roundtrip(sock, payload=b"hi"):
    sock.sendall(payload)
    sock.settimeout(5)
    return sock.recv(100)


# ---------------------------------------------------------------- local
changes = []
lp = free_port()
local = ForwardRunner(Forward("L", "127.0.0.1", lp, "127.0.0.1", ECHO), transport, lambda: changes.append(1))
check("local forward starts", local.start(), local.error)
c = socket.create_connection(("127.0.0.1", lp))
check("local forward carries data", roundtrip(c) == b"echo:hi")
time.sleep(0.2)
check("active connection counted", local.active == 1 and local.total == 1, (local.active, local.total))
c.close()
time.sleep(0.5)
check("closed connection uncounted", local.active == 0, local.active)
check("status callback fired", len(changes) >= 3)
busy = ForwardRunner(Forward("L", "127.0.0.1", lp, "127.0.0.1", ECHO), transport)
check("port already in use is reported", not busy.start() and busy.error == "port-in-use", busy.error)
local.stop()
time.sleep(0.2)
try:
    socket.create_connection(("127.0.0.1", lp), timeout=1).close()
    stopped = False
except OSError:
    stopped = True
check("stopped local forward no longer listens", stopped)

# ---------------------------------------------------------------- dynamic (SOCKS)
dp = free_port()
dyn = ForwardRunner(Forward("D", "127.0.0.1", dp), transport)
check("dynamic forward starts", dyn.start(), dyn.error)
s5 = socket.create_connection(("127.0.0.1", dp))
s5.sendall(b"\x05\x01\x00")
check("SOCKS5 greeting", s5.recv(2) == b"\x05\x00")
s5.sendall(b"\x05\x01\x00\x03" + bytes([9]) + b"localhost" + struct.pack(">H", ECHO))
check("SOCKS5 connect by name", s5.recv(10)[:2] == b"\x05\x00")
check("SOCKS5 data", roundtrip(s5) == b"echo:hi")
s5.close()
s5 = socket.create_connection(("127.0.0.1", dp))
s5.sendall(b"\x05\x01\x00")
s5.recv(2)
s5.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack(">H", ECHO))
check("SOCKS5 connect by IPv4", s5.recv(10)[:2] == b"\x05\x00" and roundtrip(s5, b"v4") == b"echo:v4")
s5.close()
s4 = socket.create_connection(("127.0.0.1", dp))
s4.sendall(b"\x04\x01" + struct.pack(">H", ECHO) + socket.inet_aton("127.0.0.1") + b"user\0")
check("SOCKS4 connect", s4.recv(8)[:2] == b"\x00\x5a" and roundtrip(s4, b"4") == b"echo:4")
s4.close()
s4a = socket.create_connection(("127.0.0.1", dp))
s4a.sendall(b"\x04\x01" + struct.pack(">H", ECHO) + b"\0\0\0\x01" + b"\0" + b"localhost\0")
check("SOCKS4a connect by name", s4a.recv(8)[:2] == b"\x00\x5a" and roundtrip(s4a, b"4a") == b"echo:4a")
s4a.close()
bad = socket.create_connection(("127.0.0.1", dp))
bad.sendall(b"\x05\x01\x00")
bad.recv(2)
bad.sendall(b"\x05\x01\x00\x03" + bytes([14]) + b"refuse.invalid" + struct.pack(">H", 1))
check("SOCKS5 failure is reported to the client", bad.recv(10)[:2] == b"\x05\x05")
bad.close()
dyn.stop()

# ---------------------------------------------------------------- remote
r1 = ForwardRunner(Forward("R", "localhost", 0, "127.0.0.1", ECHO), transport)
r2 = ForwardRunner(Forward("R", "localhost", 0, "127.0.0.1", ECHO), transport)
check("remote forwards start", r1.start() and r2.start(), (r1.error, r2.error))
check("server assigned ports", r1.bound_port > 0 and r2.bound_port > 0 and r1.bound_port != r2.bound_port)
time.sleep(0.2)
rc = socket.create_connection(("127.0.0.1", r1.bound_port))
check("remote forward carries data back to this PC", roundtrip(rc, b"r") == b"echo:r")
rc.close()
r1.stop()
time.sleep(0.3)
rc = socket.create_connection(("127.0.0.1", r2.bound_port))
check("stopping one remote forward keeps the other", roundtrip(rc, b"r2") == b"echo:r2")
rc.close()
r2.stop()

# ---------------------------------------------------------------- validation / text
check("validation", Forward("L", "127.0.0.1", 0).validate() != "" and Forward("D", "127.0.0.1", 1080).validate() == ""
      and Forward("L", "127.0.0.1", 80).validate() != "")
check("describe", Forward("L", "::1", 8080, "db", 5432).describe() == "L  [::1]:8080 → db:5432")
client.close()
print("DONE")
