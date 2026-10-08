# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""A server slow to show its first prompt: folders opened in the explorer meanwhile are kept, and the
shell's late reports of its starting folder never pull the explorer back."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "slow_shell")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = os.path.join(SP, "srvroot")
os.makedirs(os.path.join(root, "home/tester/app/conf"))
os.makedirs(os.path.join(root, "etc"))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)

from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402


def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


env = dict(os.environ, FAKE_SHELL_DELAY="7")   # past the 3 s hook wait + 2 s echo wait
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE,
                       env=env)
srv.stdout.readline()
try:
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    s = Session(host="127.0.0.1", port=2299, user="tester", name="slow")
    w.store.upsert(s)
    w.open_session(s, "pw")
    tab = w.current_tab()
    ex = tab.explorer
    check("explorer ready before the shell", wait(lambda: ex.cwd == "/home/tester" and ex.item_count() > 0, 15)
          and not tab.active.cwd, tab.active.cwd)
    # move twice in the explorer while the shell has not shown its prompt yet
    ex.navigate("/home/tester/app")
    wait(lambda: ex.cwd == "/home/tester/app")
    ex.navigate("/etc")
    check("explorer moved", wait(lambda: ex.cwd == "/etc"))
    check("the terminal catches up with the last move", wait(lambda: tab.active.cwd == "/etc", 15), tab.active.cwd)
    wait(lambda: False, 1.5)
    check("the explorer was not pulled back to the shell's first folder", ex.cwd == "/etc", ex.cwd)
    # afterwards the terminal leads again
    tab.active.chan.sendall(b"cd /home/tester/app/conf\r")
    check("then the explorer follows the terminal as before", wait(lambda: ex.cwd == "/home/tester/app/conf"), ex.cwd)
    w.close()
finally:
    stop_server(srv)
print("DONE")
