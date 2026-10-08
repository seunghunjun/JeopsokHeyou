# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys, time, subprocess, shutil
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")   # test work folder (git-ignored)
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
root = os.path.join(SP, "srvroot")
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QSplitter
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou.mainwindow import MainWindow
from jeopsokheyou.config import Session
w = MainWindow(); w.resize(1300, 700); w.show()

def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
        if cond(): return True
    return False

def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)

w.open_session(Session(host="127.0.0.1", port=2299, user="tester", name="close"), "pw")
tab = w.current_tab()
wait(lambda: tab.state == "connected")
check("single pane: close button shown (it ends the session)", tab.panes[0].close_btn.isVisibleTo(tab.panes[0].frame))
tab.split_pane(Qt.Orientation.Horizontal)
tab.split_pane(Qt.Orientation.Vertical)      # nested split
wait(lambda: all(p._inject_state == "done" for p in tab.panes), 15)
check("3 panes", len(tab.panes) == 3)
check("split: close buttons visible", all(p.close_btn.isVisibleTo(p.frame) for p in tab.panes))

# Close a nested pane with its ✕ button
target = tab.panes[2]; chan = target.chan
QTest.mouseClick(target.close_btn, Qt.MouseButton.LeftButton)
wait(lambda: False, 0.3)
check("✕ click -> pane closed", len(tab.panes) == 2 and target not in tab.panes)
check("shell channel closed too", chan.closed)
nested = [c for c in tab.term_split.findChildren(QSplitter) if c.count() == 0]
check("empty splitters cleaned up", not nested)
check("tab stays open", w.tabs.indexOf(tab) >= 0 and tab.state == "connected")

# Ctrl+Shift+W: while split, closes only the selected pane
tab.active = tab.panes[0]
w.close_pane_or_tab()
wait(lambda: False, 0.3)
check("Ctrl+Shift+W -> only selected pane closed", len(tab.panes) == 1 and w.tabs.indexOf(tab) >= 0)
check("1 pane left -> close button still there", tab.panes[0].close_btn.isVisibleTo(tab.panes[0].frame))
check("remaining pane accepts input", tab.panes[0].at_prompt and not tab.panes[0].disconnected)
tab.panes[0].send_text("cd /home/tester/docs\r"); tab.panes[0]._note_user_input("\r")
check("sync works in remaining pane", wait(lambda: tab.explorer.cwd == "/home/tester/docs"))

# Ctrl+Shift+W on the last pane -> tab closes
w.close_pane_or_tab()
wait(lambda: False, 0.3)
check("last pane -> tab closed", w.tabs.indexOf(tab) < 0)
w.close()
stop_server(srv)
print("DONE")
