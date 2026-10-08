# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Fake SSH server for tests: password "pw", minimal shell (echo + cd/OSC7), SFTP backed by a local folder."""
import os, socket, threading, sys, re, time
import paramiko
from paramiko import SFTPServerInterface, SFTPServer, SFTPAttributes, SFTPHandle, SFTP_OK
ROOT = sys.argv[2]
class Srv(paramiko.ServerInterface):
    def check_auth_password(self, u, p): return paramiko.AUTH_SUCCESSFUL if p == "pw" else paramiko.AUTH_FAILED
    def get_allowed_auths(self, u): return "password"
    def check_channel_request(self, kind, cid): return paramiko.OPEN_SUCCEEDED
    def check_channel_pty_request(self, *a): return True
    def check_channel_shell_request(self, ch):
        threading.Thread(target=shell, args=(ch,), daemon=True).start(); return True
    def check_channel_window_change_request(self, *a): return True
    # Port forwarding: direct-tcpip (-L, -D, jump hosts) and tcpip-forward (-R)
    def check_channel_direct_tcpip_request(self, chanid, origin, destination):
        PENDING[chanid] = destination; return paramiko.OPEN_SUCCEEDED
    def check_port_forward_request(self, address, port):
        ls = socket.socket(); ls.bind(("127.0.0.1", port)); ls.listen(8)
        bound = ls.getsockname()[1]; self.listeners[bound] = ls
        def loop():
            while True:
                try: c, addr = ls.accept()
                except OSError: return
                ch = self.transport.open_forwarded_tcpip_channel(addr, (address, bound))
                threading.Thread(target=bridge, args=(c, ch), daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()
        return bound
    def cancel_port_forward_request(self, address, port):
        ls = self.listeners.pop(port, None)
        if ls: ls.close()
PENDING = {}
def bridge(a, b):
    def one(x, y):
        try:
            while True:
                d = x.recv(32768)
                if not d: break
                y.sendall(d)
        except Exception: pass
        for z in (x, y):
            try: z.close()
            except Exception: pass
    threading.Thread(target=one, args=(a, b), daemon=True).start(); one(b, a)
def accept_channels(t):
    while t.is_active():
        ch = t.accept(1)
        if ch is None: continue
        dest = PENDING.pop(ch.get_id(), None)
        if dest is None: continue          # session channels are handled by the shell handler
        try: c = socket.create_connection(dest, timeout=5)
        except OSError: ch.close(); continue
        threading.Thread(target=bridge, args=(c, ch), daemon=True).start()
def shell(ch):
    cwd = "/home/tester"
    time.sleep(float(os.environ.get('FAKE_SHELL_DELAY', '0')))   # a server slow to show its first prompt
    ch.send("Welcome to demo server\r\n$ ")
    buf = ""
    hooked = False
    while True:
        d = ch.recv(4096)
        if not d: break
        out = ""
        for c in d.decode("utf-8", "replace"):
            if c == "\r":
                out += "\r\n"
                line = buf; buf = ""
                if r"\033]7" in line and not hooked:
                    hooked = True; out += f"\x1b]7;{cwd}\x07"
                m = re.match(r"\s*cd(?: --)? '?([^']*)'?$", line)
                if m:
                    t = m.group(1)
                    t = t if t.startswith("/") else os.path.normpath(cwd + "/" + t).replace("\\", "/")
                    if os.path.isdir(os.path.join(ROOT, t.lstrip("/"))): cwd = t
                    else: out += f"bash: cd: {t}: No such file or directory\r\n"
                if line.strip() == "slow":
                    ch.send(out); out = ""; time.sleep(2); out += "done\r\n"
                if line.strip() == "exit": ch.send(out); ch.close(); return
                out += (f"\x1b]7;{cwd}\x07tester:{cwd}$ " if hooked else "$ ")
            elif c == "\x7f":
                if buf: buf = buf[:-1]; out += "\b \b"
            else:
                buf += c; out += c
        if out: ch.send(out)
class H(SFTPHandle):
    def stat(self): return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
class S(SFTPServerInterface):
    def _p(self, p): return os.path.join(ROOT, self.canonicalize(p).lstrip("/"))
    def canonicalize(self, p):
        if not p.startswith("/"): p = "/home/tester/" + ("" if p == "." else p)
        return os.path.normpath(p).replace("\\", "/")
    def list_folder(self, p):
        rp = self._p(p); out=[]
        for f in os.listdir(rp):
            a = SFTPAttributes.from_stat(os.stat(os.path.join(rp, f))); a.filename = f; out.append(a)
        return out
    def stat(self, p): return SFTPAttributes.from_stat(os.stat(self._p(p)))
    lstat = stat
    def open(self, p, flags, attr):
        rp = self._p(p)
        mode = "wb" if flags & (os.O_WRONLY | os.O_RDWR) else "rb"
        f = open(rp, mode); h = H(flags); h.filename = rp; h.readfile = f; h.writefile = f; return h
    def remove(self, p): os.remove(self._p(p)); return SFTP_OK
    def rename(self, a, b): os.rename(self._p(a), self._p(b)); return SFTP_OK
    def mkdir(self, p, attr): os.mkdir(self._p(p)); return SFTP_OK
    def rmdir(self, p): os.rmdir(self._p(p)); return SFTP_OK
def serve(sock, key):
    while True:
        c, _ = sock.accept()
        t = paramiko.Transport(c); t.add_server_key(key)
        t.set_subsystem_handler("sftp", SFTPServer, S)
        srv = Srv(); srv.transport = t; srv.listeners = {}
        t.start_server(server=srv)
        threading.Thread(target=accept_channels, args=(t,), daemon=True).start()
os.makedirs(os.path.join(ROOT, "home/tester/docs"), exist_ok=True)
open(os.path.join(ROOT, "home/tester/hello.txt"), "w", encoding="utf-8").write("hello 日本語\n")
key = paramiko.RSAKey.generate(2048)
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", int(sys.argv[1]))); s.listen(5)
print("ready", flush=True); serve(s, key)
