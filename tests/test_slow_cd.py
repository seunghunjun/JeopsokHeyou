# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""A shell slow to answer the explorer's cd (longer than the app waits): the explorer stays where the user
went and the terminal ends up there too — the late answer never pulls the explorer back."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "slow_cd")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = os.path.join(SP, "srvroot")
for d in ("home/tester/app/conf", "home/tester/logs", "etc"):
    os.makedirs(os.path.join(root, d))
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


env = dict(os.environ, FAKE_CD_DELAY="3")      # longer than the 2 s the app waits for the hidden cd
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE,
                       env=env)
srv.stdout.readline()
try:
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    s = Session(host="127.0.0.1", port=2299, user="tester", name="slowcd")
    w.store.upsert(s)
    w.open_session(s, "pw")
    tab = w.current_tab()
    ex, pane = tab.explorer, tab.panes[0]
    check("connected, terminal reports its folder", wait(lambda: pane.cwd == "/home/tester" and ex.cwd == "/home/tester"
                                                         and pane._inject_state == "done", 20), pane.cwd)
    ex.navigate("/home/tester/app")
    wait(lambda: ex.cwd == "/home/tester/app")
    ex.navigate("/home/tester/logs")              # while the shell is still busy with the first cd
    check("explorer moved", wait(lambda: ex.cwd == "/home/tester/logs"))
    pane.focused.emit(pane)                       # clicking the terminal while it is still catching up
    check("focusing the terminal on its way doesn't pull the explorer back", wait(lambda: False, 0.3) or
          ex.cwd == "/home/tester/logs", ex.cwd)
    check("the terminal ends up there too", wait(lambda: pane.cwd == "/home/tester/logs", 20), pane.cwd)
    wait(lambda: False, 2)
    check("the late answers never pulled the explorer back", ex.cwd == "/home/tester/logs", ex.cwd)
    # an earlier report arriving right after our cd is not taken as its answer
    import time as _t
    pane._cd_expect = ("/home/tester/app", _t.monotonic())
    tab._pane_cwd(pane, "/home/tester")
    check("a late, earlier report doesn't move the explorer", wait(lambda: False, 0.3) or ex.cwd == "/home/tester/logs",
          ex.cwd)
    tab._pane_cwd(pane, "/home/tester/app")
    check("the cd's own answer is followed", wait(lambda: ex.cwd == "/home/tester/app", 10) and pane._cd_expect is None,
          ex.cwd)
    w.settings["confirm_quit"] = False
    w.close()
finally:
    stop_server(srv)
print("DONE")
