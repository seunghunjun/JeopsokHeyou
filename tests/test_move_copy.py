# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Moving and copying inside an explorer: dragging items onto a folder moves them (Ctrl / Option copies),
Ctrl+C / Ctrl+X / Ctrl+V copy, cut and paste (also from a server onto this computer and back)."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "move_copy")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
root = os.path.join(SP, "srv")
H = os.path.join(root, "home", "tester")
os.makedirs(os.path.join(H, "dst"))
os.makedirs(os.path.join(H, "src", "sub"))
for name, text in (("a.txt", "A"), ("b.txt", "B"), (os.path.join("src", "sub", "inner.txt"), "inner"),
                   (os.path.join("dst", "taken.txt"), "old")):
    open(os.path.join(H, name), "w", encoding="utf-8").write(text)
open(os.path.join(H, "taken.txt"), "w", encoding="utf-8").write("new")
here = os.path.join(SP, "here")
os.makedirs(here)

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from _util import stop_server  # noqa: E402
from jeopsokheyou import explorer as explorer_mod, localshell  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.explorer import copy_name  # noqa: E402
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


def settle(sec=0.8):
    wait(lambda: False, sec)


def item(ex, name):
    path = ex.cwd.rstrip("/") + "/" + name
    it = ex._find_item(path) if ex.tree_mode() else None
    if it is None:
        for i in range(ex.tree.topLevelItemCount()):
            if ex.tree.topLevelItem(i).text(0) == name:
                it = ex.tree.topLevelItem(i)
    return it


def select(ex, *names):
    ex.tree.clearSelection()
    for n in names:
        item(ex, n).setSelected(True)


class FakeDrop:
    """A drop of the explorer's own drag on one of its items (Ctrl held or not)."""

    def __init__(self, tree, onto, copy=False):
        self.tree, self.copy = tree, copy
        it = item(tree.explorer, onto) if onto else None
        rect = tree.visualItemRect(it) if it is not None else None
        self.pos = QPointF(rect.center()) if rect is not None else QPointF(5, tree.viewport().height() - 3)
        self.mime = QMimeData()
        self.mime.setUrls([QUrl.fromLocalFile(os.path.join(SP, "x"))])
        self.accepted = None

    def mimeData(self):
        return self.mime

    def source(self):
        return self.tree

    def position(self):
        return self.pos

    def modifiers(self):
        key = Qt.KeyboardModifier.AltModifier if sys.platform == "darwin" else Qt.KeyboardModifier.ControlModifier
        return key if self.copy else Qt.KeyboardModifier.NoModifier

    def setDropAction(self, _a):
        pass

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


class FakeDrag:
    """Stands in for the system drag: the drop lands on our own list."""
    drop = None

    def __init__(self, source):
        self.source = source

    def setMimeData(self, m):
        pass

    def setPixmap(self, *_a):
        pass

    def exec(self, *_a):
        FakeDrag.drop()
        return Qt.DropAction.CopyAction


def ctrl(ex, key):
    ex.tree.setFocus()
    QTest.keyClick(ex.tree, key, Qt.KeyboardModifier.ControlModifier)   # Command on macOS (Qt maps it so)


asked = []


def answer(choice):
    def fake(parent, existing, remote_dir):
        asked.append(sorted(n for n, _d in existing))
        return choice
    explorer_mod.ask_overwrite = fake


# ---- names for a copy in the same folder
check("copy names", copy_name({"a.txt"}, "a.txt") == "a - copy.txt"
      and copy_name({"a - copy.txt"}, "a.txt") == "a - copy (2).txt" and copy_name(set(), "dir") == "dir - copy"
      and copy_name(set(), ".bashrc") == ".bashrc - copy")

srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
real_drag = explorer_mod.QDrag
try:
    w = MainWindow()
    w.resize(1300, 800)
    w.show()
    s = Session(host="127.0.0.1", port=2299, user="tester", name="srv")
    w.store.upsert(s)
    w.open_session(s, "pw")
    tab = w.current_tab()
    ex = tab.explorer
    check("server tab ready", wait(lambda: tab.state == "connected" and ex.cwd == "/home/tester"
                                   and item(ex, "dst") is not None, 15))
    explorer_mod.QDrag = FakeDrag

    # ---- drag onto a folder: move
    select(ex, "a.txt", "b.txt")
    FakeDrag.drop = lambda: ex.tree.dropEvent(FakeDrop(ex.tree, "dst"))
    ex._start_drag_out()
    check("dragged onto a folder: moved there", wait(lambda: os.path.exists(os.path.join(H, "dst", "a.txt"))
                                                     and os.path.exists(os.path.join(H, "dst", "b.txt")), 10)
          and not os.path.exists(os.path.join(H, "a.txt")) and not os.path.exists(os.path.join(H, "b.txt")))
    check("... the list shows it", wait(lambda: item(ex, "a.txt") is None, 5))

    # ---- with Ctrl (Option on macOS): copy
    select(ex, "src")
    FakeDrag.drop = lambda: ex.tree.dropEvent(FakeDrop(ex.tree, "dst", copy=True))
    ex._start_drag_out()
    check("Ctrl + drag copies a folder with what is inside",
          wait(lambda: os.path.exists(os.path.join(H, "dst", "src", "sub", "inner.txt")), 10)
          and os.path.exists(os.path.join(H, "src", "sub", "inner.txt"))
          and open(os.path.join(H, "dst", "src", "sub", "inner.txt"), encoding="utf-8").read() == "inner")

    # ---- not into itself
    settle()
    select(ex, "src")
    d = FakeDrop(ex.tree, "src")
    ex.tree.dropEvent(d)
    settle()
    check("a folder is not dropped into itself", d.accepted is False and os.path.isdir(os.path.join(H, "src")))

    # ---- Ctrl+C, Ctrl+V in the same folder: a copy with a new name
    select(ex, "taken.txt")
    ctrl(ex, Qt.Key.Key_C)
    check("Ctrl+C remembers the items", explorer_mod.CLIPBOARD["paths"] == ["/home/tester/taken.txt"]
          and not explorer_mod.CLIPBOARD["cut"], lambda: explorer_mod.CLIPBOARD)
    asked.clear()
    ctrl(ex, Qt.Key.Key_V)
    check("pasted in its own folder: \"taken - copy.txt\"",
          wait(lambda: os.path.exists(os.path.join(H, "taken - copy.txt")), 10) and not asked
          and open(os.path.join(H, "taken - copy.txt"), encoding="utf-8").read() == "new")

    # ---- a name already there: asked first
    answer("skip")
    ex.paste("/home/tester/dst")
    check("pasting where the name exists asks first", wait(lambda: asked == [["taken.txt"]], 5), asked)
    settle()
    check("... skip keeps what is there", open(os.path.join(H, "dst", "taken.txt"), encoding="utf-8").read() == "old")
    asked.clear()
    answer("overwrite")
    ex.paste("/home/tester/dst")
    check("... overwrite replaces it", wait(lambda: open(os.path.join(H, "dst", "taken.txt"),
                                                         encoding="utf-8").read() == "new", 10))

    # ---- Ctrl+X, then Ctrl+V in another folder: moved, once
    settle()
    select(ex, "taken - copy.txt")
    ctrl(ex, Qt.Key.Key_X)
    check("Ctrl+X marks a cut", explorer_mod.CLIPBOARD["cut"])
    ex.navigate("/home/tester/src")
    check("went into src", wait(lambda: ex.cwd == "/home/tester/src", 10))
    ctrl(ex, Qt.Key.Key_V)
    check("cut + paste moves it", wait(lambda: os.path.exists(os.path.join(H, "src", "taken - copy.txt")), 10)
          and not os.path.exists(os.path.join(H, "taken - copy.txt")))
    check("... and a cut is pasted only once", not explorer_mod.CLIPBOARD["paths"])
    ex.navigate("/home/tester")
    wait(lambda: ex.cwd == "/home/tester" and item(ex, "src") is not None, 10)

    # ---- from one server tab to another (down to this computer, then up)
    w.open_session(s, "pw")
    tab2 = w.current_tab()
    ex2 = tab2.explorer
    check("second server tab ready", wait(lambda: tab2.state == "connected" and ex2.cwd == "/home/tester", 15))
    ex.navigate("/home/tester/dst")
    wait(lambda: ex.cwd == "/home/tester/dst" and item(ex, "a.txt") is not None, 10)
    select(ex, "a.txt")
    ex.copy_selected(True)
    ex2.paste("/home/tester/src")
    check("server -> server: pasted, and a cut from another place leaves the original",
          wait(lambda: os.path.exists(os.path.join(H, "src", "a.txt")), 15)
          and os.path.exists(os.path.join(H, "dst", "a.txt")))
    ex.navigate("/home/tester")
    wait(lambda: ex.cwd == "/home/tester" and item(ex, "taken.txt") is not None, 10)

    # ---- from the server onto this computer (a local terminal's explorer)
    prof = localshell.default_profile({})
    prof.start_dir = here
    w.open_local(prof)
    ltab = w.current_tab()
    lex = ltab.explorer
    vhere = localshell.to_virtual(here)
    check("local tab ready", wait(lambda: lex.cwd == vhere, 20), lex.cwd)
    select(ex, "taken.txt")
    ex.copy_selected(False)
    lex.paste()
    check("server -> this computer: pasted (downloaded) here",
          wait(lambda: os.path.exists(os.path.join(here, "taken.txt")), 15)
          and open(os.path.join(here, "taken.txt"), encoding="utf-8").read() == "new")

    # ---- this computer: copy inside, then onto the server
    wait(lambda: item(lex, "taken.txt") is not None, 10)
    select(lex, "taken.txt")
    lex.copy_selected(False)
    lex.paste()
    check("this computer: a copy in the same folder", wait(lambda: os.path.exists(os.path.join(here, "taken - copy.txt")), 10))
    os.makedirs(os.path.join(here, "box"))
    lex.refresh()
    wait(lambda: item(lex, "box") is not None, 10)
    select(lex, "taken.txt")
    lex.copy_selected(True)
    lex.paste(vhere + "/box")
    check("this computer: cut + paste into a folder moves it",
          wait(lambda: os.path.exists(os.path.join(here, "box", "taken.txt")), 10)
          and not os.path.exists(os.path.join(here, "taken.txt")))
    wait(lambda: item(lex, "taken - copy.txt") is not None, 10)
    select(lex, "taken - copy.txt")
    lex.copy_selected(False)
    ex.paste("/home/tester/dst")
    check("this computer -> server: pasted (uploaded)", wait(lambda: os.path.exists(os.path.join(H, "dst", "taken - copy.txt")), 15))
    w.settings["confirm_quit"] = False
    w.close()
finally:
    explorer_mod.QDrag = real_drag
    stop_server(srv)
print("DONE")
