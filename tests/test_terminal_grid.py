# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Text stays on the cell grid: the cursor sits right after the last character, whatever the font size
(glyphs are fractional pixels wide, cells are whole pixels)."""
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
if sys.platform == "win32":
    os.environ["QT_QPA_PLATFORM"] = "windows"   # real glyph widths (offscreen rounds them); no window is shown
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtGui import QColor, QFontMetricsF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou.terminal import TerminalWidget, pick_font  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


PROMPT = "[root@localhost ~]# vbvbv"
for family, size in (("Cascadia Mono", 12), ("Consolas", 11), ("Courier New", 13), ("Cascadia Mono", 15), ("", 10)):
    t = TerminalWidget(pick_font(family, size))
    t.resize(900, 200)
    name = f"{t.term_font.family()} {size}"
    for f in (t.term_font, t.bold_font):
        drift = QFontMetricsF(f).horizontalAdvance(PROMPT) - len(PROMPT) * t.cw
        check(f"{name}: text width matches the cells ({'bold' if f.bold() else 'regular'})", abs(drift) < 0.01, drift)
    t.feed(PROMPT.encode())
    app.processEvents()
    img = t.grab().toImage()
    dpr = img.devicePixelRatio()
    row_y = int((t.PAD + t.ch // 2) * dpr)
    cur_x = int((t.PAD + t.screen.cursor.x * t.cw) * dpr)
    bg = QColor(t.bg_default)
    # right edge of the drawn text on the prompt row (left of the cursor block)
    last_ink = 0
    for x in range(int(t.PAD * dpr), cur_x):
        for dy in range(-int(t.ch * dpr / 3), int(t.ch * dpr / 3)):
            c = img.pixelColor(x, row_y + dy)
            if abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue()) > 120:
                last_ink = x
                break
    gap_cells = (cur_x - last_ink) / (t.cw * dpr)
    check(f"{name}: cursor right after the text", 0 <= gap_cells < 0.6, round(gap_cells, 2))
    t.close()
print("DONE")
