# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Shortcuts follow Windows Terminal / iTerm2, never clash, leave the shell its keys, and are listed in Help."""
import os
import shutil
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "shortcuts")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtGui import QAction, QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou import shortcuts  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


for mac in (False, True):
    system = "macOS" if mac else "Windows"
    shortcuts.IS_MAC = mac
    seen, clash = {}, []
    for sid in shortcuts.KEYS:
        for k in shortcuts.keys(sid):
            s = k.toString(QKeySequence.SequenceFormat.PortableText)
            if s in seen and seen[s] != sid:
                clash.append((s, seen[s], sid))
            seen[s] = sid
    check(f"{system}: no key used twice", not clash, clash)
    # keys the shell needs must never be taken: Ctrl+letter (Control+letter on macOS), F1-F12, Ctrl+/
    shell = [f"{'Meta' if mac else 'Ctrl'}+{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + \
            [f"F{n}" for n in range(1, 13)] + (["Ctrl+/"] if not mac else [])
    taken = [k for k in shell if k in seen]
    check(f"{system}: shell keys stay with the server", not taken, taken)
shortcuts.IS_MAC = False

win = {sid: shortcuts.KEYS[sid][0] for sid in shortcuts.KEYS}
mac = {sid: shortcuts.KEYS[sid][1] for sid in shortcuts.KEYS}
check("Windows Terminal keys", win["split_lr"][0] == "Alt+Shift+=" and win["split_tb"][0] == "Alt+Shift+-"
      and win["duplicate_tab"][0] == "Ctrl+Shift+T" and win["close_pane"][0] == "Ctrl+Shift+W"
      and win["find"][0] == "Ctrl+Shift+F" and win["tab_1"][0] == "Ctrl+Alt+1")
check("iTerm2 keys (Ctrl = Command)", mac["split_lr"][0] == "Ctrl+D" and mac["split_tb"][0] == "Ctrl+Shift+D"
      and mac["duplicate_tab"][0] == "Ctrl+T" and mac["close_pane"][0] == "Ctrl+W" and mac["find"][0] == "Ctrl+F"
      and mac["next_tab"][0] == "Ctrl+Shift+]" and mac["tab_1"][0] == "Ctrl+1")
check("old keys keep working", "Ctrl+Shift+D" in win["split_lr"] and "Ctrl+Shift+E" in win["split_tb"]
      and "Ctrl+Shift+G" in win["find"])

w = MainWindow()
w.show()
acts = {a.text(): a for a in w.findChildren(QAction)}
split = next(a for t, a in acts.items() if t.startswith("Split horizontally"))
check("menu action carries all its keys", [k.toString() for k in split.shortcuts()] == ["Alt+Shift+=", "Alt+Shift++", "Ctrl+Shift+D"],
      [k.toString() for k in split.shortcuts()])
check("Help menu has Keyboard shortcuts", "Keyboard shortcuts" in acts)

from jeopsokheyou.dialogs import ShortcutsDialog  # noqa: E402

d = ShortcutsDialog(w)
rows = dict(d.rows())
# key names as this system writes them (Ctrl+Alt+1 is ⌥⌘1 when the tests run on macOS)
check("dialog lists actions with this system's keys", rows.get("Split left/right") == shortcuts.text("split_lr")
      and rows.get("Go to tab 1–9 (9 = last)") == shortcuts.text("tab_1"), rows.get("Go to tab 1–9 (9 = last)"))
if sys.platform != "darwin":
    check("... Windows Terminal keys", rows.get("Split left/right", "").startswith("Alt+Shift+=")
          and rows.get("Go to tab 1–9 (9 = last)") == "Ctrl+Alt+1–9", rows.get("Go to tab 1–9 (9 = last)"))
check("dialog lists terminal keys", rows.get("Copy the selection") == "Ctrl+Shift+C / Ctrl+Insert")
d.close()

for name in ("a", "b", "c"):
    s = Session(host="192.0.2.1", name=name, auth="key", user="u")   # no password prompt in a test
    w.store.upsert(s)
    w.open_session(s)
w.go_to_tab(2)
check("go to tab 2 (Home not counted)", w.tabs.currentWidget().session.name == "b")
w.go_to_tab(9)
check("tab 9 is the last tab", w.tabs.currentWidget().session.name == "c")
w.go_to_tab(7)
check("missing tab number does nothing", w.tabs.currentWidget().session.name == "c")
w.close()
print("DONE")
