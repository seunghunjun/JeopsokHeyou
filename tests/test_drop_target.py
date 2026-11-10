# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Dropping files from the file manager onto the server's explorer: while dragging, the folder they go into is
highlighted and named ("Upload to: ..."); dropped on a file they go into that file's folder (also a subfolder opened
in the tree), and the message at the end says where they went."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "drop_target")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
root = os.path.join(SP, "srv")
H = os.path.join(root, "home", "tester")
os.makedirs(os.path.join(H, "sub"))
open(os.path.join(H, "sub", "inside.txt"), "w", encoding="utf-8").write("x")
open(os.path.join(H, "top.txt"), "w", encoding="utf-8").write("x")
mine = os.path.join(SP, "mine.txt")
open(mine, "w", encoding="utf-8").write("from this computer")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
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


def wait(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


def framed(item) -> bool:
    """The drop frame (accent colour) is drawn at the left edge of the item's row."""
    from jeopsokheyou import icons
    app.processEvents()
    img = ex.tree.viewport().grab().toImage()
    rect = ex.tree.visualItemRect(item)
    want = QColor(icons.theme.current().accent)
    c = img.pixelColor(int(2 * img.devicePixelRatio()), int(rect.center().y() * img.devicePixelRatio()))
    return abs(c.red() - want.red()) + abs(c.green() - want.green()) + abs(c.blue() - want.blue()) < 90


class FakeDragEvent:
    """A drag of this computer's files (from the file manager: no source widget) at a row of the list."""

    def __init__(self, tree, item):
        self.tree = tree
        rect = tree.visualItemRect(item) if item is not None else None
        self.pos = QPointF(rect.center()) if rect is not None else QPointF(5, tree.viewport().height() - 3)
        self.mime = QMimeData()
        self.mime.setUrls([QUrl.fromLocalFile(mine)])
        self.accepted = None

    def mimeData(self):
        return self.mime

    def source(self):
        return None

    def position(self):
        return self.pos

    def modifiers(self):
        return Qt.KeyboardModifier.NoModifier

    def setDropAction(self, _a):
        pass

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
try:
    w = MainWindow()
    w.resize(1300, 800)
    w.show()
    w.open_session(Session(host="127.0.0.1", port=2299, user="tester", name="srv"), "pw")
    tab = w.current_tab()
    ex = tab.explorer
    check("connected", wait(lambda: tab.state == "connected" and ex.cwd == "/home/tester"
                            and ex._find_item("/home/tester/sub") is not None, 15))
    check("tree view", ex.tree_mode())
    sub = ex._find_item("/home/tester/sub")
    sub.setExpanded(True)
    check("subfolder opened in the tree", wait(lambda: ex._find_item("/home/tester/sub/inside.txt") is not None, 10))
    inside = ex._find_item("/home/tester/sub/inside.txt")
    before = ex.info.text()

    ev = FakeDragEvent(ex.tree, inside)
    ex.tree.dragEnterEvent(ev)
    ex.tree.dragMoveEvent(ev)
    check("dragging over a file in a subfolder names that subfolder", ex.info.text() == "Upload to: /home/tester/sub",
          lambda: ex.info.text())
    check("... and frames the subfolder's row on screen", ex.tree._marked is sub and framed(sub),
          lambda: (ex.tree._marked, framed(sub)))
    top = ex._find_item("/home/tester/top.txt")
    ev2 = FakeDragEvent(ex.tree, top)
    ex.tree.dragMoveEvent(ev2)
    check("over a file of the current folder: the current folder", ex.info.text() == "Upload to: /home/tester"
          and ex.tree._marked is not sub and not framed(sub),
          lambda: ex.info.text())
    ex.tree._hide_target()               # what leaving the list does
    check("leaving the list puts the status back and the highlight away", ex.info.text() == before
          and ex.tree._marked is None, lambda: ex.info.text())

    ev3 = FakeDragEvent(ex.tree, inside)
    ex.tree.dragMoveEvent(ev3)
    ex.tree.dropEvent(ev3)
    check("dropped on a file in the subfolder: uploaded into that subfolder (not the current folder)",
          wait(lambda: os.path.exists(os.path.join(H, "sub", "mine.txt")), 15)
          and not os.path.exists(os.path.join(H, "mine.txt")))
    check("the message says where it went", wait(lambda: ex.info.text() == "Upload complete → /home/tester/sub", 5),
          lambda: ex.info.text())
    w.settings["confirm_quit"] = False
    w.close()
finally:
    stop_server(srv)
print("DONE")
