# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""File explorer tree view: parents stay visible, folders open in place (one listing each, when opened),
and the flat list is still available from Settings."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "explorertree")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)

root = os.path.join(SP, "srv")
for d in ("home/tester/app/conf", "home/tester/logs", "home/other", "etc"):
    os.makedirs(os.path.join(root, d), exist_ok=True)
for f in ("home/tester/readme.txt", "home/tester/app/conf/server.xml", "etc/hosts"):
    open(os.path.join(root, f), "w", encoding="utf-8").write("x")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from _util import stop_server  # noqa: E402
from jeopsokheyou import explorer  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


check("ancestors", explorer.ancestors("/home/tester") == ["/", "/home", "/home/tester"]
      and explorer.ancestors("/") == ["/"])

srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
try:
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    s = Session(host="127.0.0.1", port=2299, user="tester", name="tree")
    w.store.upsert(s)
    w.open_session(s, "pw")
    tab = w.current_tab()
    ex = tab.explorer
    check("connected", wait(lambda: tab.state == "connected" and ex.cwd == "/home/tester" and ex.item_count() > 0, 15),
          ex.cwd)
    top = sorted(ex.tree.topLevelItem(i).text(0) for i in range(ex.tree.topLevelItemCount()))
    check("tree starts at / with the parents visible", "home" in top and "etc" in top, top)
    home = ex._find_item("/home")
    check("the way to the current folder is open", home is not None and home.isExpanded()
          and ex._cwd_item is not None and ex._cwd_item.isExpanded())
    check("current folder in bold", ex._cwd_item.font(0).bold())
    names = sorted(ex._cwd_item.child(i).text(0) for i in range(ex._cwd_item.childCount()))
    check("current folder contents", {"app", "logs", "readme.txt"} <= set(names), names)
    other = ex._find_item("/home/other")
    check("other folders are closed with a placeholder", other is not None and not other.isExpanded()
          and other.childCount() == 1 and other.child(0).data(0, Qt.ItemDataRole.UserRole) is None)
    check("status counts the current folder", ex.info.text() == f"{ex.item_count()} items", ex.info.text())

    # open a folder in place (one listing, only now)
    app_item = ex._find_item("/home/tester/app")
    app_item.setExpanded(True)
    check("opening a folder lists it in place", wait(lambda: ex._find_item("/home/tester/app/conf") is not None))
    check("current folder unchanged", ex.cwd == "/home/tester")

    # go deeper: the parents stay visible
    ex.navigate("/home/tester/app/conf")
    check("navigate deeper", wait(lambda: ex.cwd == "/home/tester/app/conf" and ex.item_count() == 1))
    check("parents still shown above", ex._find_item("/home/tester/logs") is not None
          and ex._find_item("/etc") is not None)
    check("the folder opened before stays open", ex._find_item("/home/tester/app").isExpanded())
    ex.go_up()
    check("go up selects the new current folder", wait(lambda: ex.cwd == "/home/tester/app")
          and wait(lambda: ex.tree.currentItem() is not None and ex.tree.currentItem().text(0) == "app"))

    # going up to / still shows everything (it used to come out empty)
    ex.navigate("/home")
    wait(lambda: ex.cwd == "/home")
    # let the terminal finish its own cd first (a slow machine would otherwise still be on the way)
    wait(lambda: tab.active is not None and tab.active.cwd == "/home" and not tab.active._hiding)
    ex.go_up()
    check("up to / lists the root", wait(lambda: ex.cwd == "/" and ex.item_count() >= 2), ex.item_count())
    check("... and nothing is selected at /", not ex.tree.selectedItems())
    ex.refresh()
    check("refresh at / keeps the root", wait(lambda: ex.tree.topLevelItemCount() >= 2))

    # moving elsewhere only keeps the way to the new folder open
    ex.navigate("/home/tester")
    wait(lambda: ex.cwd == "/home/tester" and ex._cwd_item is not None)
    ex._find_item("/home/tester/app").setExpanded(True)
    wait(lambda: ex._find_item("/home/tester/app/conf") is not None)
    ex.refresh()
    check("refresh keeps opened folders", wait(lambda: ex._find_item("/home/tester/app") is not None
                                               and ex._find_item("/home/tester/app").isExpanded()))
    ex.navigate("/etc")
    wait(lambda: ex.cwd == "/etc")
    wait(lambda: False, 1)
    check("navigating closes the old branch", not ex._find_item("/home").isExpanded(),
          (sorted(ex._expanded), ex._find_item("/home").childCount()))

    # double-click an open folder folds it, a closed one opens it
    item = ex._find_item("/etc")
    ex._on_double(item, 0)
    check("double-click on an open folder folds it", not ex._find_item("/etc").isExpanded() and ex.cwd == "/etc")
    wait(lambda: tab.panes[0].cwd == ex.cwd, 5)       # let the terminal catch up with the last move first
    wait(lambda: False, 0.5)
    sb = ex.tree.verticalScrollBar()
    sb.setValue(sb.maximum())
    before = sb.value()
    home_item = ex._find_item("/home")
    ex._on_double(home_item, 0)
    check("double-click on a closed folder opens it in place", wait(lambda: ex.cwd == "/home"
                                                                    and home_item.isExpanded()
                                                                    and home_item.childCount() > 1))
    check("... without redrawing the tree", ex._find_item("/home") is home_item and ex._cwd_item is home_item
          and home_item.font(0).bold() and not ex._find_item("/etc").font(0).bold())
    check("... without scrolling", sb.value() == before or sb.maximum() == 0, (before, sb.value()))
    check("... path bar and Back follow", ex.path_edit.text() == "/home" and ex.history[-1:] == ["/etc"],
          (ex.path_edit.text(), ex.history[-3:]))
    ex.go_back()
    check("Back returns", wait(lambda: ex.cwd == "/etc"))
    ex.navigate("/etc")
    wait(lambda: ex.cwd == "/etc")

    # "up" starts from the selected folder (or the folder of a selected file), not the bold current folder
    ex.navigate("/home/tester")
    wait(lambda: ex.cwd == "/home/tester" and ex._cwd_item is not None)
    wait(lambda: tab.panes[0].cwd == ex.cwd, 5)
    wait(lambda: False, 0.5)
    ex._find_item("/home/tester/app").setExpanded(True)
    wait(lambda: ex._find_item("/home/tester/app/conf") is not None)
    ex._find_item("/home/tester/app/conf").setExpanded(True)
    wait(lambda: ex._find_item("/home/tester/app/conf/server.xml") is not None)
    ex.tree.setCurrentItem(ex._find_item("/home/tester/app/conf"))
    ex.go_up()
    check("up from a selected folder goes to its parent", wait(lambda: ex.cwd == "/home/tester/app"), ex.cwd)
    check("... and that parent is selected", wait(lambda: ex.tree.currentItem() is not None
                                                   and ex.tree.currentItem().text(0) == "app"))
    wait(lambda: tab.panes[0].cwd == ex.cwd, 5)
    wait(lambda: False, 0.5)
    ex._find_item("/home/tester/app/conf").setExpanded(True)
    wait(lambda: ex._find_item("/home/tester/app/conf/server.xml") is not None)
    ex.tree.setCurrentItem(ex._find_item("/home/tester/app/conf/server.xml"))
    ex.go_up()
    check("up from a selected file goes above its folder", wait(lambda: ex.cwd == "/home/tester/app"), ex.cwd)
    ex.tree.clearSelection()
    ex.go_up()
    check("nothing selected: up from the current folder", wait(lambda: ex.cwd == "/home/tester"), ex.cwd)
    ex.go_up()                               # right away: the terminal's late report of the last folder comes in now
    check("pressing up again keeps going up (the selection follows)",
          wait(lambda: ex.cwd == "/home") and ex.tree.currentItem() is not None
          and ex.tree.currentItem().text(0) == "home", (ex.cwd, ex.tree.currentItem() and ex.tree.currentItem().text(0),
                                                       [i.text(0) for i in ex.tree.selectedItems()]))
    ex.go_up()
    check("... and again", wait(lambda: ex.cwd == "/"), ex.cwd)
    wait(lambda: False, 2)
    check("late terminal reports did not pull it back", ex.cwd == "/", ex.cwd)
    wait(lambda: tab.panes[0].cwd == ex.cwd, 5)
    wait(lambda: False, 0.5)

    # clicking a folder (or a file) makes it the location: full path, bold, item count — no redraw
    ex.navigate("/home/tester")
    wait(lambda: ex.cwd == "/home/tester" and ex._find_item("/home/tester/app") is not None)
    wait(lambda: tab.panes[0].cwd == ex.cwd, 5)
    wait(lambda: False, 0.5)
    ex._find_item("/home/tester/app").setExpanded(True)
    wait(lambda: ex._find_item("/home/tester/app/conf") is not None)
    conf = ex._find_item("/home/tester/app/conf")
    term_before = tab.panes[0].cwd
    ex.tree.setCurrentItem(conf)
    check("clicking a subfolder shows its full path", ex.cwd == "/home/tester/app/conf"
          and ex.path_edit.text() == "/home/tester/app/conf" and conf.font(0).bold()
          and ex._find_item("/home/tester/app/conf") is conf, (ex.cwd, ex.path_edit.text()))
    check("... the terminal stays where it is (only double-click moves it)", tab.panes[0].cwd == term_before)
    conf.setExpanded(True)
    wait(lambda: ex._find_item("/home/tester/app/conf/server.xml") is not None)
    ex.tree.setCurrentItem(ex._find_item("/home/tester/readme.txt"))
    check("clicking a file shows its folder", ex.cwd == "/home/tester" and ex.path_edit.text() == "/home/tester"
          and not conf.font(0).bold())
    app_item = ex._find_item("/home/tester/app")
    ex.tree.setCurrentItem(conf)
    check("conf is open and current", conf.isExpanded() and ex.cwd == "/home/tester/app/conf")
    ex.go_up()
    check("Up folds the folder where it is (no redraw)", not conf.isExpanded() and ex.cwd == "/home/tester/app"
          and ex._find_item("/home/tester/app") is app_item and app_item.font(0).bold()
          and ex.tree.currentItem() is app_item and ex.tree.selectedItems() == [app_item]
          and ex.path_edit.text() == "/home/tester/app")
    check("... and the terminal follows", wait(lambda: tab.panes[0].cwd == "/home/tester/app", 5), tab.panes[0].cwd)
    wait(lambda: False, 0.5)

    # double-click a folder in another branch
    ex._on_double(ex._find_item("/etc"), 0)
    check("double-click opens another branch", wait(lambda: ex.cwd == "/etc" and ex.item_count() == 1))

    # placeholder is harmless
    def placeholder(parent):
        for i in range(parent.childCount()):
            c = parent.child(i)
            if c.data(0, Qt.ItemDataRole.UserRole) is None:
                return c
            found = placeholder(c)
            if found is not None:
                return found
        return None
    ph = placeholder(ex.tree.invisibleRootItem())   # a closed folder's "Loading…" row
    before_cwd = ex.cwd
    ex._on_double(ph, 0)
    check("double-click on Loading does nothing", ph is not None and ex.cwd == before_cwd)

    # flat list from Settings
    w.settings["explorer_tree"] = False
    ex.refresh()
    check("flat list when turned off", wait(lambda: ex.tree.topLevelItemCount() == 1
                                            and ex.tree.topLevelItem(0).text(0) == "hosts"))
    w.settings["explorer_tree"] = True
    ex.refresh()
    check("tree again when turned on", wait(lambda: ex._find_item("/home") is not None))
    w.close()
finally:
    stop_server(srv)
print("DONE")
