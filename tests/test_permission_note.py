# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""A server refusing a file operation ("Permission denied"): the message says which account the explorer works as
(su / sudo in the terminal does not change it) and offers to connect to the same server as another account."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "permission_note")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = os.path.join(SP, "srv")
os.makedirs(os.path.join(root, "home", "tester"))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from _util import stop_server  # noqa: E402
from jeopsokheyou import explorer as explorer_mod  # noqa: E402
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


told, plain, opened = [], [], []
answer = [False]


def fake_tell(parent, msg, who):
    told.append((msg, who))
    return answer[0]


explorer_mod.tell_permission = fake_tell
explorer_mod.QMessageBox.warning = staticmethod(lambda parent, title, msg: plain.append(msg))
QInputDialog.getText = staticmethod(lambda *a, **k: ("deploy", True))

srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
try:
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    w.open_session(Session(host="127.0.0.1", port=2299, user="tester", name="perm"), "pw")
    tab = w.current_tab()
    ex = tab.explorer
    check("connected", wait(lambda: tab.state == "connected" and ex.cwd == "/home/tester", 15))
    w.open_quick = lambda s: opened.append(s)
    ex.connect_as_requested.disconnect()
    ex.connect_as_requested.connect(lambda s: w.open_quick(s))

    ex._on_error("move", "PermissionError: [Errno 13] Permission denied")
    check("permission denied: the note names the account the explorer works as",
          told and told[-1][1] == "tester@127.0.0.1" and not plain, lambda: (told, plain))
    check("... closing it opens nothing", not opened)

    answer[0] = True
    ex._on_error("rename", "PermissionError: [Errno 13] Permission denied")
    check("\"Connect as another account\": the same server as the account typed",
          opened and opened[-1].host == "127.0.0.1" and opened[-1].port == 2299 and opened[-1].user == "deploy",
          lambda: [(s.host, s.port, s.user) for s in opened])

    ex._on_error("rename", "OSError: Failure")
    check("other errors: the plain message as before", plain == ["OSError: Failure"], lambda: plain)
    w.settings["confirm_quit"] = False
    w.close()
finally:
    stop_server(srv)
print("DONE")
