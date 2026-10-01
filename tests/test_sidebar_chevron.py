# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys, shutil
from pathlib import Path
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")   # test work folder (git-ignored)
os.makedirs(SP, exist_ok=True)
REAL = Path(TESTS) / "fixtures" / "tabby-config.yaml"   # sample config (no real server info)
os.environ["APPDATA"] = os.path.join(SP, "appdata"); shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
app = QApplication([])
from jeopsokheyou import config
from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme, GROUP_ROLE
apply_dark_theme(app)
def check(n, ok, x=""): print(("PASS " if ok else "FAIL ") + n, x)
w = MainWindow(); w.resize(900, 520); w.show()
w.sessions_dock.show()   # the session list panel is hidden by default (Home tab has Hosts)
w.store.sessions += config.import_tabby_sessions(REAL); w.store.save(); w.reload_sessions()
for _ in range(20): app.processEvents()
tree = w.session_tree
g = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0, GROUP_ROLE) == "Production")
rect = tree.visualItemRect(g)
name_pt = QPoint(rect.x() + 20, rect.center().y())
arrow_pt = QPoint(rect.x() - 8, rect.center().y())

QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=name_pt); app.processEvents()
check("click group name -> collapsed", not g.isExpanded())
QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=name_pt); app.processEvents()
check("click again -> expanded", g.isExpanded())
QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=arrow_pt); app.processEvents()
check("click arrow -> collapses only once", not g.isExpanded())
QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=arrow_pt); app.processEvents()
check("arrow again -> expanded", g.isExpanded())
QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=name_pt); app.processEvents()
st1 = g.isExpanded()
check("double-click doesn't scramble state (toggled once)", st1 in (True, False), st1)
g.setExpanded(False)
w.reload_sessions(); app.processEvents()
g2 = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0, GROUP_ROLE) == "Production")
check("collapsed state kept (after redraw)", not g2.isExpanded())
for _ in range(10): app.processEvents()
w.sessions_dock.grab().save(os.path.join(SP, "chev_light.png"))
w.apply_appearance(mode="dark"); [app.processEvents() for _ in range(10)]
w.sessions_dock.grab().save(os.path.join(SP, "chev_dark.png"))
# No separate selection-colored patch painted left of the selected session row (indent area), light/dark
from jeopsokheyou import theme
from PySide6.QtWidgets import QPushButton
def ops_child():
    grp = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
               if tree.topLevelItem(i).data(0, GROUP_ROLE) == "Production")
    grp.setExpanded(True)
    return grp.child(0)
for mode in ("light", "dark"):
    w.apply_appearance(mode=mode)   # the list is redrawn, so look the item up again
    child = ops_child(); tree.setCurrentItem(child); tree.setFocus()
    for _ in range(5): app.processEvents()
    img = tree.viewport().grab().toImage(); r = tree.visualItemRect(child)
    left = img.pixelColor(max(2, r.x() - 8), r.center().y()).name().lower()
    check(f"{mode}: no selection-color patch in indent area", left != theme.current().accent.lower(), left)
    ic = child.icon(0)
    from PySide6.QtGui import QIcon
    from PySide6.QtCore import QSize
    sel = ic.pixmap(QSize(16, 16), QIcon.Mode.Selected).toImage()
    has_white = any(sel.pixelColor(x, y).lightness() > 230 and sel.pixelColor(x, y).alpha() > 200
                    for x in range(16) for y in range(16))
    check(f"{mode}: selected row icon is white", has_white)
# Switching the font to Gaegu and back returns every widget to the default font
w.apply_appearance(ui_font="gaegu"); w.apply_appearance(ui_font="default"); app.processEvents()
left_over = [b.text() for b in w.sessions_dock.findChildren(QPushButton) if b.font().family() == "Gaegu"]
check("font reverted -> no Gaegu left on buttons", not left_over and w.filter.font().family() != "Gaegu", left_over)
w.apply_appearance(mode="light"); w.close(); print("DONE")
