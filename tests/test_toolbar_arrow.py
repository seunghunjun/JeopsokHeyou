# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""The local terminal button in the menu bar's row keeps room for its arrow (with the lower padding of the buttons
there, the arrow used to sit on the icon)."""
import os
import shutil
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "toolbar_arrow")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

app = QApplication([])
from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme  # noqa: E402


def check(name, ok, extra=""):
    if callable(extra):                  # details computed (and printed) only when the check fails
        extra = "" if ok else extra()
    print(("PASS " if ok else "FAIL ") + name, extra)


apply_dark_theme(app)
w = MainWindow()
w.resize(1300, 700)
w.show()
app.processEvents()
for name, tb in (("main window", w.main_toolbar), ("separate window", w.window_toolbar())):
    tb.show()
    app.processEvents()
    menu_btns = [b for b in tb.findChildren(QToolButton)
                 if b.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup]
    plain = [b for b in tb.findChildren(QToolButton) if b.popupMode() != QToolButton.ToolButtonPopupMode.MenuButtonPopup
             and not b.icon().isNull() and b.sizeHint().width() > b.iconSize().width()]
    check(f"{name}: the button with a menu is wider than a plain one by the arrow's room",
          bool(menu_btns) and bool(plain)
          and all(m.sizeHint().width() >= min(p.sizeHint().width() for p in plain) + 9 for m in menu_btns),
          lambda: ([m.sizeHint().width() for m in menu_btns], [p.sizeHint().width() for p in plain]))
w.settings["confirm_quit"] = False
w.close()
print("DONE")
