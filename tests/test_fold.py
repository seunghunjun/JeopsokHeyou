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
w.settings["confirm_quit"] = False
w.close()
print("DONE")
