# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Jump hosts, forwards opened with a session, and saved tunnels (start/stop/auto-reconnect) in the real UI."""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata-tunnels")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
root = os.path.join(SP, "srvroot-tunnels")
os.makedirs(root, exist_ok=True)
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, os.path.dirname(TESTS))
from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.forwarding import Forward  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme  # noqa: E402
from jeopsokheyou.tunnels import Tunnel, TunnelsPage  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def wait(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# echo service on this PC, reached through the SSH server
echo = socket.socket()
echo.bind(("127.0.0.1", 0))
echo.listen(8)
ECHO = echo.getsockname()[1]


def echo_loop():
    while True:
        c, _ = echo.accept()

        def serve(c=c):
            try:
                while True:
                    d = c.recv(4096)
                    if not d:
                        break
                    c.sendall(b"echo:" + d)
            except OSError:
                pass
            c.close()
        threading.Thread(target=serve, daemon=True).start()


threading.Thread(target=echo_loop, daemon=True).start()


def through(port, payload=b"ping"):
    result = {}

    def run():
        try:
            c = socket.create_connection(("127.0.0.1", port), timeout=5)
            c.sendall(payload)
            result["data"] = c.recv(100)
            c.close()
        except OSError as e:
            result["data"] = repr(e)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    wait(lambda: not t.is_alive(), 8)
    return result.get("data")


apply_dark_theme(app)
w = MainWindow()
w.resize(1200, 700)
w.show()

# ---------------------------------------------------------------- jump host + session forwards
jump = Session(host="127.0.0.1", port=2299, user="tester", name="bastion", group="Testing")
jump.password = "pw"
w.store.upsert(jump)
lp = free_port()
target = Session(host="127.0.0.1", port=2299, user="tester", name="inner", group="Testing", jump=jump.id,
                 forwards=[Forward("L", "127.0.0.1", lp, "127.0.0.1", ECHO).to_dict(),
                           Forward("L", "127.0.0.1", lp, "127.0.0.1", ECHO).to_dict()])   # 2nd one: port in use
w.store.upsert(target)
w.reload_sessions()
w.open_session(target, "pw")
tab = w.current_tab()
check("connected through the jump host", wait(lambda: tab.state == "connected"), tab.state)
check("one jump client in the chain", len(tab.conn._jump_clients) == 1)
wait(lambda: False, 0.3)
check("session forward is open", len(tab.forward_runners) == 2 and tab.forward_runners[0].running)
check("second forward reports the busy port", not tab.forward_runners[1].running
      and tab.forward_runners[1].error == "port-in-use", tab.forward_runners[1].error)
check("data flows through the session forward", through(lp) == b"echo:ping")
tab.panes[0].send_text("exit\r")
check("disconnect closes the session forwards", wait(lambda: tab.state == "closed") and not tab.forward_runners)
try:
    socket.create_connection(("127.0.0.1", lp), timeout=1).close()
    still = True
except OSError:
    still = False
check("port released after disconnect", not still)

# ---------------------------------------------------------------- saved tunnel
tp = free_port()
t = Tunnel(name="echo tunnel", session_id=jump.id, forward=Forward("L", "127.0.0.1", tp, "127.0.0.1", ECHO).to_dict())
w.tunnels.upsert(t)
page = TunnelsPage(w.tunnels)
check("tunnel listed on the page", page.table.rowCount() == 1 and page.table.item(0, 0).text() == "echo tunnel")
w.tunnels.start(t.id)
runner = w.tunnels.runners[t.id]
check("tunnel runs without a terminal", wait(lambda: runner.state == "running"), runner.state + " " + runner.error)
check("data flows through the tunnel", through(tp, b"t1") == b"echo:t1")
wait(lambda: False, 0.4)
check("page shows the running status", page.table.item(0, 5).text() == runner.status_text(), page.table.item(0, 5).text())
runner.conn.client.close()       # simulate a dropped connection
check("drop detected and reconnecting", wait(lambda: runner.state in ("reconnecting", "connecting"), 8), runner.state)
check("reconnected automatically", wait(lambda: runner.state == "running", 15), runner.state + " " + runner.error)
check("tunnel works after reconnect", through(tp, b"t2") == b"echo:t2")
w.tunnels.stop(t.id)
check("stopped", runner.state == "stopped" and runner.forward is None)

# autostart flag + persistence
t2 = Tunnel.from_dict(dict(t.__dict__))
t2.autostart = True
w.tunnels.upsert(t2)
from jeopsokheyou.tunnels import TunnelStore  # noqa: E402
check("tunnels saved to disk", TunnelStore().get(t.id).autostart is True)
w.tunnels.autostart()
check("autostart starts flagged tunnels", wait(lambda: w.tunnels.runners[t.id].state == "running"))
w.tunnels.stop_all()
check("stop all", all(r.state == "stopped" for r in w.tunnels.runners.values()))

# a deleted session is reported, not crashed on
w.store.remove(jump.id)
w.tunnels.start(t.id)
check("deleted session reported", w.tunnels.runners[t.id].state == "error")
check("jump reference cleared when its session is deleted", w.store.get(target.id).jump == "")

w.close()
stop_server(srv)
print("DONE")
