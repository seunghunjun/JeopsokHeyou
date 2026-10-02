# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Session logging: what the terminal shows, as plain text (colors and control codes removed),
one file per terminal pane, optionally with a time stamp on every line."""
from __future__ import annotations

import re
import time
from pathlib import Path

from . import paths

# CSI / OSC / other escape sequences, and remaining C0 controls except \n \r \b \t
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[PX^_][^\x1b]*\x1b\\|\x1b[@-Z\\-_()*+][0-9A-Za-z]?")
CONTROL_RE = re.compile(r"[\x00-\x07\x0b\x0c\x0e-\x1f\x7f]")
UNSAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def default_dir() -> Path:
    return Path.home() / "Documents" / "JeopsokHeyou Logs"


def log_path(base: Path, session_title: str, pane_no: int = 1) -> Path:
    name = UNSAFE_RE.sub("_", session_title).strip(" ._") or "session"
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    suffix = f"_{pane_no}" if pane_no > 1 else ""
    return Path(base) / name / f"{stamp}{suffix}.log"


class SessionLog:
    def __init__(self, path: Path, timestamps: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timestamps = timestamps
        self._fh = open(self.path, "a", encoding="utf-8", newline="\n")
        self._line: list[str] = []
        self._pending = ""         # an escape sequence cut at the end of a chunk
        self._cr = False           # the previous character was a carriage return
        self._header()

    def _header(self):
        self._fh.write(f"# JeopsokHeyou session log — started {time.strftime('%Y-%m-%d %H:%M:%S')}"
                       f" ({paths.OS_NAME})\n")
        self._fh.flush()

    def write(self, text: str) -> None:
        if self._fh is None:
            return
        text = self._pending + text
        self._pending = ""
        cut = text.rfind("\x1b")
        if cut >= 0 and not ANSI_RE.match(text, cut) and len(text) - cut < 256:
            self._pending, text = text[cut:], text[:cut]
        text = ANSI_RE.sub("", text)
        wrote = False
        for ch in text:
            if self._cr and ch != "\n":
                self._line = []    # a carriage return followed by text: the line was redrawn (progress bars)
            self._cr = False
            if ch == "\n":
                self._emit()
                wrote = True
            elif ch == "\r":
                self._cr = True
            elif ch == "\b":
                if self._line:
                    self._line.pop()
            elif ch == "\t" or not CONTROL_RE.match(ch):
                self._line.append(ch)
        if wrote:
            self._fh.flush()

    def _emit(self):
        line = "".join(self._line).rstrip()
        self._line = []
        prefix = time.strftime("[%H:%M:%S] ") if self.timestamps else ""
        self._fh.write(prefix + line + "\n")

    def close(self) -> None:
        if self._fh is None:
            return
        if self._line:
            self._emit()
        self._fh.write(f"# ended {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._fh.close()
        self._fh = None

    @property
    def open(self) -> bool:
        return self._fh is not None
