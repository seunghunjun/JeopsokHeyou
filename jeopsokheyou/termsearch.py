# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Find in the terminal (screen + scrollback): a small search bar shown in the top-right corner."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton

from . import icons
from .i18n import tr


def find_hits(rows, columns: int, query: str) -> list[tuple[int, int, int]]:
    """Case-insensitive matches as (abs_row, first_col, last_col). ``rows`` yields (abs_row, line)."""
    q = query.lower()
    if not q:
        return []
    hits = []
    for abs_row, line in rows:
        chars, cols = [], []
        for x in range(columns):
            d = line[x].data
            if d == "":            # second cell of a wide character
                continue
            chars.append(d)
            cols.append(x)
        text = "".join(chars).lower()
        start = text.find(q)
        while start >= 0:
            end = start + len(q) - 1
            last = cols[end] if end < len(cols) else cols[-1]
            if last + 1 < columns and line[last + 1].data == "" and chars[end] > "\x7f":
                last += 1          # include the second half of a wide character
            hits.append((abs_row, cols[start], last))
            start = text.find(q, start + 1)
    return hits


class SearchBar(QFrame):
    """Overlay used by TerminalWidget: type to search, Enter = next (older), Shift+Enter = previous, Esc = close."""

    def __init__(self, term):
        super().__init__(term)
        self.term = term
        self.setObjectName("TermSearch")
        self.setStyleSheet("QFrame#TermSearch{background:#2C2C2E;border:1px solid #48484A;border-radius:8px}"
                           "QLineEdit{background:#1C1C1E;color:#F2F2F7;border:1px solid #48484A;border-radius:6px;"
                           "padding:3px 6px} QLabel{color:#A1A1A6} QToolButton{color:#F2F2F7;border:none;"
                           "padding:2px 4px} QToolButton:hover{background:#3A3A3C;border-radius:4px}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 4, 4)
        lay.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Find"))
        self.edit.setFixedWidth(200)
        self.edit.textChanged.connect(self._changed)
        self.edit.returnPressed.connect(lambda: self.term.search_step(1))
        self.count = QLabel()
        self.count.setMinimumWidth(56)
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev = QToolButton()
        prev.setText("▲")
        prev.setToolTip(tr("Previous match (older) — Enter"))
        prev.clicked.connect(lambda: self.term.search_step(1))
        nxt = QToolButton()
        nxt.setText("▼")
        nxt.setToolTip(tr("Next match (newer) — Shift+Enter"))
        nxt.clicked.connect(lambda: self.term.search_step(-1))
        close = QToolButton()
        close.setIcon(icons.line("close", "#F2F2F7"))
        close.setToolTip(tr("Close (Esc)"))
        close.clicked.connect(self.term.close_search)
        for w in (self.edit, self.count, prev, nxt, close):
            lay.addWidget(w)
        self.adjustSize()
        self.hide()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.term.close_search()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.term.search_step(-1)
            return
        super().keyPressEvent(e)

    def _changed(self, text: str):
        self.term.search(text)

    def show_count(self, index: int, total: int, query: str):
        if not query:
            self.count.setText("")
        elif total == 0:
            self.count.setText(tr("No matches"))
        else:
            self.count.setText(f"{index + 1}/{total}")

    def place(self):
        self.adjustSize()
        self.move(self.term.width() - self.term.SB_W - self.width() - 8, 6)
