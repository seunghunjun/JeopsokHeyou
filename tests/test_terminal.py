# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys; TESTS = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from PySide6.QtWidgets import QApplication
app = QApplication([])
from jeopsokheyou.terminal import TerminalWidget, pick_font, MODE_DECCKM, MODE_BRACKETED
t = TerminalWidget(pick_font("", 11)); t.resize(800, 400); t.show(); app.processEvents()
s = t.screen
print("font", t.term_font.family(), "cell", t.cw, t.ch, "size", s.columns, s.lines)
sent=[]; t.writer = sent.append
cwd=[]; t.cwd_changed.connect(cwd.append)
for i in range(100): t.feed(f"line {i}\r\n".encode())
print("scrollback", len(s.scrollback), "sb_total", s.sb_total)
t.feed("日本語 テスト \x1b[31m赤色\x1b[0m \x1b[38;5;208m橙色\x1b[0m \x1b[1;32mbold\x1b[0m\r\n".encode())
line = s.buffer[s.cursor.y-1]; print("wide:", repr("".join(line[x].data or "_" for x in range(12))))
t.feed(b"\x1b]7;/home/us"); t.feed(b"er/proj\x07"); print("osc7", cwd)
t.feed(b"\x1b]7;file://host/var/log\x1b\\"); print("osc7 file", cwd)
t.feed(b"\x1b[?1049h\x1b[2J\x1b[Hvim screen"); print("alt", s.alt is not None, repr(s.display[0][:12]))
t.feed(b"\x1b[?1049l"); print("alt off", s.alt is None, repr(s.display[s.cursor.y][:10]))
t.feed(b"\x1b[?1h\x1b[?2004h"); print("decckm", MODE_DECCKM in s.mode, "bracketed", MODE_BRACKETED in s.mode)
t.feed(b"\x1b[6n"); print("CPR reply", sent[-1])
t.scroll_lines(10); img = t.grab(); print("paint ok (scrolled)", img.width())
t.sel_anchor=(s.sb_total-3,0); t.sel_end=(s.sb_total-1,5); print("sel", repr(t.selected_text())); t.grab()
t.scroll_lines(-100)
t.resize(500, 200); [app.processEvents() or __import__("time").sleep(0.02) for _ in range(10)]; print("resized", s.columns, s.lines, "cursor", s.cursor.y)
t.resize(1000, 600); [app.processEvents() or __import__("time").sleep(0.02) for _ in range(10)]; print("resized", s.columns, s.lines)
t.paste_text("a\nb"); print("paste", sent[-1])
from PySide6.QtGui import QKeyEvent, QGuiApplication; from PySide6.QtCore import Qt, QEvent
import jeopsokheyou.terminal as term
# physical Control key: MetaModifier on macOS, ControlModifier elsewhere
CTRL = Qt.KeyboardModifier.MetaModifier if sys.platform == "darwin" else Qt.KeyboardModifier.ControlModifier
fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)
def press(k, m, txt=""):
    n = len(sent); app.sendEvent(t, QKeyEvent(QEvent.KeyPress, k, m, txt)); return b"".join(sent[n:])
for k,m,txt in [(Qt.Key_Up,Qt.NoModifier,""),(Qt.Key_C,CTRL,"\x03"),(Qt.Key_Right,CTRL,""),(Qt.Key_F5,Qt.NoModifier,""),(Qt.Key_Tab,Qt.NoModifier,"\t")]:
    app.sendEvent(t, QKeyEvent(QEvent.KeyPress,k,m,txt))
print("keys", sent[-5:])
check("ctrl+c -> ^C", sent[-4] == b"\x03")
check("ctrl+right -> CSI 1;5C", sent[-3] == b"\x1b[1;5C")

# macOS branch (forced via the module attribute so it runs on every OS)
saved_mac = term.IS_MAC
try:
    term.IS_MAC = True
    M, CMD, ALT = Qt.KeyboardModifier.MetaModifier, Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier
    SHIFT = Qt.KeyboardModifier.ShiftModifier
    check("mac: Control(Meta)+C -> ^C", press(Qt.Key_C, M, "c") == b"\x03")
    check("mac: Control(Meta)+D -> ^D", press(Qt.Key_D, M, "\x04") == b"\x04")
    check("mac: Control(Meta)+Z -> ^Z", press(Qt.Key_Z, M, "") == b"\x1a")
    check("mac: Control(Meta)+[ -> ESC", press(Qt.Key_BracketLeft, M, "") == b"\x1b")
    check("mac: Control(Meta)+Right -> CSI 1;5C", press(Qt.Key_Right, M, "") == b"\x1b[1;5C")
    t.sel_anchor = (s.sb_total, 0); t.sel_end = (s.sb_total, 3)
    QGuiApplication.clipboard().setText("")
    out = press(Qt.Key_C, CMD, "c")
    check("mac: Cmd+C copies selection, sends nothing", out == b"" and QGuiApplication.clipboard().text() == t.selected_text() != "")
    QGuiApplication.clipboard().setText("")
    out = press(Qt.Key_C, CMD | SHIFT, "C")
    check("mac: Cmd+Shift+C copies selection", out == b"" and QGuiApplication.clipboard().text() == t.selected_text())
    QGuiApplication.clipboard().setText("pasted")
    check("mac: Cmd+V pastes (bracketed)", press(Qt.Key_V, CMD, "v") == b"\x1b[200~pasted\x1b[201~")
    check("mac: Cmd+Shift+V pastes", press(Qt.Key_V, CMD | SHIFT, "V") == b"\x1b[200~pasted\x1b[201~")
    check("mac: Cmd+K sends nothing", press(Qt.Key_K, CMD, "k") == b"")
    check("mac: Cmd+Left sends nothing", press(Qt.Key_Left, CMD, "") == b"")
    zoom = []; t.font_zoom.connect(zoom.append)
    press(Qt.Key_Equal, CMD, "="); press(Qt.Key_Minus, CMD, "-")
    check("mac: Cmd+= / Cmd+- zoom", zoom == [1, -1])
    t.font_zoom.disconnect(zoom.append)
    check("mac: Option+a text without ESC", press(Qt.Key_A, ALT, "å") == "å".encode())
finally:
    term.IS_MAC = saved_mac

# Windows branch
term.IS_MAC = False
try:
    C, ALT = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier
    check("win: Ctrl+C -> ^C", press(Qt.Key_C, C, "\x03") == b"\x03")
    check("win: Alt+x -> ESC x", press(Qt.Key_X, ALT, "x") == b"\x1bx")
    t.sel_anchor = (s.sb_total, 0); t.sel_end = (s.sb_total, 3)
    QGuiApplication.clipboard().setText("")
    out = press(Qt.Key_C, C | Qt.KeyboardModifier.ShiftModifier, "C")
    check("win: Ctrl+Shift+C copies selection", out == b"" and QGuiApplication.clipboard().text() == t.selected_text() != "")
    zoom = []; t.font_zoom.connect(zoom.append)
    press(Qt.Key_Equal, C, "="); press(Qt.Key_Minus, C, "-")
    check("win: Ctrl+= / Ctrl+- zoom", zoom == [1, -1])
    t.font_zoom.disconnect(zoom.append)
finally:
    term.IS_MAC = saved_mac

t.grab()
if not fails: print("OK")
