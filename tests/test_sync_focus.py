# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Explorer and terminal stay together after coming back from another program:
- a listing for an older move (the explorer following the terminal) arriving late does not undo a double-click,
- the same terminal getting the focus back does not pull the explorer to the terminal's (older) folder,
- going back to where the terminal is while its cd is still on the way sends it back there afterwards,
- the reason the terminal was not moved stays readable below the list."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "sync_focus")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = os.path.join(SP, "srv")
for d in ("home/tester/app/conf", "home/tester/logs", "etc"):
    os.makedirs(os.path.join(root, d))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from _util import stop_server  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402


def check(name, ok, extra=""):
    if callable(extra):                  # details computed (and printed) only when the check fails
        extra = "" if ok else extra()
    print(("PASS " if ok else "FAIL ") + name, extra)


def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


def settle(sec=1.0):
    wait(lambda: False, sec)


srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
try:
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    s = Session(host="127.0.0.1", port=2299, user="tester", name="sync")
    w.store.upsert(s)
    w.open_session(s, "pw")
    tab = w.current_tab()
    ex, pane = tab.explorer, tab.panes[0]
    check("ready", wait(lambda: pane.cwd == "/home/tester" and ex.cwd == "/home/tester"
                        and pane._inject_state == "done", 20))
    pane.focused.emit(pane)              # the terminal had the focus before the user went to another program
    settle(0.5)

    def state():
        return ex.cwd, pane.cwd, pane._pending_cd, pane._late_cd, ex.info.text()

    # ---- a listing still on its way for an older move must not undo a double-click
    ex.follow("/etc", from_terminal=False)       # e.g. another pane picked: its listing is queued
    ex._on_double(ex._find_item("/home/tester/logs"), 0)
    settle(2.0)
    check("a late listing does not take the explorer back after a double-click",
          ex.cwd == "/home/tester/logs" and pane.cwd == "/home/tester/logs", state)

    ex.navigate("/home/tester")
    wait(lambda: pane.cwd == "/home/tester" and ex.cwd == "/home/tester", 5)
    settle(0.5)

    # ---- the terminal can't follow (something typed): the reason stays readable, focus back keeps the explorer
    pane._note_user_input("\x1b[A")              # Up arrow at the prompt: no new prompt report comes
    ex._on_double(ex._find_item("/home/tester/app"), 0)
    settle(1.0)
    check("the reason the terminal stayed is still shown after the listing",
          "being typed" in ex.info.text() and ex.cwd == "/home/tester/app", state)
    pane.focused.emit(pane)                      # back from another program: the same terminal gets the focus
    settle(1.0)
    check("the same terminal getting the focus back does not pull the explorer back", ex.cwd == "/home/tester/app",
          state)
    pane.input_dirty = False

    # ---- back to where the terminal is while its cd is still on the way
    ex.navigate("/home/tester")
    wait(lambda: ex.cwd == "/home/tester", 5)
    wait(lambda: pane.cwd == "/home/tester", 5)
    settle(0.5)
    pane._hiding = "cd"                          # the app's cd is still on its way (simulated)
    first = pane.sync_cd("/home/tester/logs")
    back = pane.sync_cd("/home/tester")
    check("going back while a cd is on its way: the way back is queued (not dropped)",
          first == "queued" and back == "queued" and pane._pending_cd == "/home/tester", state)
    pane._hiding = None
    w.settings["confirm_quit"] = False
    w.close()
finally:
    stop_server(srv)
print("DONE")
