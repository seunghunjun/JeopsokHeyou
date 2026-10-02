# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys, time, subprocess, shutil
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")   # test work folder (git-ignored)
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
root = os.path.join(SP, "srvroot")
os.makedirs(os.path.join(root, "home/tester/logs/2026"), exist_ok=True)
os.makedirs(os.path.join(root, "home/tester/docs"), exist_ok=True)
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
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

def screen(p):
    return [l.rstrip() for l in p.screen.display if l.strip()]

def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)

s = Session(host="127.0.0.1", port=2299, user="tester", name="sync")
w.open_session(s, "pw")
tab = w.current_tab(); ex = tab.explorer; p0 = tab.panes[0]
check("connect + hook injection", wait(lambda: p0._inject_state == "done" and p0.at_prompt, 15), screen(p0))

# 1) Explorer -> terminal
ex.navigate("/home/tester/docs")
check("explorer navigate -> terminal cd", wait(lambda: p0.cwd == "/home/tester/docs"), p0.cwd)
wait(lambda: False, 0.3)
sc = screen(p0)
check("cd command line hidden", not any("cd --" in l for l in sc), sc)
check("single prompt line (previous prompt erased)", sum("tester:" in l for l in sc) == 1, sc)

# 2) Terminal -> explorer
p0.send_text("cd /home/tester/logs\r"); p0._note_user_input("\r")
check("terminal cd -> explorer navigates", wait(lambda: ex.cwd == "/home/tester/logs"), ex.cwd)

# 3) Terminal left alone while the user is typing
for ch in "ls -al":
    app.sendEvent(p0, QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, ch))
wait(lambda: False, 0.3)
ex.navigate("/home/tester/docs")
wait(lambda: ex.cwd == "/home/tester/docs")
wait(lambda: False, 0.5)
check("typing -> terminal unchanged", p0.cwd == "/home/tester/logs" and "A command is being typed" in ex.info.text(),
      f"{p0.cwd} | info={ex.info.text()}")
for _ in range(6):
    app.sendEvent(p0, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier, ""))
app.sendEvent(p0, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\r"))
wait(lambda: p0.at_prompt)

# 4) Terminal left alone while a command is running
for ch in "slow":
    app.sendEvent(p0, QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, ch))
app.sendEvent(p0, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\r"))
wait(lambda: False, 0.3)
ex.navigate("/home/tester")
wait(lambda: ex.cwd == "/home/tester")
check("running -> terminal unchanged", "A command is running" in ex.info.text(), ex.info.text())
wait(lambda: p0.at_prompt, 5)
check("running command output preserved", any("done" in l for l in screen(p0)), screen(p0)[-3:])

# 5) Rapid clicks -> ends at the last location
ex.navigate("/home/tester/logs"); ex.navigate("/home/tester/logs/2026")
check("rapid navigation -> final location", wait(lambda: p0.cwd == "/home/tester/logs/2026" and ex.cwd == "/home/tester/logs/2026"),
      f"{p0.cwd} / {ex.cwd}")
wait(lambda: False, 0.5)
check("cd lines hidden during rapid navigation", not any("cd --" in l for l in screen(p0)), screen(p0))

# 6) Back / up
ex.go_up()
check("parent folder -> terminal", wait(lambda: p0.cwd == "/home/tester/logs"), p0.cwd)

# 7) Split view: clicking another terminal moves the explorer to its location
before_split = screen(p0)   # remember the text so we can check nothing was lost to a transient narrow size
tab.split_pane(Qt.Orientation.Horizontal); p1 = tab.panes[1]
wait(lambda: p1._inject_state == "done" and p1.at_prompt, 15)
check("new split pane starts at home", p1.cwd == "/home/tester", p1.cwd)
wait(lambda: False, 0.5)
# Nothing may be lost while the splitter is laid out: long lines are re-wrapped (reflow), not cut.
def all_text(p):
    s = p.screen
    rows = list(s.scrollback) + [s.buffer[y] for y in range(s.lines)]
    return "".join("".join(r[x].data for x in range(s.columns)) for r in rows)
squash = lambda t: "".join(t.split())
expected = squash("".join(l for l in before_split if l.strip()))
check("existing screen content kept after split (re-wrapped, nothing lost)", expected in squash(all_text(p0)),
      (p0.screen.columns, screen(p0)[-4:]))
p0.setFocus(); tab._pane_focused(p0)
check("select pane 1 -> explorer at logs", wait(lambda: ex.cwd == "/home/tester/logs"), ex.cwd)
tab._pane_focused(p1)
check("select pane 2 -> explorer at home", wait(lambda: ex.cwd == "/home/tester"), ex.cwd)

# 8) Sync turned off
ex.follow_chk.setChecked(False)
ex.navigate("/home/tester/docs"); wait(lambda: ex.cwd == "/home/tester/docs"); wait(lambda: False, 0.5)
check("sync off -> terminal unchanged", p1.cwd == "/home/tester", p1.cwd)

w.grab().save(os.path.join(SP, "sync.png"))
w.close()
stop_server(srv)
print("DONE")
