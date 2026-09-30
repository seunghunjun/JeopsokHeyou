# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys, time, subprocess, shutil
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")   # test work folder (git-ignored)
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
root = os.path.join(SP, "srvroot")
os.makedirs(os.path.join(root, "home/tester/conf"), exist_ok=True)
open(os.path.join(root, "home/tester/conf/web.xml"), "w", encoding="utf-8").write("<web>original</web>\n")
open(os.path.join(root, "home/tester/conf/app.conf"), "w", encoding="utf-8").write("port=80\n")
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
asked = []
def fake_q(parent, title, text, *a, **k):
    asked.append(title)
    return QMessageBox.StandardButton.Yes
QMessageBox.question = staticmethod(fake_q)
from jeopsokheyou import winopen
calls = []
winopen.open_default = lambda p: (calls.append(("default", os.path.basename(p))), not p.endswith(".conf"))[1]
winopen.open_with_dialog = lambda p, h=0: calls.append(("dialog", os.path.basename(p)))
from jeopsokheyou.mainwindow import MainWindow
from jeopsokheyou.config import Session
w = MainWindow(); w.resize(1200, 700); w.show()

def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
        if cond(): return True
    return False

def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)

w.open_session(Session(host="127.0.0.1", port=2299, user="tester"), "pw")
tab = w.current_tab(); ex = tab.explorer
wait(lambda: tab.state == "connected"); asked.clear()   # ignore the host key prompt
ex.navigate("/home/tester/conf"); wait(lambda: ex.cwd == "/home/tester/conf")

ex.open_remote("/home/tester/conf/web.xml")
check("open -> default program", wait(lambda: ("default", "web.xml") in calls), calls)
local = next(k for k in ex.edit_map if k.endswith("web.xml"))

# The editor rewriting the same content on open, or only touching the mtime, must not prompt
data = open(local, "rb").read()
os.utime(local, None); open(local, "wb").write(data)
wait(lambda: False, 1.5)
check("open only / same content saved -> no upload prompt", not asked, asked)

# Open the same file twice in a row (change notice while re-downloading)
ex.open_remote("/home/tester/conf/web.xml"); ex.open_remote("/home/tester/conf/web.xml")
wait(lambda: calls.count(("default", "web.xml")) >= 3); wait(lambda: False, 1.5)
check("open twice in a row -> no upload prompt", not asked, asked)

# Real edit -> prompt and upload
open(local, "w", encoding="utf-8").write("<web>modified</web>\n")
check("real edit -> upload prompt", wait(lambda: bool(asked), 5), asked)
check("uploaded to server", wait(lambda: "modified" in open(os.path.join(root, "home/tester/conf/web.xml"), encoding="utf-8").read(), 5))
asked.clear(); wait(lambda: False, 1.5)
check("no repeat prompt after upload", not asked, asked)

# Choose program
calls.clear()
ex.open_remote("/home/tester/conf/web.xml", choose=True)
check("choose-program dialog", wait(lambda: ("dialog", "web.xml") in calls) and ("default", "web.xml") not in calls, calls)

# File type without an associated program -> chooser opens automatically
calls.clear()
ex.open_remote("/home/tester/conf/app.conf")
check("unassociated type -> chooser", wait(lambda: ("dialog", "app.conf") in calls), calls)
w.close()
stop_server(srv)
print("DONE")
