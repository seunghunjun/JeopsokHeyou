# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Dragging files between a local terminal's explorer (this computer) and a server's explorer:
server -> this computer downloads into the folder dropped on, this computer -> server uploads."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "local_transfer")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
root = os.path.join(SP, "srv")
os.makedirs(os.path.join(root, "home", "tester"))
open(os.path.join(root, "home", "tester", "server.txt"), "w", encoding="utf-8").write("from the server")
here = os.path.join(SP, "here")
os.makedirs(here)
open(os.path.join(here, "mine.txt"), "w", encoding="utf-8").write("from this computer")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from _util import stop_server  # noqa: E402
from jeopsokheyou import explorer as explorer_mod, localshell  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
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


def select(ex, name):
    ex.tree.clearSelection()
    it = ex._find_item(ex.cwd.rstrip("/") + "/" + name) if ex.tree_mode() else None
    if it is None:
        for i in range(ex.tree.topLevelItemCount()):
            if ex.tree.topLevelItem(i).text(0) == name:
                it = ex.tree.topLevelItem(i)
    it.setSelected(True)
    return it


class FakeDrag:
    """Stands in for the system drag: drop() decides where it lands."""
    drop = None
    last_mime = None

    def __init__(self, source):
        self.source = source

    def setMimeData(self, m):
        FakeDrag.last_mime = m

    def setPixmap(self, *_a):
        pass

    def exec(self, *_a):
        FakeDrag.drop(self)
        return Qt.DropAction.CopyAction


srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
real_drag = explorer_mod.QDrag
try:
    w = MainWindow()
    w.resize(1300, 700)
    w.show()
    s = Session(host="127.0.0.1", port=2299, user="tester", name="srv")
    w.store.upsert(s)
    w.open_session(s, "pw")
    remote_tab = w.current_tab()
    rex = remote_tab.explorer
    check("server tab ready", wait(lambda: remote_tab.state == "connected" and rex.cwd == "/home/tester"
                                   and rex.item_count() > 0, 15))
    prof = localshell.default_profile({})
    prof.start_dir = here
    w.open_local(prof)
    local_tab = w.current_tab()
    lex = local_tab.explorer
    vhere = localshell.to_virtual(here)
    check("local tab ready", wait(lambda: lex.cwd == vhere and lex.item_count() >= 1, 20), lex.cwd)

    explorer_mod.QDrag = FakeDrag
    # server -> this computer: dropped on the local explorer, downloaded straight into its folder
    select(rex, "server.txt")
    FakeDrag.drop = lambda d: lex._on_remote_dropped(rex, None)
    rex._start_drag_out()
    check("server file downloaded into this computer's folder",
          wait(lambda: os.path.exists(os.path.join(here, "server.txt")), 15)
          and open(os.path.join(here, "server.txt"), encoding="utf-8").read() == "from the server")
    check("... and the local explorer shows it", wait(lambda: lex._find_item(vhere + "/server.txt") is not None
                                                      if lex.tree_mode() else lex.item_count() >= 2, 10))
    check("no placeholder left behind", not any(n.startswith("~") or n.endswith(".part") for n in os.listdir(here)),
          os.listdir(here))

    # this computer -> server: the local explorer drags real files, the server's explorer uploads them
    select(lex, "mine.txt")
    FakeDrag.drop = lambda d: rex._on_dropped([u.toLocalFile() for u in FakeDrag.last_mime.urls()], None)
    lex._start_drag_out()
    check("local file dragged as a real file", [os.path.normcase(u.toLocalFile()) for u in FakeDrag.last_mime.urls()]
          == [os.path.normcase(os.path.join(here, "mine.txt"))], [u.toLocalFile() for u in FakeDrag.last_mime.urls()])
    check("... uploaded to the server", wait(lambda: os.path.exists(os.path.join(root, "home", "tester", "mine.txt")), 15)
          and open(os.path.join(root, "home", "tester", "mine.txt"), encoding="utf-8").read() == "from this computer")
    w.settings["confirm_quit"] = False
    w.close()
finally:
    explorer_mod.QDrag = real_drag
    stop_server(srv)
print("DONE")
