# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Closing the main window asks first while connections are open (Cancel keeps everything running)."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "confirm_quit")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = os.path.join(SP, "srv")
os.makedirs(os.path.join(root, "home", "tester"))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
from _util import stop_server  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402

asked = []
answer = [QMessageBox.StandardButton.Cancel]


def question(parent, title, text, *a, **k):
    if "host key" in text:                  # trust the test server
        return QMessageBox.StandardButton.Yes
    asked.append(text)
    return answer[0]


QMessageBox.question = staticmethod(question)


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


# nothing open: closes right away
w0 = MainWindow()
w0.show()
w0.close()
check("no connection: closes without asking", not asked and not w0.isVisible())

srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
try:
    w = MainWindow()
    w.show()
    tabs = []
    for name in ("one", "two"):
        s = Session(host="127.0.0.1", port=2299, user="tester", name=name)
        w.store.upsert(s)
        w.open_session(s, "pw")
        tabs.append(w.current_tab())
    check("connected", wait(lambda: all(t.state == "connected" for t in tabs), 15))
    w.float_tab(tabs[1], QPoint(300, 120))
    app.processEvents()

    w.close()
    check("asks before quitting", len(asked) == 1, asked)
    check("... telling what ends", "2 open connection(s)" in asked[0] and "1 separate window(s)" in asked[0], asked[0])
    check("Cancel keeps everything running", w.isVisible() and all(t.state == "connected" for t in tabs)
          and len(w.tab_windows) == 1)

    w.settings["confirm_quit"] = False
    w.close()
    check("Settings can turn the question off", len(asked) == 1 and not w.isVisible())
    check("quitting ends the separate windows too", wait(lambda: not w.tab_windows))

    w2 = MainWindow()
    w2.settings["confirm_quit"] = True     # the window above saved it off
    w2.show()
    s = Session(host="127.0.0.1", port=2299, user="tester", name="three")
    w2.store.upsert(s)
    w2.open_session(s, "pw")
    t3 = w2.current_tab()
    wait(lambda: t3.state == "connected", 15)
    answer[0] = QMessageBox.StandardButton.Yes
    w2.close()
    check("Yes quits", len(asked) == 2 and not w2.isVisible() and "1 open connection(s)" in asked[1], asked[-1:])
finally:
    stop_server(srv)
print("DONE")
