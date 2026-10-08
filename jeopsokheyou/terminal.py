# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""pyte-based terminal emulator widget.

- xterm-256color, scrollback, vim/less alternate screen (1049), bracketed paste (2004)
- IME composition input (Korean etc.), selectable server encoding (utf-8/euc-kr, ...)
- PuTTY-style controls: drag-select = auto copy, right-click = paste
- Detects OSC 7 (current directory notification) to sync with the file explorer
"""
from __future__ import annotations

import codecs
import copy
import math
import re
import sys
from collections import defaultdict, deque
from typing import Callable

import pyte
from pyte.screens import Margins
from PySide6.QtCore import QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication,
                           QKeyEvent, QPainter, QPen)
from PySide6.QtWidgets import QScrollBar, QWidget

# On macOS Qt maps ControlModifier to Command and MetaModifier to the physical Control key.
IS_MAC = sys.platform == "darwin"

ALT_MODES = {47, 1047, 1049}
MODE_DECCKM = 1 << 5          # cursor-key application mode (private 1)
MODE_BRACKETED = 2004 << 5    # bracketed paste (private 2004)

PALETTE = {
    "black": "#1d1f21", "red": "#e06c75", "green": "#98c379", "brown": "#e5c07b",
    "blue": "#61afef", "magenta": "#c678dd", "cyan": "#56b6c2", "white": "#d0d0d0",
    "brightblack": "#5c6370", "brightred": "#ff7b86", "brightgreen": "#b5e890",
    "brightbrown": "#ffd68a", "brightblue": "#7cc3ff", "brightmagenta": "#de94f5",
    "brightcyan": "#6fd6e3", "brightwhite": "#ffffff",
}
DEFAULT_FG = "#E5E5EA"
DEFAULT_BG = "#1C1C1E"
SELECTION_BG = "#2F5C99"
CURSOR_COLOR = "#F2F2F7"

OSC7_RE = re.compile(r"\x1b\]7;([^\x07\x1b]*)(?:\x07|\x1b\\)")


class TermScreen(pyte.Screen):
    """Screen with scrollback, alternate screen and response (DA/CPR) callbacks."""

    def __init__(self, columns: int, lines: int, scrollback: int = 5000):
        self.scrollback: deque = deque(maxlen=scrollback)
        self.reflow = True           # re-wrap long lines when the width changes (Settings can turn it off)
        self._drawing = False        # inside draw(): a line feed there is a soft wrap, not a real newline
        self.sb_total = 0            # total lines pushed into scrollback so far (basis for absolute row numbers)
        self.alt = None              # (saved main-screen buffer, cursor)
        self.responder: Callable[[str], None] | None = None
        self.on_title: Callable[[str], None] | None = None
        super().__init__(columns, lines)

    # --- scrollback
    def index(self) -> None:
        top, bottom = self.margins or Margins(0, self.lines - 1)
        if self.alt is None and top == 0 and self.cursor.y == bottom:
            self.scrollback.append(self.buffer[top])
            self.sb_total += 1
        super().index()

    # --- soft wraps: remember which rows continue on the next row (needed to re-wrap on resize)
    def draw(self, data: str) -> None:
        self._drawing = True
        try:
            super().draw(data)
        finally:
            self._drawing = False

    def linefeed(self) -> None:
        if self._drawing:   # pyte wraps inside draw() with carriage_return() + linefeed()
            self.buffer[self.cursor.y].wrapped = True
        super().linefeed()

    def erase_in_line(self, how: int = 0, private: bool = False) -> None:
        super().erase_in_line(how, private)
        if how in (0, 2):   # the end of the row was cleared: it no longer continues on the next row
            self.buffer[self.cursor.y].wrapped = False

    def erase_in_display(self, how: int = 0, *args, **kwargs) -> None:
        super().erase_in_display(how, *args, **kwargs)
        if how == 3:
            self.scrollback.clear()

    # --- alternate screen (vim, less, htop ...)
    def set_mode(self, *modes, **kwargs) -> None:
        if kwargs.get("private") and ALT_MODES & set(modes):
            if self.alt is None:
                self.alt = (self.buffer, copy.copy(self.cursor))
                self.buffer = defaultdict(self.buffer.default_factory)
                self.dirty.update(range(self.lines))
            modes = tuple(m for m in modes if m not in ALT_MODES)
            if not modes:
                return
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes, **kwargs) -> None:
        if kwargs.get("private") and ALT_MODES & set(modes):
            if self.alt is not None:
                self.buffer, cur = self.alt
                self.alt = None
                cur.x = min(cur.x, self.columns - 1)
                cur.y = min(cur.y, self.lines - 1)
                self.cursor = cur
                self.dirty.update(range(self.lines))
            modes = tuple(m for m in modes if m not in ALT_MODES)
            if not modes:
                return
        super().reset_mode(*modes, **kwargs)

    # --- reflow: when the width changes, join soft-wrapped rows and wrap them again at the new width
    def _new_row(self, cells, wrapped: bool):
        row = pyte.screens.StaticDefaultDict(self.default_char)
        for x, c in enumerate(cells):
            row[x] = c
        row.wrapped = wrapped
        return row

    def _row_cells(self, row, width: int, keep_all: bool) -> list:
        cells = [row[x] for x in range(width)]
        if not keep_all:   # a real line end: drop the blank padding after the text
            while cells and cells[-1].data in (" ", "") and cells[-1].bg == "default" and not cells[-1].reverse:
                cells.pop()
        return cells

    def _reflow(self, columns: int) -> None:
        old_cols = self.columns
        last = self.cursor.y   # rows below the cursor only count when they hold text
        for y in range(self.lines - 1, self.cursor.y, -1):
            if y in self.buffer and any(c.data.strip() for c in self.buffer[y].values()):
                last = y
                break
        rows = list(self.scrollback) + [self.buffer[y] for y in range(last + 1)]
        cursor_row = len(self.scrollback) + self.cursor.y
        # 1) logical lines (soft-wrapped rows joined) and the cursor's place in them
        logical, cur, cursor_at = [], [], (0, 0)
        for i, row in enumerate(rows):
            wrapped = bool(getattr(row, "wrapped", False))
            if i == cursor_row:
                cursor_at = (len(logical), len(cur) + self.cursor.x)
            cur.extend(self._row_cells(row, old_cols, keep_all=wrapped))   # the cursor's place is kept separately
            if not wrapped:
                logical.append(cur)
                cur = []
        if cur:
            logical.append(cur)
        # 2) wrap again at the new width (a double-width character is never split)
        new_rows, cursor_pos = [], (0, 0)
        for li, cells in enumerate(logical):
            start = len(new_rows)
            offsets = []   # cell index -> (row, x)
            row, x = [], 0
            i = 0
            while i < len(cells):
                c = cells[i]
                wide = c.data != "" and i + 1 < len(cells) and cells[i + 1].data == ""
                need = 2 if wide else 1
                if x + need > columns:
                    new_rows.append(self._new_row(row, True))
                    row, x = [], 0
                offsets.append((len(new_rows), x))
                row.append(c)
                x += 1
                if wide:
                    offsets.append((len(new_rows), x))
                    row.append(cells[i + 1])
                    x += 1
                    i += 1
                i += 1
            new_rows.append(self._new_row(row, False))
            if li == cursor_at[0]:
                o = cursor_at[1]
                if o < len(offsets):
                    cursor_pos = offsets[o]
                else:   # past the text (e.g. after the prompt's trailing space)
                    extra = o - len(cells)
                    r, cx = (offsets[-1][0], offsets[-1][1] + 1) if offsets else (start, 0)
                    cx += extra
                    while cx > columns:
                        cx -= columns
                        r += 1
                    cursor_pos = (r, cx)
        while cursor_pos[0] >= len(new_rows):
            new_rows.append(self._new_row([], False))
        # 3) the last screenful (keeping the cursor visible) becomes the screen, the rest scrollback
        cy = cursor_pos[0]
        top = max(0, len(new_rows) - self.lines)
        top = min(top, cy)
        top = max(top, cy - self.lines + 1)
        discarded = self.sb_total - len(self.scrollback)
        self.scrollback.clear()
        self.scrollback.extend(new_rows[:top])
        self.sb_total = discarded + top
        self.buffer.clear()
        for y, row in enumerate(new_rows[top:top + self.lines]):
            self.buffer[y] = row
        self.cursor.y = cy - top
        self.cursor.x = min(cursor_pos[1], columns)
        self.columns = columns
        self.set_margins()
        self.dirty.update(range(self.lines))

    # --- resize: trim below the cursor; lines pushed off the top go to scrollback
    def resize(self, lines=None, columns=None) -> None:
        lines = lines or self.lines
        columns = columns or self.columns
        if columns != self.columns and self.reflow and self.alt is None:
            try:
                self._reflow(columns)
            except Exception:
                pass   # never lose the session over a layout problem — fall back to plain resizing
        if lines < self.lines:
            drop = max(0, self.cursor.y + 1 - lines)
            old = self.lines
            if drop:
                if self.alt is None:
                    for y in range(drop):
                        self.scrollback.append(self.buffer[y])
                        self.sb_total += 1
                moved = {y - drop: self.buffer[y] for y in range(drop, old) if y in self.buffer}
                self.buffer.clear()
                self.buffer.update(moved)
                self.cursor.y -= drop
            for y in range(lines, old):
                self.buffer.pop(y, None)
            self.lines = lines
        if columns == self.columns and lines == self.lines:
            self.set_margins()
            self.dirty.update(range(lines))
            return
        super().resize(lines, columns)

    def write_process_input(self, data: str) -> None:
        if self.responder:
            self.responder(data)

    def set_title(self, param: str) -> None:
        super().set_title(param)
        if self.on_title:
            self.on_title(param)


def pick_font(family: str = "", size: int = 11) -> QFont:
    families = set(QFontDatabase.families())
    for cand in ([family] if family else []) + ["D2Coding", "D2Coding ligature", "NanumGothicCoding",
                                                "Cascadia Mono", "Consolas", "SF Mono", "Menlo", "Monaco",
                                                "Courier New"]:
        if cand and cand in families:
            family = cand
            break
    f = QFont(family, size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    f.setKerning(False)
    return f


class TerminalWidget(QWidget):
    title_changed = Signal(str)
    cwd_changed = Signal(str)
    reconnect_requested = Signal()
    font_zoom = Signal(int)

    SB_W = 10
    PAD = 8     # padding between text and widget edges

    def __init__(self, font: QFont, scrollback: int = 5000, encoding: str = "utf-8", parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(False)
        self.setCursor(Qt.CursorShape.IBeamCursor)

        self.writer: Callable[[bytes], None] | None = None
        self.on_resize: Callable[[int, int], None] | None = None
        self.disconnected = False

        self.screen = TermScreen(80, 24, scrollback)
        self.screen.responder = lambda s: self.send_text(s)
        self.screen.on_title = lambda t: self.title_changed.emit(t)
        self.stream = pyte.Stream(self.screen)
        self.set_encoding(encoding)
        self._osc_pending = ""
        # shell state (known only after receiving OSC 7 — when the bash/zsh hook was injected)
        self.cwd = ""
        self.at_prompt = False      # waiting for input at the prompt?
        self.input_dirty = False    # has the user typed something at the prompt?
        self.prompt_start = 0       # absolute row where the current prompt starts

        self.scroll_offset = 0
        self.sel_anchor = None   # (abs_row, col)
        self.sel_end = None
        self._selecting = False
        self.preedit = ""

        self._colors: dict[str, QColor] = {}
        self.palette_hex = dict(PALETTE)
        self.fg_default = QColor(DEFAULT_FG)
        self.bg_default = QColor(DEFAULT_BG)
        self.cursor_color = QColor(CURSOR_COLOR)
        self.selection_color = QColor(SELECTION_BG)
        # find in terminal
        self.search_query = ""
        self.search_hits: list[tuple[int, int, int]] = []   # (abs_row, first_col, last_col)
        self.search_index = -1
        self._search_bar = None
        # keyword highlighting (highlights.compile_rules) and session log (sessionlog.SessionLog)
        self.highlight_rules: list = []
        self.logger = None

        self.sbar = QScrollBar(Qt.Orientation.Vertical, self)
        self.sbar.valueChanged.connect(self._on_scrollbar)
        self.sbar.setStyleSheet("QScrollBar{background:#1C1C1E;width:10px;margin:2px}"
                                "QScrollBar::handle{background:#4a4d52;border-radius:4px;min-height:24px}"
                                "QScrollBar::add-line,QScrollBar::sub-line{height:0}")

        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.setInterval(12)
        self._repaint_timer.timeout.connect(self._flush_repaint)
        self._pty_timer = QTimer(self)
        self._pty_timer.setSingleShot(True)
        self._pty_timer.setInterval(60)
        self._pty_timer.timeout.connect(self._emit_resize)
        self._want_size = (24, 80)

        self.set_font(font)

    # ------------------------------------------------------------ settings
    def set_encoding(self, enc: str) -> None:
        try:
            codecs.lookup(enc)
        except LookupError:
            enc = "utf-8"
        self.encoding = enc
        self._decoder = codecs.getincrementaldecoder(enc)(errors="replace")

    def set_font(self, font: QFont) -> None:
        self.term_font = QFont(font)
        self.bold_font = QFont(font)
        self.bold_font.setBold(True)
        fm = QFontMetricsF(self.term_font)
        self.cw = max(1, math.ceil(fm.horizontalAdvance("M")))
        # Cells are whole pixels but glyphs are not (e.g. 9.375 px): stretch each letter to the cell width so
        # a run of text stays on the grid and the cursor sits right after the last character.
        for f in (self.term_font, self.bold_font):
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                               self.cw - QFontMetricsF(f).horizontalAdvance("M"))
        self.ch = max(1, math.ceil(fm.lineSpacing()))
        self.ascent = fm.ascent()
        self._recalc_size()
        self.update()

    # ------------------------------------------------------------ I/O
    def feed(self, data: bytes) -> None:
        text = self._osc_pending + self._decoder.decode(data)
        self._osc_pending = ""
        if not text:
            return
        if self.logger is not None:
            try:
                self.logger.write(text)
            except OSError:
                self.logger = None    # disk full / folder removed: stop logging, keep the session
        # an incomplete OSC 7 at the end of a chunk is joined with the next chunk
        tail = text.rfind("\x1b]7;")
        if tail >= 0 and OSC7_RE.match(text, tail) is None and len(text) - tail < 4096:
            self._osc_pending = text[tail:]
            text = text[:tail]
        before = self.screen.sb_total
        pos = 0
        for m in OSC7_RE.finditer(text):
            # feed everything up to the OSC 7 first so the "prompt start row" is exact
            self.stream.feed(text[pos:m.end()])
            pos = m.end()
            self._on_osc7(m.group(1))
        self.stream.feed(text[pos:])
        grew = self.screen.sb_total - before
        if self.scroll_offset and grew:
            # keep the viewed position while the user is scrolled up
            self.scroll_offset = min(self.scroll_offset + grew, len(self.screen.scrollback))
        if self.screen.alt is not None:
            self.scroll_offset = 0
        self._schedule_repaint()

    def write_local(self, text: str) -> None:
        """Print an app-local message (not from the server) to the screen."""
        self.stream.feed(text.replace("\n", "\r\n"))
        self.scroll_offset = 0
        self._schedule_repaint()

    def _on_osc7(self, path: str) -> None:
        """Current-directory notification the shell sends right before showing the prompt."""
        if path.startswith("file://"):
            path = path[7:]
            slash = path.find("/")
            path = path[slash:] if slash >= 0 else "/"
        if not path:
            return
        self.cwd = path
        self.at_prompt = True
        self.input_dirty = False
        self.prompt_start = self.screen.sb_total + self.screen.cursor.y
        self.cwd_changed.emit(path)

    def _note_user_input(self, text: str) -> None:
        """Track user input: Enter means a command is running, anything else means 'typing'."""
        if "\r" in text:
            self.at_prompt = False
            self.input_dirty = False
        else:
            self.input_dirty = True

    def send_text(self, text: str) -> None:
        self.send_bytes(text.encode(self.encoding, errors="replace"))

    def send_bytes(self, data: bytes) -> None:
        if self.writer and not self.disconnected:
            if self.scroll_offset:
                self.scroll_offset = 0
                self._schedule_repaint()
            self.writer(data)

    def paste_text(self, text: str) -> None:
        if not text:
            return
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        self._note_user_input(text)
        if MODE_BRACKETED in self.screen.mode:
            text = "\x1b[200~" + text + "\x1b[201~"
        self.send_text(text)

    # ------------------------------------------------------------ size
    def _recalc_size(self) -> None:
        w = max(1, self.width() - self.SB_W - 2 * self.PAD)
        cols = max(10, w // self.cw)
        rows = max(3, (self.height() - 2 * self.PAD) // self.ch)
        self._want_size = (rows, cols)
        if cols != self.screen.columns or rows != self.screen.lines:
            # apply once after the layout settles (60ms) so transient small sizes
            # during split/window moves don't truncate the screen content
            self._pty_timer.start()
        self.sbar.setGeometry(self.width() - self.SB_W, 0, self.SB_W, self.height())
        self._update_scrollbar()

    def _emit_resize(self) -> None:
        rows, cols = self._want_size
        if cols == self.screen.columns and rows == self.screen.lines:
            return
        self.screen.resize(rows, cols)
        self._update_scrollbar()
        self.update()
        if self.on_resize:
            self.on_resize(self.screen.columns, self.screen.lines)

    def resizeEvent(self, e):
        self._recalc_size()
        if self._search_bar is not None and self._search_bar.isVisible():
            self._search_bar.place()
        super().resizeEvent(e)

    # ------------------------------------------------------------ scrolling
    def _update_scrollbar(self) -> None:
        n = len(self.screen.scrollback)
        self.sbar.blockSignals(True)
        self.sbar.setRange(0, n)
        self.sbar.setPageStep(self.screen.lines)
        self.sbar.setValue(n - self.scroll_offset)
        self.sbar.blockSignals(False)

    def _on_scrollbar(self, v: int) -> None:
        self.scroll_offset = max(0, len(self.screen.scrollback) - v)
        self.update()

    def scroll_lines(self, n: int) -> None:
        self.scroll_offset = max(0, min(len(self.screen.scrollback), self.scroll_offset + n))
        self._update_scrollbar()
        self.update()

    def _schedule_repaint(self) -> None:
        if not self._repaint_timer.isActive():
            self._repaint_timer.start()

    def _flush_repaint(self) -> None:
        self._update_scrollbar()
        self.update()

    # ------------------------------------------------------------ coordinates
    def _top_abs(self) -> int:
        return self.screen.sb_total - self.scroll_offset

    def _line_at(self, abs_row: int):
        s = self.screen
        if abs_row < s.sb_total:
            i = abs_row - (s.sb_total - len(s.scrollback))
            return s.scrollback[i] if 0 <= i < len(s.scrollback) else None
        y = abs_row - s.sb_total
        return s.buffer[y] if 0 <= y < s.lines else None

    def _cell_at(self, pos) -> tuple[int, int]:
        col = int(max(0, min(self.screen.columns - 1, (pos.x() - self.PAD) // self.cw)))
        row = int(max(0, min(self.screen.lines - 1, (pos.y() - self.PAD) // self.ch)))
        return self._top_abs() + row, col

    def _sel_range(self):
        if not self.sel_anchor or not self.sel_end or self.sel_anchor == self.sel_end:
            return None
        a, b = sorted([self.sel_anchor, self.sel_end])
        return a, b

    def selected_text(self) -> str:
        r = self._sel_range()
        if not r:
            return ""
        (r0, c0), (r1, c1) = r
        out = []
        for row in range(r0, r1 + 1):
            line = self._line_at(row)
            if line is None:
                continue
            start = c0 if row == r0 else 0
            end = c1 if row == r1 else self.screen.columns - 1
            out.append("".join(line[x].data for x in range(start, end + 1)).rstrip())
        return "\n".join(out)

    # ------------------------------------------------------------ painting
    def _color(self, name: str, fg: bool, bold: bool = False) -> QColor:
        if name == "default":
            return self.fg_default if fg else self.bg_default
        key = name
        if fg and bold and name in self.palette_hex and not name.startswith("bright"):
            key = "bright" + name
        c = self._colors.get(key)
        if c is None:
            hexv = self.palette_hex.get(key)
            if hexv is None:
                hexv = "#" + key if len(key) == 6 else DEFAULT_FG
            c = QColor(hexv)
            self._colors[key] = c
        return c

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg_default)
        p.translate(self.PAD, self.PAD)
        s = self.screen
        cw, ch = self.cw, self.ch
        top = self._top_abs()
        sel = self._sel_range()
        sel_bg = self.selection_color
        for vy in range(s.lines):
            abs_row = top + vy
            line = self._line_at(abs_row)
            if line is None:
                continue
            row_sel = None
            if sel and sel[0][0] <= abs_row <= sel[1][0]:
                c0 = sel[0][1] if abs_row == sel[0][0] else 0
                c1 = sel[1][1] if abs_row == sel[1][0] else s.columns - 1
                row_sel = (c0, c1)
            if not line and row_sel is None:
                continue
            hl = {}
            if self.highlight_rules and s.alt is None:
                from .highlights import row_colors
                hl = row_colors(line, s.columns, self.highlight_rules)
            xmax = s.columns if row_sel else min(s.columns, (max(line.keys()) + 1) if line else 0)
            y = vy * ch
            # 1) background
            run_start, run_color = 0, None
            for x in range(xmax + 1):
                if x < xmax:
                    c = line[x]
                    if row_sel and row_sel[0] <= x <= row_sel[1]:
                        bgc = sel_bg
                    elif c.reverse:
                        bgc = self._color(c.fg, True, c.bold)
                    else:
                        bgc = None if c.bg == "default" else self._color(c.bg, False)
                else:
                    bgc = "END"
                if bgc is not run_color:
                    if run_color is not None and run_color != "END":
                        p.fillRect(run_start * cw, y, (x - run_start) * cw, ch, run_color)
                    run_start, run_color = x, bgc
            # 2) text
            run, run_x, run_key, run_fgc = [], 0, None, None
            for x in range(xmax + 1):
                if x < xmax:
                    c = line[x]
                    d = c.data
                    if c.reverse:
                        fgc = self.bg_default if c.bg == "default" else self._color(c.bg, False)
                    elif x in hl and c.fg == "default":
                        fgc = hl[x]        # keyword highlight (only text the program did not color itself)
                    else:
                        fgc = self._color(c.fg, True, c.bold)
                    key = (fgc.rgb(), c.bold or x in hl, c.underscore, c.italics)
                else:
                    d, key = "", None
                ascii_ok = len(d) == 1 and " " <= d < "\x7f"
                if run and (key != run_key or not ascii_ok):
                    self._draw_run(p, run_x, y, "".join(run), run_key, run_fgc)
                    run = []
                if x >= xmax:
                    break
                if not d:
                    continue  # second cell of a wide character (the run was already cut above)
                if ascii_ok:
                    if not run:
                        run_x, run_key, run_fgc = x, key, fgc
                    run.append(d)
                else:
                    self._draw_run(p, x, y, d, key, fgc)
        self._paint_search(p, top)
        self._paint_cursor(p)
        p.end()

    def _draw_run(self, p: QPainter, x: int, y: int, text: str, key, color: QColor) -> None:
        _, bold, under, italic = key
        f = self.bold_font if bold else self.term_font
        if italic:
            f = QFont(f)
            f.setItalic(True)
        p.setFont(f)
        p.setPen(color)
        p.drawText(QPointF(x * self.cw, y + self.ascent), text)
        if under:
            uy = y + self.ch - 2
            p.drawLine(x * self.cw, uy, (x + len(text)) * self.cw, uy)

    def _cursor_rect(self) -> QRect:
        c = self.screen.cursor
        return QRect(c.x * self.cw, c.y * self.ch, self.cw, self.ch)

    def _paint_cursor(self, p: QPainter) -> None:
        s = self.screen
        if self.scroll_offset or s.cursor.hidden or self.disconnected:
            if not self.preedit:
                return
        r = self._cursor_rect()
        if self.preedit:
            p.setFont(self.term_font)
            fm = QFontMetricsF(self.term_font)
            w = max(self.cw * 2, math.ceil(fm.horizontalAdvance(self.preedit)))
            p.fillRect(r.x(), r.y(), w, r.height(), QColor("#3a3d41"))
            p.setPen(QColor("#ffffff"))
            p.drawText(QPointF(r.x(), r.y() + self.ascent), self.preedit)
            p.setPen(QPen(self.cursor_color))
            p.drawLine(r.x(), r.bottom(), r.x() + w, r.bottom())
            return
        line = s.buffer[s.cursor.y]
        c = line[s.cursor.x]
        if c.data and c.data > "\x7f" and s.cursor.x + 1 < s.columns and line[s.cursor.x + 1].data == "":
            r.setWidth(self.cw * 2)
        if self.hasFocus():
            p.fillRect(r, self.cursor_color)
            if c.data.strip():
                p.setFont(self.bold_font if c.bold else self.term_font)
                p.setPen(self.bg_default)
                p.drawText(QPointF(r.x(), r.y() + self.ascent), c.data)
        else:
            p.setPen(QPen(self.cursor_color))
            p.drawRect(r.adjusted(0, 0, -1, -1))

    # ------------------------------------------------------------ color scheme
    def apply_scheme(self, scheme: dict | None) -> None:
        """Terminal colors: None = built-in scheme; otherwise {"ansi": [16 hex], "fg", "bg", "cursor", "selection"}."""
        self.palette_hex = dict(PALETTE)
        fg, bg, cur, sel = DEFAULT_FG, DEFAULT_BG, CURSOR_COLOR, SELECTION_BG
        if scheme:
            names = ["black", "red", "green", "brown", "blue", "magenta", "cyan", "white"]
            ansi = list(scheme.get("ansi") or [])
            for i, n in enumerate(names + ["bright" + n for n in names]):
                if i < len(ansi) and ansi[i]:
                    self.palette_hex[n] = ansi[i]
            fg = scheme.get("fg") or fg
            bg = scheme.get("bg") or bg
            cur = scheme.get("cursor") or cur
            sel = scheme.get("selection") or sel
        self.fg_default, self.bg_default = QColor(fg), QColor(bg)
        self.cursor_color, self.selection_color = QColor(cur), QColor(sel)
        self._colors.clear()
        self.update()

    # ------------------------------------------------------------ find
    def open_search(self) -> None:
        from .termsearch import SearchBar
        if self._search_bar is None:
            self._search_bar = SearchBar(self)
        bar = self._search_bar
        sel = self.selected_text()
        if sel and "\n" not in sel:
            bar.edit.setText(sel)
        bar.place()
        bar.show()
        bar.raise_()
        bar.edit.setFocus()
        bar.edit.selectAll()
        self.search(bar.edit.text())

    def close_search(self) -> None:
        if self._search_bar is not None:
            self._search_bar.hide()
        self.search_query, self.search_hits, self.search_index = "", [], -1
        self.update()
        self.setFocus()

    def search(self, query: str) -> int:
        """Find all matches; jump to the newest one (closest to the prompt). Returns the number of matches."""
        from .termsearch import find_hits
        s = self.screen
        first = s.sb_total - len(s.scrollback)
        rows = [(first + i, line) for i, line in enumerate(s.scrollback)]
        rows += [(s.sb_total + y, s.buffer[y]) for y in range(s.lines)]
        self.search_query = query
        self.search_hits = find_hits(rows, s.columns, query)
        self.search_index = len(self.search_hits) - 1
        self._show_hit()
        return len(self.search_hits)

    def search_step(self, direction: int) -> None:
        """direction 1 = previous (older, upward), -1 = next (newer, downward)."""
        if self.search_query and not self.search_hits:
            self.search(self.search_query)
        if not self.search_hits:
            return
        self.search_index = (self.search_index - direction) % len(self.search_hits)
        self._show_hit()

    def _show_hit(self) -> None:
        if self._search_bar is not None:
            self._search_bar.show_count(self.search_index, len(self.search_hits), self.search_query)
        if 0 <= self.search_index < len(self.search_hits):
            row = self.search_hits[self.search_index][0]
            top = self._top_abs()
            if not (top <= row < top + self.screen.lines):
                # bring the match into view, a few rows below the top edge
                wanted_top = row - min(3, self.screen.lines // 3)
                self.scroll_offset = max(0, min(len(self.screen.scrollback), self.screen.sb_total - wanted_top))
                self._update_scrollbar()
        self.update()

    def _paint_search(self, p: QPainter, top: int) -> None:
        if not self.search_hits:
            return
        bottom = top + self.screen.lines
        other, current = QColor(255, 214, 10, 80), QColor(255, 149, 0, 150)
        for i, (row, c0, c1) in enumerate(self.search_hits):
            if top <= row < bottom:
                p.fillRect(c0 * self.cw, (row - top) * self.ch, (c1 - c0 + 1) * self.cw, self.ch,
                           current if i == self.search_index else other)

    # ------------------------------------------------------------ keyboard
    def event(self, e):
        if e.type() == e.Type.KeyPress and e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) \
                and not (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.keyPressEvent(e)
            return True
        return super().event(e)

    def focusNextPrevChild(self, nxt: bool) -> bool:
        return False

    def keyPressEvent(self, e: QKeyEvent):
        key = e.key()
        mods = e.modifiers()
        if IS_MAC:
            # macOS: Command (ControlModifier) is for local shortcuts only,
            # the physical Control key (MetaModifier) produces control characters.
            cmd = bool(mods & Qt.KeyboardModifier.ControlModifier)
            ctrl = bool(mods & Qt.KeyboardModifier.MetaModifier)
        else:
            cmd = False
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)

        if self.disconnected:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_R):
                self.reconnect_requested.emit()
            return

        # local shortcuts
        if cmd:
            # macOS: Cmd(+Shift)+C copy, Cmd(+Shift)+V paste, Cmd+= / Cmd++ / Cmd+- zoom
            if key == Qt.Key.Key_C:
                t = self.selected_text()
                if t:
                    QGuiApplication.clipboard().setText(t)
                return
            if key == Qt.Key.Key_V:
                self.paste_text(QGuiApplication.clipboard().text())
                return
            if key in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
                self.font_zoom.emit(1)
                return
            if key == Qt.Key.Key_Minus:
                self.font_zoom.emit(-1)
                return
        if ctrl and shift and key == Qt.Key.Key_C and not IS_MAC:
            t = self.selected_text()
            if t:
                QGuiApplication.clipboard().setText(t)
            return
        if ctrl and shift and key == Qt.Key.Key_V and not IS_MAC:
            self.paste_text(QGuiApplication.clipboard().text())
            return
        if shift and key == Qt.Key.Key_Insert:
            self.paste_text(QGuiApplication.clipboard().text())
            return
        if ctrl and not shift and key == Qt.Key.Key_Insert and not IS_MAC:   # Ctrl+Insert copies (PuTTY, Windows Terminal)
            t = self.selected_text()
            if t:
                QGuiApplication.clipboard().setText(t)
            return
        if shift and key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and self.screen.alt is None:
            step = self.screen.lines - 1
            self.scroll_lines(step if key == Qt.Key.Key_PageUp else -step)
            return
        if ctrl and key in (Qt.Key.Key_Equal, Qt.Key.Key_Plus) and not IS_MAC:
            self.font_zoom.emit(1)
            return
        if ctrl and key == Qt.Key.Key_Minus and not IS_MAC:
            self.font_zoom.emit(-1)
            return
        if cmd:
            # any other Cmd combination belongs to menu shortcuts, never to the remote shell
            return

        seq = self._key_sequence(key, ctrl, shift, alt, e.text())
        if seq is not None:
            self.sel_anchor = self.sel_end = None
            self._note_user_input(seq)
            self.send_text(seq)

    def _key_sequence(self, key, ctrl, shift, alt, text) -> str | None:
        app = MODE_DECCKM in self.screen.mode
        # Alt sends an ESC prefix on Windows; on macOS Option types special characters as is
        esc = alt and not IS_MAC
        mod = 1 + (1 if shift else 0) + (2 if alt else 0) + (4 if ctrl else 0)
        K = Qt.Key
        cursor = {K.Key_Up: "A", K.Key_Down: "B", K.Key_Right: "C", K.Key_Left: "D",
                  K.Key_Home: "H", K.Key_End: "F"}
        if key in cursor:
            ch = cursor[key]
            if mod > 1:
                return f"\x1b[1;{mod}{ch}"
            return ("\x1bO" if app else "\x1b[") + ch
        tilde = {K.Key_Insert: 2, K.Key_Delete: 3, K.Key_PageUp: 5, K.Key_PageDown: 6,
                 K.Key_F5: 15, K.Key_F6: 17, K.Key_F7: 18, K.Key_F8: 19, K.Key_F9: 20,
                 K.Key_F10: 21, K.Key_F11: 23, K.Key_F12: 24}
        if key in tilde:
            n = tilde[key]
            return f"\x1b[{n};{mod}~" if mod > 1 else f"\x1b[{n}~"
        pf = {K.Key_F1: "P", K.Key_F2: "Q", K.Key_F3: "R", K.Key_F4: "S"}
        if key in pf:
            return f"\x1b[1;{mod}{pf[key]}" if mod > 1 else "\x1bO" + pf[key]
        if key in (K.Key_Return, K.Key_Enter):
            return "\x1b\r" if esc else "\r"
        if key == K.Key_Backspace:
            return ("\x1b" if esc else "") + ("\x08" if ctrl else "\x7f")
        if key == K.Key_Tab:
            return "\t"
        if key == K.Key_Backtab:
            return "\x1b[Z"
        if key == K.Key_Escape:
            return "\x1b"
        if ctrl and (not text.isprintable() or text == "" or IS_MAC):
            # Ctrl+letter: fix up when Qt doesn't deliver text as a control character
            # (always on macOS, where the Control key may arrive with plain text)
            if K.Key_A <= key <= K.Key_Z:
                return ("\x1b" if esc else "") + chr(key - K.Key_A + 1)
            special = {K.Key_Space: "\x00", K.Key_BracketLeft: "\x1b", K.Key_Backslash: "\x1c",
                       K.Key_BracketRight: "\x1d", K.Key_AsciiCircum: "\x1e", K.Key_Underscore: "\x1f",
                       K.Key_2: "\x00", K.Key_6: "\x1e", K.Key_Slash: "\x1f"}
            if key in special:
                return special[key]
        if text:
            return ("\x1b" + text) if esc and not ctrl else text
        return None

    # ------------------------------------------------------------ IME (CJK input)
    def inputMethodEvent(self, e):
        commit = e.commitString()
        self.preedit = e.preeditString()
        if commit:
            self._note_user_input(commit)
            self.send_text(commit)
        self.update()
        e.accept()

    def inputMethodQuery(self, q):
        if q == Qt.InputMethodQuery.ImCursorRectangle:
            return self._cursor_rect().translated(self.PAD, self.PAD)
        if q == Qt.InputMethodQuery.ImFont:
            return self.term_font
        if q == Qt.InputMethodQuery.ImEnabled:
            return True
        return super().inputMethodQuery(q)

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() == Qt.MouseButton.LeftButton:
            self.sel_anchor = self.sel_end = self._cell_at(e.position())
            self._selecting = True
            self.update()
        elif e.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self.paste_text(QGuiApplication.clipboard().text())

    def mouseMoveEvent(self, e):
        if self._selecting:
            pos = e.position()
            if pos.y() < 0:
                self.scroll_lines(1)
            elif pos.y() > self.height():
                self.scroll_lines(-1)
            self.sel_end = self._cell_at(pos)
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            t = self.selected_text()
            if t:
                QGuiApplication.clipboard().setText(t)

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        row, col = self._cell_at(e.position())
        line = self._line_at(row)
        if line is None:
            return

        def word(x):
            d = line[x].data
            return bool(d) and (d.isalnum() or d in "-_./~:@%+=" or d > "\x7f")
        if not word(col):
            return
        a = col
        while a > 0 and word(a - 1):
            a -= 1
        b = col
        while b < self.screen.columns - 1 and word(b + 1):
            b += 1
        self.sel_anchor, self.sel_end = (row, a), (row, b)
        self._selecting = False
        QGuiApplication.clipboard().setText(self.selected_text())
        self.update()

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if not dy:
            return
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.font_zoom.emit(1 if dy > 0 else -1)
            return
        notches = max(1, abs(dy) // 120)
        if self.screen.alt is not None:
            app = MODE_DECCKM in self.screen.mode
            seq = ("\x1bO" if app else "\x1b[") + ("A" if dy > 0 else "B")
            self.send_text(seq * (3 * notches))
            return
        self.scroll_lines((3 if dy > 0 else -3) * notches)

    def focusInEvent(self, e):
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)
