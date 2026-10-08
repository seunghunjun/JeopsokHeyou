# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Keyboard shortcuts, following each system's usual terminal app: Windows Terminal on Windows,
iTerm2 / Terminal.app on macOS. The keys JeopsokHeyou used before stay as extra shortcuts.

Qt writes the macOS Command key as "Ctrl" and the Control key as "Meta" in key strings.
Plain Ctrl+letter (Control+letter on macOS) always goes to the server (Ctrl+C, Ctrl+D, Ctrl+R, ...).
"""
from __future__ import annotations

from PySide6.QtGui import QKeySequence

from .paths import IS_MAC

# id: (Windows keys, macOS keys) — the first one is shown in menus
KEYS: dict[str, tuple[list[str], list[str]]] = {
    "new_session": (["Ctrl+Shift+N"], ["Ctrl+Shift+N"]),
    "quick_connect": (["Ctrl+Shift+Q"], ["Ctrl+L"]),             # ⌘⇧Q logs out of macOS
    "lock": (["Ctrl+Shift+L"], ["Ctrl+Shift+L"]),
    "split_lr": (["Alt+Shift+=", "Alt+Shift++", "Ctrl+Shift+D"], ["Ctrl+D"]),
    "split_tb": (["Alt+Shift+-", "Ctrl+Shift+E"], ["Ctrl+Shift+D", "Ctrl+Shift+E"]),
    "duplicate_tab": (["Ctrl+Shift+T"], ["Ctrl+T", "Ctrl+Shift+T"]),
    "close_pane": (["Ctrl+Shift+W"], ["Ctrl+W", "Ctrl+Shift+W"]),
    "next_tab": (["Ctrl+Tab"], ["Ctrl+Shift+]", "Meta+Tab"]),
    "prev_tab": (["Ctrl+Shift+Tab"], ["Ctrl+Shift+[", "Meta+Shift+Tab"]),
    "snippets": (["Ctrl+Shift+P"], ["Ctrl+Shift+P"]),
    "find": (["Ctrl+Shift+F", "Ctrl+Shift+G"], ["Ctrl+F"]),
    "home": (["Ctrl+Shift+H"], ["Ctrl+Shift+H"]),
    "explorer": (["Ctrl+Shift+B"], ["Ctrl+Shift+B"]),
    "sessions_panel": (["Ctrl+Shift+S"], ["Ctrl+Shift+S"]),
    "zoom_in": (["Ctrl+=", "Ctrl++", "Ctrl+Shift+="], ["Ctrl+=", "Ctrl++"]),
    "zoom_out": (["Ctrl+-", "Ctrl+Shift+-"], ["Ctrl+-"]),
    "settings": (["Ctrl+,"], ["Ctrl+,"]),
    "port_forwarding": (["Ctrl+Shift+O"], ["Ctrl+Shift+O"]),
    "shortcuts": (["Ctrl+Shift+/", "Ctrl+?"], ["Ctrl+/"]),          # F1 and Ctrl+/ belong to programs on the server
}
for _n in range(1, 10):                                          # go to tab 1-9 (9 = last tab)
    KEYS[f"tab_{_n}"] = ([f"Ctrl+Alt+{_n}"], [f"Ctrl+{_n}"])

# Help > Keyboard shortcuts: (section, label, shortcut id) — labels are translated when shown
SECTIONS = [
    ("Connections", [("New session", "new_session"), ("Quick connect", "quick_connect"),
                     ("Lock saved passwords", "lock")]),
    ("Tabs and split panes", [("Split left/right", "split_lr"), ("Split top/bottom", "split_tb"),
                              ("Duplicate tab (new connection to the same server)", "duplicate_tab"),
                              ("Close pane or tab", "close_pane"), ("Next tab", "next_tab"),
                              ("Previous tab", "prev_tab"), ("Go to tab 1–9 (9 = last)", "tab_1")]),
    ("Terminal", [("Find in the terminal", "find"), ("Snippets", "snippets"),
                  ("Larger text", "zoom_in"), ("Smaller text", "zoom_out")]),
    ("View and tools", [("Home", "home"), ("Show/hide SFTP explorer", "explorer"),
                        ("Session list panel", "sessions_panel"), ("Port forwarding", "port_forwarding"),
                        ("Settings", "settings"), ("Keyboard shortcuts", "shortcuts")]),
]

# Handled by the terminal itself: (label, Windows, macOS)
TERMINAL_KEYS = [
    ("Copy the selection", "Ctrl+Shift+C / Ctrl+Insert", "⌘C"),
    ("Paste", "Ctrl+Shift+V / Shift+Insert", "⌘V"),
    ("Scroll up / down a page", "Shift+PgUp / Shift+PgDn", "Shift+PgUp / Shift+PgDn"),
    ("Sent to the server (interrupt, end of input, search history, …)", "Ctrl+C, Ctrl+D, Ctrl+R, …",
     "Control+C, Control+D, Control+R, …"),
]

LABELS = [label for _s, rows in SECTIONS for label, _k in rows] + [s for s, _r in SECTIONS] + \
    [label for label, _w, _m in TERMINAL_KEYS] + ["Typing in the terminal"]


def keys(sid: str) -> list[QKeySequence]:
    win, mac = KEYS[sid]
    return [QKeySequence(k) for k in (mac if IS_MAC else win)]


def text(sid: str, first_only: bool = False) -> str:
    """Keys as the system writes them (⌘⇧D on macOS)."""
    seqs = keys(sid)
    if first_only:
        seqs = seqs[:1]
    if sid == "tab_1":
        return " / ".join(s.toString(QKeySequence.SequenceFormat.NativeText)[:-1] + "1–9" for s in seqs[:1])
    return " / ".join(s.toString(QKeySequence.SequenceFormat.NativeText) for s in seqs)


def terminal_text(win: str, mac: str) -> str:
    return mac if IS_MAC else win
