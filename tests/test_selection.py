# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Mouse selection like Windows Terminal / iTerm2: double-click a word, triple-click the whole line
(a long line the screen wrapped counts as one), drag on to add whole words or lines,
and a wrapped line is copied without a line break where the screen wrapped it."""
import os
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou.terminal import TerminalWidget, pick_font  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok:
        fails.append(name)


t = TerminalWidget(pick_font("", 11))
t.resize(400, 300)
t.show()
app.processEvents()
cols = t.screen.columns
long = "".join(chr(ord("a") + i % 26) for i in range(cols * 2 + 5))     # wraps onto three rows
t.feed(b"first line\r\n")
t.feed(("echo " + long + "\r\n").encode())
t.feed(b"last one here\r\n")
s = t.screen
row_first = s.sb_total + 0
row_long = s.sb_total + 1          # the long line takes rows 1, 2 and 3
row_last = s.sb_total + 4


def pos(row, col):
    y = (row - t._top_abs()) * t.ch + t.PAD + t.ch / 2
    return QPointF(t.PAD + col * t.cw + t.cw / 2, y)


def mouse(kind, row, col, button=Qt.MouseButton.LeftButton):
    p = pos(row, col)
    ev = QMouseEvent(kind, p, t.mapToGlobal(p), button,
                     button if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(t, ev)


def click(row, col):
    mouse(QEvent.Type.MouseButtonPress, row, col)
    mouse(QEvent.Type.MouseButtonRelease, row, col)


def double(row, col):
    click(row, col)
    mouse(QEvent.Type.MouseButtonDblClick, row, col)
    mouse(QEvent.Type.MouseButtonRelease, row, col)


clip = QGuiApplication.clipboard

# double-click: a word
double(row_last, 6)
check("double-click selects the word", t.selected_text() == "one" and clip().text() == "one", repr(t.selected_text()))

# triple-click: the whole line
double(row_first, 2)
click(row_first, 2)
check("triple-click selects the whole line", t.selected_text() == "first line", repr(t.selected_text()))

# triple-click on a wrapped line: all of it, with no line break where the screen wrapped it
double(row_long + 1, 3)
click(row_long + 1, 3)
check("triple-click on a wrapped line takes all of it", t.selected_text() == "echo " + long,
      repr(t.selected_text()[:40]))
check("... and copies it as one line", clip().text() == "echo " + long and "\n" not in clip().text())

# drag across a wrapped line: no line break in the middle, real line ends kept
t.sel_anchor, t.sel_end = (row_first, 0), (row_long + 2, cols - 1)
check("selection across a wrapped line keeps only real line breaks",
      t.selected_text() == "first line\necho " + long, repr(t.selected_text()[-20:]))

# a third click that comes too late is a plain click
double(row_first, 2)
t._last_double = (time.monotonic() - 5, row_first)
click(row_first, 2)
check("a late third click is a plain click", t.selected_text() == "", repr(t.selected_text()))

# triple-click then drag down: whole lines are added
double(row_first, 2)
mouse(QEvent.Type.MouseButtonPress, row_first, 2)
mouse(QEvent.Type.MouseMove, row_last, 1)
mouse(QEvent.Type.MouseButtonRelease, row_last, 1)
check("dragging after a triple-click adds whole lines",
      t.selected_text() == "first line\necho " + long + "\nlast one here", repr(t.selected_text()[-20:]))

# double-click then drag: whole words are added
mouse(QEvent.Type.MouseButtonPress, row_last, 1)
mouse(QEvent.Type.MouseButtonRelease, row_last, 1)
mouse(QEvent.Type.MouseButtonDblClick, row_last, 1)
mouse(QEvent.Type.MouseMove, row_last, 6)
mouse(QEvent.Type.MouseButtonRelease, row_last, 6)
check("dragging after a double-click adds whole words", t.selected_text() == "last one", repr(t.selected_text()))

# a plain drag still selects exactly what it covers
t._last_double = None          # (a click right after a double-click would be a triple-click)
mouse(QEvent.Type.MouseButtonPress, row_last, 1)
mouse(QEvent.Type.MouseMove, row_last, 3)
mouse(QEvent.Type.MouseButtonRelease, row_last, 3)
check("a plain drag selects character by character", t.selected_text() == "ast", repr(t.selected_text()))

print(f"{'OK' if not fails else 'FAILED'}")
