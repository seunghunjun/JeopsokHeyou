# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Sequences the screen used to get wrong: keyboard-mode CSI with a > / < / = marker (Claude Code's "CSI > 4 ; 2 m"
turned underline + dim on for everything), SGR with ":" sub-parameters (printed as text), and erased cells that
kept the underline (lines across empty rows)."""
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou.terminal import TerminalWidget, clean_sequences, pick_font  # noqa: E402


def check(name, ok, extra=""):
    if callable(extra):                  # details computed (and printed) only when the check fails
        extra = "" if ok else extra()
    print(("PASS " if ok else "FAIL ") + name, extra)


t = TerminalWidget(pick_font("", 11))
t.resize(800, 300)
s = t.screen


def fresh():
    t.feed(b"\x1b[0m\x1b[2J\x1b[H")


def row(y=0, n=12):
    r = s.buffer[y]
    return "".join(r[x].data for x in range(n)), "".join("_" if r[x].underscore else "." for x in range(n))


# ---- keyboard modes are not display attributes
fresh()
t.feed(b"\x1b[>4;2mabcd")
check("CSI > 4;2 m (modifyOtherKeys): no underline, nothing dim", row()[1].startswith("....")
      and not s.cursor.attrs.underscore and not s.buffer[0][0].bold, lambda: row())
fresh()
t.feed(b"\x1b[>1u\x1b[<u\x1b[=1;1uabcd")
check("kitty keyboard push / pop / set: nothing printed", row()[0].startswith("abcd"), lambda: row())
fresh()
t.feed(b"\x1b[>4;")                   # cut in the middle of a chunk
t.feed(b"2mab")
check("... also when the sequence is split between chunks", row()[0].startswith("ab") and row()[1].startswith(".."),
      lambda: row())
check("CSI > c (vim asks the terminal version) is still passed on", clean_sequences("\x1b[>c") == "\x1b[>c")

# ---- ":" sub-parameters
fresh()
t.feed(b"\x1b[4:3mab\x1b[4:0mcd")
check("curly underline 4:3 on, 4:0 off (not printed as text)", row()[0].startswith("abcd")
      and row()[1].startswith("__.."), lambda: row())
fresh()
t.feed(b"\x1b[38:2::255:0:0mab\x1b[58:2::0:255:0mcd\x1b[59mef")
check("38:2::r:g:b colour applied, underline colour ignored", row()[0].startswith("abcdef")
      and s.buffer[0][0].fg.lower() == "ff0000", lambda: (row(), s.buffer[0][0].fg))

# ---- erasing leaves no underline
fresh()
t.feed(b"\x1b[4mab\x1b[K\r\n\x1b[3X\r\n\x1b[J")
check("erase line / characters / display with underline on: blank cells have no underline",
      row(0)[1] == "__.........." and row(1)[1] == "." * 12 and row(2)[1] == "." * 12, lambda: (row(0), row(1), row(2)))
fresh()
t.feed(b"\x1b[44m\x1b[K")
check("... but keep the background colour (as xterm)", s.buffer[0][5].bg == "blue", lambda: s.buffer[0][5].bg)
fresh()
t.feed(b"\x1b[4mx\x1b[24my")
check("plain underline still works", row()[1].startswith("_."), lambda: row())
print("DONE")
