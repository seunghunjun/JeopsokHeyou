# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys, time, subprocess, shutil
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")   # test work folder (git-ignored)
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata"); shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
root = os.path.join(SP, "srvroot")
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou.mainwindow import MainWindow, SessionTab
from jeopsokheyou.config import Session
from jeopsokheyou.explorer import job_simple
w = MainWindow(); w.resize(1200, 700); w.show()

def wait(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
        if cond(): return True
    return False

def check(n, ok, x=""): print(("PASS " if ok else "FAIL ") + n, x)

# Session vs. global setting precedence
s = Session(host="127.0.0.1", port=2299, user="tester", name="idle")
w.open_session(s, "pw"); tab = w.current_tab()
check("default 30 min", tab.idle_limit() == 30 * 60)
s.idle_minutes = 0; check("session 'never' wins", tab.idle_limit() == 0)
s.idle_minutes = 10; check("session 10 min wins", tab.idle_limit() == 600)
s.idle_minutes = -1; w.settings["idle_minutes"] = 60; check("follows global setting", tab.idle_limit() == 3600)

LIMIT = 6   # 6 s for the test (warning 3 s before)
SessionTab.idle_limit = lambda self: LIMIT
wait(lambda: tab.state == "connected" and tab.panes[0]._inject_state == "done", 15)
tab.split_pane(Qt.Orientation.Horizontal); wait(lambda: tab.panes[-1]._inject_state == "done", 15)
tab.touch()

check("warning banner shown", wait(lambda: tab.idle_banner.isVisible(), 6)
      and tab.idle_label.text().startswith("Idle — disconnecting in"), tab.idle_label.text())
app.sendEvent(tab.panes[0], QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, "a"))
wait(lambda: False, 0.2)
check("key press -> banner hidden and time extended", not tab.idle_banner.isVisible() and tab.state == "connected")

wait(lambda: tab.idle_banner.isVisible(), 6)
QTest.mouseClick(tab.explorer.tree.viewport(), Qt.MouseButton.LeftButton)
wait(lambda: False, 0.2)
check("explorer click also counts as activity", not tab.idle_banner.isVisible() and tab.state == "connected")

# No disconnect while a file transfer is running
tab.explorer.transfer.submit("slow", job_simple(lambda sftp: time.sleep(9)))
wait(lambda: False, 8)
check("kept alive during transfer", tab.state == "connected" and not tab.idle_banner.isVisible())
wait(lambda: not tab.explorer.transfer_active(), 5); tab.touch()

# Timeout -> disconnect
check("timeout -> auto disconnect", wait(lambda: tab.state == "closed", 10), tab.state)
disp = "\n".join(tab.panes[0].screen.display)
check("split panes cleaned up", len(tab.panes) == 1, len(tab.panes))
flat = "".join(l.rstrip() for l in tab.panes[0].screen.display)
check("notice text", "Disconnected automatically" in flat, [l.rstrip() for l in tab.panes[0].screen.display if l.strip()][-4:])
check("explorer shows disconnected too", tab.explorer.info.text() == "Disconnected")

# Reconnect
app.sendEvent(tab.panes[0], QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\r"))
check("Enter -> reconnect", wait(lambda: tab.state == "connected", 10))
check("timer reset after reconnect", not tab.idle_banner.isVisible())

# 'Never' -> no disconnect
SessionTab.idle_limit = lambda self: 0
wait(lambda: False, 8)
check("never -> kept alive", tab.state == "connected")

# Settings dialog save
from jeopsokheyou.dialogs import SettingsDialog, SessionDialog
d = SettingsDialog(w.settings, w.term_font, w); d.idle.setCurrentIndex(d.idle.findData(10))
check("settings dialog value", d.values()["idle_minutes"] == 10); d.reject()
sd = SessionDialog(Session(host="h", idle_minutes=60), [], w)
check("session editor shows value", sd.idle.currentData() == 60)
sd.idle.setCurrentIndex(sd.idle.findData(-1)); sd.host.setText("h"); sd._accept()
check("session editor saves value", sd.session.idle_minutes == -1)
w.close(); stop_server(srv)
print("DONE")
