# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys, shutil
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")   # test work folder (git-ignored)
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata"); shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from PySide6.QtWidgets import QApplication
app = QApplication([])
from jeopsokheyou import theme, config
from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme
from jeopsokheyou.dialogs import SettingsDialog
def check(n, ok, x=""): print(("PASS " if ok else "FAIL ") + n, x)
apply_dark_theme(app)
check("default = light", theme.current().name == "light")
w = MainWindow(); w.show()
d = SettingsDialog(w.settings, w.term_font, w)
d.mode.setCurrentIndex(d.mode.findData("dark")); d.ui_font.setCurrentIndex(d.ui_font.findData("gaegu"))
check("selection previews immediately (dark + Gaegu)", theme.current().name == "dark" and "Gaegu" in app.font().families(), app.font().families()[:1])
d.reject()
check("cancel -> reverted", theme.current().name == "light" and "Gaegu" not in app.font().families())
d = SettingsDialog(w.settings, w.term_font, w)
d.mode.setCurrentIndex(d.mode.findData("dark")); d.ui_font.setCurrentIndex(d.ui_font.findData("gaegu")); d.term_size.setValue(14)
v = d.values(); d.accept(); w.term_font = w.term_font; w.apply_appearance(mode=v["theme"], ui_font=v["ui_font"])
st = config.load_settings()
check("OK -> saved", st["theme"] == "dark" and st["ui_font"] == "gaegu", (st.get("theme"), st.get("ui_font")))
check("menu check marks in sync", w._theme_actions["dark"].isChecked() and w._font_actions["gaegu"].isChecked())
check("Gaegu font registered", "Gaegu" in __import__("PySide6.QtGui", fromlist=["QFontDatabase"]).QFontDatabase.families())
w.close(); print("DONE")
