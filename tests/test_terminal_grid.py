# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Text stays on the cell grid: the cursor sits right after the last character, whatever the font size
(glyphs are fractional pixels wide, cells are whole screen pixels — like Windows Terminal, so at 150 % the
text is not spread out). Runs again at 150 % so machines at 100 % check that too."""
import os
import subprocess
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
if sys.platform == "win32":
    os.environ["QT_QPA_PLATFORM"] = "windows"   # real glyph widths (offscreen rounds them); no window is shown
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtGui import QColor, QFontMetricsF, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou.terminal import TerminalWidget, pick_font  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


PROMPT = "[root@localhost ~]# vbvbv"
for family, size in (("Cascadia Mono", 12), ("Consolas", 11), ("Courier New", 13), ("Cascadia Mono", 15), ("", 10)):
    t = TerminalWidget(pick_font(family, size))
    t.resize(900, 200)
    scale = QGuiApplication.primaryScreen().devicePixelRatio()
    name = f"{t.term_font.family()} {size} @{int(scale * 100)}%"
    glyph = QFontMetricsF(pick_font(family, size)).horizontalAdvance("M") * scale
    check(f"{name}: a cell is whole screen pixels, the glyph width rounded (not rounded up in widget pixels)",
          abs(t.cw * scale - round(glyph)) < 1e-6 and abs(t.cw * scale - glyph) <= 0.5, (t.cw * scale, glyph))
    for f in (t.term_font, t.bold_font):
        # a run of letters (drawn as one piece) ends on its cell, within a quarter of a screen pixel
        piece = PROMPT[:t.RUN]
        drift = (QFontMetricsF(f).horizontalAdvance(piece) - len(piece) * t.cw) * scale
        check(f"{name}: text width matches the cells ({'bold' if f.bold() else 'regular'})", abs(drift) < 0.25, drift)
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
if not os.environ.get("QT_SCALE_FACTOR"):
    out = subprocess.run([sys.executable, __file__], env=dict(os.environ, QT_SCALE_FACTOR="1.5"),
                         capture_output=True, text=True, encoding="utf-8").stdout
    for line in out.splitlines():
        if line.startswith(("PASS", "FAIL")):
            print(line)
print("DONE")
