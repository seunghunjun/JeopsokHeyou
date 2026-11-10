# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Room for the terminals: a folded explorer leaves a strip next to the terminal that brings it back, and the toolbar
is turned on and off from View > Toolbar (not only by right-clicking it)."""
import os
import shutil
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "fold")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou import config, localshell  # noqa: E402
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


w = MainWindow()
w.resize(1200, 700)
w.show()
w.open_local(localshell.default_profile({}))
tab = w.current_tab()
ex = tab.explorer
wait(lambda: ex.cwd != "", 15)

# ---- folding the explorer (toolbar button / shortcut) leaves a strip that brings it back
check("explorer shown, no strip", not ex.isHidden() and tab.explorer_strip.isHidden())
ex.fold_btn.click()
check("the explorer's own button folds it", wait(lambda: ex.isHidden(), 3))
check("folded: the strip appears next to the terminal", not tab.explorer_strip.isHidden())
tab.explorer_strip.button.click()
check("the strip's button brings it back", wait(lambda: not ex.isHidden(), 3) and tab.explorer_strip.isHidden())
w.toggle_explorer()
check("the shortcut / View menu still fold it", ex.isHidden() and not tab.explorer_strip.isHidden())
w.toggle_explorer()
from PySide6.QtWidgets import QToolButton  # noqa: E402
check("no explorer button on the toolbar any more",
      not any("explorer" in b.toolTip().lower() for b in w.main_toolbar.findChildren(QToolButton)))
from PySide6.QtCore import Qt  # noqa: E402
check("the buttons share the menu bar's row (no separate toolbar row)",
      w.menuBar().cornerWidget(Qt.Corner.TopRightCorner) is w.main_toolbar
      and w.main_toolbar.mapTo(w, w.main_toolbar.rect().topLeft()).y() < w.menuBar().height())

# ---- View > Toolbar
check("toolbar shown by default, menu item checked", not w.main_toolbar.isHidden() and w.toolbar_act.isChecked())
w.toolbar_act.trigger()
check("View > Toolbar hides it", w.main_toolbar.isHidden() and not w.toolbar_act.isChecked()
      and config.load_settings().get("show_toolbar") is False)
from PySide6.QtCore import QPoint  # noqa: E402
w.float_tab(tab, QPoint(200, 120))
app.processEvents()
win = w.tab_windows[0]
win_tbs = [t for t in w._toolbars if t is not w.main_toolbar]
check("a separate window opens without the toolbar too", bool(win_tbs) and all(t.isHidden() for t in win_tbs))
w.toolbar_act.trigger()
check("... and gets it back with the menu item", not w.main_toolbar.isHidden() and all(not t.isHidden() for t in win_tbs))
w.main_toolbar.toggleViewAction().trigger()          # the right-click menu
check("right-click unchecking is the same setting", w.main_toolbar.isHidden() and not w.toolbar_act.isChecked()
      and config.load_settings().get("show_toolbar") is False)
w.toolbar_act.trigger()

# ---- focus mode: menus and tabs hidden over terminals, the same key brings them back
from PySide6.QtGui import QAction  # noqa: E402
w.toggle_focus_mode()
app.processEvents()
check("focus mode hides the menu bar and the tab bar of a window showing terminals",
      w.focus_mode and win.menuBar().isHidden() and win.tabs.tabBar().isHidden())
check("... but not over Home (no title bar there to leave it from)", w.tabs.currentWidget() is w.home
      and not w.menuBar().isHidden() and not w.tabs.tabBar().isHidden())
check("... the menus' shortcuts still work (they are on the window too)",
      w.focus_act in w.actions() and w.explorer_act in w.actions())
w.toggle_focus_mode()
app.processEvents()
check("... and the same key brings them back", not w.focus_mode and not win.menuBar().isHidden()
      and not win.tabs.tabBar().isHidden())
check("the toolbar has a button that turns it on",
      any(b.toolTip().startswith("Focus mode") for b in w.main_toolbar.findChildren(QToolButton)))
w.toggle_focus_mode(True)
p0 = w.session_tabs()[0].panes[0]
check("in focus mode each terminal's title bar has the way back", not p0.frame.bar.focus_btn.isHidden()
      and ("Ctrl+Shift+M" in p0.frame.bar.focus_btn.toolTip() or "⇧⌘M" in p0.frame.bar.focus_btn.toolTip()),
      lambda: p0.frame.bar.focus_btn.toolTip())
p0.frame.bar.focus_btn.click()
check("... and clicking it leaves focus mode", not w.focus_mode and not win.menuBar().isHidden()
      and p0.frame.bar.focus_btn.isHidden())
w.toggle_focus_mode(True)
w.float_tab(win.tabs.widget(0), QPoint(260, 160))      # a window opened while focus mode is on
app.processEvents()
check("a window opened in focus mode follows it", all(x.menuBar().isHidden() for x in w.tab_windows))
w.toggle_focus_mode(False)

# ---- focus mode: the other open connections on the top-left terminal's title bar (one place only)
w.open_local(localshell.default_profile({}))
t1 = w.tabs.widget(w.tabs.count() - 1)
w.open_local(localshell.default_profile({}))
t2 = w.tabs.widget(w.tabs.count() - 1)
w.tabs.setCurrentWidget(t2)
wait(lambda: False, 0.3)
w.toggle_focus_mode(True)


def chips(tab):
    return [[b.text() for b in p.frame.bar.chips.findChildren(QToolButton)
             if b.objectName() == "FocusChip" and b.isCheckable()]
            for p in tab.panes if not p.frame.bar.chips.isHidden()]


def home_chip(tab):
    bs = [b for p in tab.panes for b in p.frame.bar.chips.findChildren(QToolButton)
          if not p.frame.bar.chips.isHidden() and b.objectName() == "FocusChip" and not b.isCheckable()]
    return bs[0] if bs else None


def names():
    return [w.tabs.tabText(i) for i in range(w.tabs.count()) if w.tabs.widget(i) in (t1, t2)]


check("the open connections are shown on the terminal's title bar", wait(lambda: chips(t2) == [names()], 3),
      lambda: (chips(t2), names()))
w.split(Qt.Orientation.Horizontal)
check("split: still on one title bar only (the top-left terminal)",
      wait(lambda: len(t2.panes) == 2 and len(chips(t2)) == 1, 5)
      and not t2.panes[0].frame.bar.chips.isHidden() and t2.panes[1].frame.bar.chips.isHidden(),
      lambda: chips(t2))
conn = [b for b in t2.panes[0].frame.bar.chips.findChildren(QToolButton) if b.isCheckable()]
mine = [b for b in conn if b.isChecked()]
other = [b for b in conn if not b.isChecked()]
check("the current connection is marked", len(mine) == 1 and len(other) == 1)
other[0].click()
check("clicking another connection goes to it", wait(lambda: w.tabs.currentWidget() is t1, 3)
      and wait(lambda: chips(t1) == [names()], 3), lambda: chips(t1))
check("a Home button comes first", home_chip(t1) is not None
      and t1.panes[0].frame.bar.chips_lay.itemAt(0).widget() is home_chip(t1))
home_chip(t1).click()
check("... it opens Home, where the menus and tabs show again", wait(lambda: w.tabs.currentWidget() is w.home, 3)
      and not w.menuBar().isHidden() and not w.tabs.tabBar().isHidden() and w.focus_mode)
check("... focus mode rests on Home: menu item unchecked and greyed, the button too",
      not w.focus_act.isChecked() and not w.focus_act.isEnabled() and not w.main_toolbar.focus_btn.isEnabled())
w.tabs.setCurrentWidget(t1)
check("back on a terminal: focus mode again", wait(lambda: w.menuBar().isHidden() and w.tabs.tabBar().isHidden(), 3)
      and w.focus_act.isChecked() and w.focus_act.isEnabled())
w.toggle_focus_mode(False)
check("leaving focus mode: no connections on the title bars", wait(lambda: not chips(t1) and not chips(t2), 3))
w.settings["confirm_quit"] = False
w.close()
print("DONE")
