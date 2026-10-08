# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Quick connect: asks the user before the password, offers an already saved host, and saves a new host
once the login works (no duplicates)."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "quick")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
root = os.path.join(SP, "srv")
os.makedirs(os.path.join(root, "home", "tester"), exist_ok=True)

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)   # trust the test host key
from _util import stop_server  # noqa: E402
from jeopsokheyou import dialogs  # noqa: E402
from jeopsokheyou.config import Session, SessionStore  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402


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


asked: list[str] = []
QInputDialog.getText = staticmethod(lambda *a, **k: (asked.append("user") or "tester", True))
real_ask = dialogs.ask_password_saving


def fake_password(parent, label, s, store=None):
    asked.append("password")
    return "pw"


dialogs.ask_password_saving = fake_password

srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
try:
    w = MainWindow()
    w.show()

    # new host, no user typed: user first, then password; saved after login
    s = Session.parse_quick("127.0.0.1:2299")
    w.open_quick(s)
    tab = w.current_tab()
    check("connected", wait(lambda: tab.state == "connected"))
    check("asks the user before the password", asked == ["user", "password"], asked)
    saved = [x for x in w.store.sessions if x.host == "127.0.0.1" and x.port == 2299]
    check("new host saved after the login worked", len(saved) == 1 and saved[0].user == "tester")
    check("... with its password (encrypted)", saved[0].password == "pw" and saved[0].password_enc
          and "\"pw\"" not in w.store.path.read_text(encoding="utf-8"))
    w.show_home("hosts")
    w.home.hosts.open_group("")
    check("... and shown in the host list", wait(lambda: saved[0].id in w.home.hosts.cards))
    check("... kept on disk", any(x.host == "127.0.0.1" for x in SessionStore(w.store.path).sessions))

    # the same target again: offer the saved host
    shown = []

    def fake_exec(box):
        shown.append(box.text())
        box_buttons = {b.text(): b for b in box.buttons()}
        next(b for t, b in box_buttons.items() if t == "Use the saved host").click()
        return 0

    real_exec = QMessageBox.exec
    QMessageBox.exec = fake_exec
    asked.clear()
    w.open_quick(Session.parse_quick("tester@127.0.0.1:2299"))
    t2 = w.current_tab()
    check("saved host offered", shown and "already saved" in shown[0], shown)
    check("connects with the saved host (saved password, no prompts)", t2.session.id == saved[0].id
          and wait(lambda: t2.state == "connected") and asked == [], asked)
    check("no duplicate saved", len([x for x in w.store.sessions if x.host == "127.0.0.1"]) == 1)

    # "Connect without it": a new connection, still no duplicate saved
    def fake_exec_new(box):
        next(b for b in box.buttons() if b.text() == "Connect without it").click()
        return 0

    QMessageBox.exec = fake_exec_new
    w.open_quick(Session.parse_quick("tester@127.0.0.1:2299"))
    t3 = w.current_tab()
    check("connect without the saved host", t3.session.id != saved[0].id and wait(lambda: t3.state == "connected"))
    check("still no duplicate", len([x for x in w.store.sessions if x.host == "127.0.0.1"]) == 1)
    QMessageBox.exec = real_exec

    # a different user on the same host is a different saved host
    check("match needs the same user when one is typed",
          w.saved_matches(Session.parse_quick("other@127.0.0.1:2299")) == []
          and len(w.saved_matches(Session.parse_quick("127.0.0.1:2299"))) == 1)
    w.close()
finally:
    dialogs.ask_password_saving = real_ask
    stop_server(srv)
print("DONE")
