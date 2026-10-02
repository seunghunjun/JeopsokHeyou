# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Keyword highlighting in the terminal (e.g. ERROR in red) and the dialog that edits the rules."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .i18n import tr

# words: comma-separated; matched as whole words, "*" matches any letters (e.g. *Exception).
# case: match upper/lower case exactly.
DEFAULT_RULES = [
    {"words": "ERROR, ERR, FATAL, FAIL, FAILED, FAILURE, CRITICAL, *Exception, Traceback", "color": "#ff5f57",
     "case": False},
    {"words": "WARN, WARNING", "color": "#ffbd2e", "case": False},
    {"words": "SUCCESS, SUCCEEDED", "color": "#28c840", "case": False},
]


def compile_rules(rules: list[dict] | None) -> list[tuple[re.Pattern, QColor]]:
    out = []
    for r in rules or []:
        words = [w.strip() for w in str(r.get("words", "")).split(",") if w.strip()]
        if not words:
            continue
        alts = [r"\w*".join(re.escape(part) for part in w.split("*")) for w in words]
        pattern = r"(?<![\w])(?:" + "|".join(alts) + r")(?![\w])"
        flags = 0 if r.get("case") else re.IGNORECASE
        try:
            out.append((re.compile(pattern, flags), QColor(r.get("color") or "#ff5f57")))
        except re.error:
            continue
    return out


def row_colors(line, columns: int, compiled) -> dict[int, QColor]:
    """Column → color for the cells of one terminal row that match a rule (first rule wins)."""
    if not compiled:
        return {}
    chars, cols = [], []
    for x in range(columns):
        d = line[x].data
        if d == "":
            continue
        chars.append(d)
        cols.append(x)
    text = "".join(chars)
    if not text.strip():
        return {}
    out: dict[int, QColor] = {}
    for rx, color in compiled:
        for m in rx.finditer(text):
            for i in range(m.start(), m.end()):
                c = cols[i]
                out.setdefault(c, color)
                if c + 1 < columns and line[c + 1].data == "":
                    out.setdefault(c + 1, color)
    return out


class HighlightDialog(QDialog):
    """Settings → Keyword highlighting."""

    def __init__(self, enabled: bool, rules: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Keyword highlighting"))
        self.setMinimumSize(620, 340)
        lay = QVBoxLayout(self)
        self.enabled = QCheckBox(tr("Highlight keywords in the terminal"))
        self.enabled.setChecked(enabled)
        lay.addWidget(self.enabled)
        note = QLabel(tr("Words are separated by commas and matched as whole words; * matches any letters "
                         "(e.g. *Exception). Full-screen programs (vim, top, …) are not highlighted."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Words"), tr("Color"), tr("Match case")])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 1)
        for r in rules:
            self._add_row(r)
        btns = QHBoxLayout()
        add = QPushButton(tr("Add…"))
        add.clicked.connect(lambda: self._add_row({"words": "", "color": "#64d2ff", "case": False}, edit=True))
        rm = QPushButton(tr("Remove"))
        rm.clicked.connect(self._remove)
        reset = QPushButton(tr("Restore defaults"))
        reset.clicked.connect(self._reset)
        btns.addWidget(add)
        btns.addWidget(rm)
        btns.addStretch(1)
        btns.addWidget(reset)
        lay.addLayout(btns)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add_row(self, rule: dict, edit: bool = False):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(rule.get("words", "")))
        btn = QPushButton()
        self._set_color(btn, rule.get("color") or "#ff5f57")
        btn.clicked.connect(lambda: self._pick(btn))
        self.table.setCellWidget(r, 1, btn)
        case = QTableWidgetItem()
        case.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
        case.setCheckState(Qt.CheckState.Checked if rule.get("case") else Qt.CheckState.Unchecked)
        self.table.setItem(r, 2, case)
        if edit:
            self.table.setCurrentCell(r, 0)
            self.table.editItem(self.table.item(r, 0))

    @staticmethod
    def _set_color(btn: QPushButton, color: str):
        btn.setProperty("color", color)
        btn.setText(color)
        btn.setStyleSheet(f"QPushButton{{color:{color};font-weight:600}}")

    def _pick(self, btn: QPushButton):
        c = QColorDialog.getColor(QColor(btn.property("color")), self, tr("Color"))
        if c.isValid():
            self._set_color(btn, c.name())

    def _remove(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _reset(self):
        self.table.setRowCount(0)
        for r in DEFAULT_RULES:
            self._add_row(dict(r))

    def rules(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            words = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            if not words:
                continue
            out.append({"words": words, "color": self.table.cellWidget(r, 1).property("color"),
                        "case": self.table.item(r, 2).checkState() == Qt.CheckState.Checked})
        return out
