# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Re-wrapping long lines when the terminal width changes (reflow)."""
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
import pyte  # noqa: E402

from jeopsokheyou.terminal import TermScreen  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def make(cols=20, lines=6, sb=500):
    s = TermScreen(cols, lines, sb)
    return s, pyte.ByteStream(s)


def rows(s):
    """All rows (scrollback + screen) as (text, wrapped)."""
    out = [("".join(r[x].data for x in range(s.columns)).rstrip(), bool(getattr(r, "wrapped", False)))
           for r in s.scrollback]
    out += [("".join(s.buffer[y][x].data for x in range(s.columns)).rstrip(), bool(getattr(s.buffer[y], "wrapped", False)))
            for y in range(s.lines)]
    return out


def logical(s):
    """Rows joined back into the lines the program printed."""
    res, cur = [], ""
    for text, wrapped in rows(s):
        if wrapped:
            cur += text.ljust(0)
            continue
        res.append(cur + text)
        cur = ""
    while res and res[-1] == "":
        res.pop()
    return res


LONG = "/mdpark/app/doremypa_hp/web/WEB-INF/classes/doremypaweb/edu/service"   # 66 chars
s, st = make(20, 6)
st.feed(("root@host:~# cd " + LONG + "\r\n").encode())
st.feed(b"short line\r\n")
st.feed(b"$ ")
before = logical(s)
check("narrow terminal wraps the long line", len([r for r in rows(s) if r[1]]) >= 4)
s.resize(6, 100)
check("widening joins the wrapped rows into one", rows(s)[-6:][0][0].startswith("root@host:~# cd /mdpark")
      and LONG in "".join(t for t, _ in rows(s)), rows(s)[-6:])
check("text unchanged after widening", logical(s) == before, logical(s))
check("cursor stays after the prompt", (s.cursor.y, s.cursor.x) == (2, 2), (s.cursor.y, s.cursor.x))
s.resize(6, 15)
check("narrowing wraps again without losing text", logical(s) == before, logical(s))
for w in (33, 9, 70, 20, 41):
    s.resize(6, w)
check("many resizes keep the text and add no blank lines", logical(s) == before, logical(s))
check("cursor still after the prompt", "".join(s.buffer[s.cursor.y][x].data for x in range(s.cursor.x)) == "$ ")

# typing a long command: the cursor stays right after the last typed character
s, st = make(20, 6)
st.feed(b"$ echo " + b"y" * 50)      # 57 characters, wraps twice; cursor at its end
for w in (30, 11, 57, 80):
    s.resize(6, w)
    # a row filled exactly leaves the cursor at its end (pending wrap), like xterm
    ok = s.cursor.x == (57 if w >= 57 else 57 % w) and logical(s)[-1] == "$ echo " + "y" * 50
    check(f"typed command keeps the cursor at its end (width {w})", ok, (s.cursor.y, s.cursor.x))

# a real newline is never merged, even when the line exactly fills the width
s, st = make(10, 5)
st.feed(b"0123456789\r\nabc\r\n")
s.resize(5, 30)
check("full-width line ending in a real newline stays separate", logical(s)[:2] == ["0123456789", "abc"], logical(s))

# double-width characters (Korean) are never split
s, st = make(20, 5)
han = "".join(map(chr, range(0xAC00, 0xAC00 + 15)))   # 15 Hangul syllables = 30 cells
st.feed((han + "\r\n").encode())
s.resize(5, 25)
first = s.buffer[0] if not s.scrollback else s.scrollback[0]
cells = [first[x].data for x in range(25)]
check("wide characters are not split across rows", cells[24] in (" ", "") and logical(s)[0] == han, cells[22:])
s.resize(5, 7)
check("odd width keeps every wide character whole", logical(s)[0] == han, logical(s))

# colors survive
s, st = make(10, 5)
st.feed(b"\x1b[31m" + b"R" * 25 + b"\x1b[0m\r\n")
s.resize(5, 40)
check("colors are kept", s.buffer[0][0].fg == "red" and s.buffer[0][24].fg == "red" and s.buffer[0][24].data == "R")

# scrollback is re-wrapped too, and the absolute row counter stays consistent
s, st = make(20, 5, sb=100)
for i in range(60):
    st.feed((f"line-{i:02d}-" + "x" * 30 + "\r\n").encode())
base = s.sb_total - len(s.scrollback)
s.resize(5, 80)
check("scrollback lines joined", all(len(t) == 38 for t in logical(s)[-10:]), logical(s)[-3:])
check("row counter consistent", s.sb_total - len(s.scrollback) == base)
s.resize(5, 13)
check("scrollback limit respected", len(s.scrollback) <= 100)
check("newest lines kept intact", logical(s)[-1] == "line-59-" + "x" * 30, logical(s)[-1])

# clearing to the end of a row removes the 'continues' mark (shell redraws the command line)
s, st = make(10, 5)
st.feed(b"abcdefghijklmno")       # wraps once
st.feed(b"\x1b[1;1H\x1b[K")       # cursor to row 1 and clear it
check("erase clears the wrap mark", rows(s)[0][1] is False)

# full-screen programs (alternate screen) are not reflowed
s, st = make(20, 5)
st.feed(b"\x1b[?1049h" + b"A" * 30)
s.resize(5, 40)
check("alternate screen is left alone", s.alt is not None and "".join(s.buffer[0][x].data for x in range(40)).strip() == "A" * 20)
st.feed(b"\x1b[?1049l")

# turned off in Settings: old behavior (no re-wrapping)
s, st = make(20, 5)
s.reflow = False
st.feed((LONG + "\r\n").encode())
s.resize(5, 100)
check("reflow can be turned off", rows(s)[0][0] == LONG[:20], rows(s)[0][0])
print("DONE")
