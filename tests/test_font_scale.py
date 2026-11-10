# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Moving between screens of different scales (or a remote desktop reconnecting) must not squeeze the letters: the
cell width is measured from the plain font every time, not from the font already fitted to the last scale."""
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou.terminal import TerminalWidget, pick_font  # noqa: E402


def check(name, ok, extra=""):
    if callable(extra):                  # details computed (and printed) only when the check fails
        extra = "" if ok else extra()
    print(("PASS " if ok else "FAIL ") + name, extra)


for size in (10, 11, 13):
    t = TerminalWidget(pick_font("", size))
    scale = [1.5]
    t._dpr = lambda: scale[0]
    t.set_font(t.term_font)
    first = t.cw
    seen = []
    for s in (2.0, 1.5, 1.5, 2.0, 1.0, 1.75, 1.25, 1.5, 2.0, 1.0, 1.5) * 3:
        scale[0] = s
        t.set_font(t.term_font)          # what a repaint does when the scale changed
        seen.append(round(t.cw, 3))
    check(f"size {size}: back at 150 % the cells are as wide as before", abs(t.cw - first) < 1e-6,
          lambda: (first, t.cw, seen))
print("DONE")
