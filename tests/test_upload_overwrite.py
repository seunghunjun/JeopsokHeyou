# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Uploading a name that already exists asks first (overwrite / skip / cancel); explorer columns are resizable."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata-overwrite")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
root = os.path.join(SP, "srvroot-overwrite")
shutil.rmtree(root, ignore_errors=True)
os.makedirs(root)
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, os.path.dirname(TESTS))
from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou import explorer  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.explorer import COL_NAME, SftpExplorer  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme  # noqa: E402


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


apply_dark_theme(app)
w = MainWindow()
w.resize(1200, 700)
w.show()
w.open_session(Session(host="127.0.0.1", port=2299, user="tester", name="srv"), "pw")
tab = w.current_tab()
ex = tab.explorer
check("connected", wait(lambda: tab.state == "connected" and ex.cwd == "/home/tester"), ex.cwd)

remote = os.path.join(root, "home", "tester", "hello.txt")
original = open(remote, encoding="utf-8").read()
local_dir = os.path.join(SP, "overwrite-local")
shutil.rmtree(local_dir, ignore_errors=True)
os.makedirs(local_dir)
local = os.path.join(local_dir, "hello.txt")
open(local, "w", encoding="utf-8").write("NEW CONTENT\n")
fresh = os.path.join(local_dir, "fresh.txt")
open(fresh, "w", encoding="utf-8").write("fresh\n")

asked = []


def answer(choice):
    def fake(parent, existing, remote_dir):
        asked.append([n for n, _d in existing])
        return choice
    explorer.ask_overwrite = fake


def settle():
    wait(lambda: False, 1.0)


answer("cancel")
ex.upload([local], ex.cwd)
check("asked before overwriting an existing file", wait(lambda: asked == [["hello.txt"]], 5), asked)
settle()
check("cancel leaves the remote file alone", open(remote, encoding="utf-8").read() == original)

asked.clear()
answer("skip")
ex.upload([local, fresh], ex.cwd)
wait(lambda: os.path.exists(os.path.join(root, "home", "tester", "fresh.txt")), 5)
settle()
check("only the existing name was asked about", asked == [["hello.txt"]], asked)
check("skip keeps the existing file and uploads the new one",
      open(remote, encoding="utf-8").read() == original
      and os.path.exists(os.path.join(root, "home", "tester", "fresh.txt")))

asked.clear()
answer("overwrite")
ex.upload([local], ex.cwd)
check("overwrite replaces the file", wait(lambda: open(remote, encoding="utf-8").read() == "NEW CONTENT\n", 5))

asked.clear()
newer = os.path.join(local_dir, "brand-new.txt")
open(newer, "w", encoding="utf-8").write("x\n")
ex.upload([newer], ex.cwd)
check("no question when nothing exists yet", wait(lambda: os.path.exists(os.path.join(root, "home", "tester",
                                                                                      "brand-new.txt")), 5)
      and asked == [])

# ---------------------------------------------------------------- columns
h = ex.tree.header()
check("name column is user-resizable", h.sectionResizeMode(COL_NAME) == explorer.QHeaderView.ResizeMode.Interactive)
h.resizeSection(COL_NAME, 333)
check("user width remembered", w.settings.get("explorer_columns", {}).get(str(COL_NAME)) == 333)
other = SftpExplorer("x", w.settings)
check("new explorers use the remembered widths", other.tree.header().sectionSize(COL_NAME) == 333)

w.close()
stop_server(srv)
print("DONE")
