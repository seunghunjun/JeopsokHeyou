# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Download remote files by dragging them into Windows Explorer.

Windows Explorer requires a 'real local file' at the moment of the drop, so:
1) temporarily create small placeholder files/folders with the real names and drag those
2) after the drop, find the folder the placeholder was copied to (Explorer window/desktop/a subfolder)
3) download into that folder in the background — the downloaded file overwrites the placeholder.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from PySide6.QtCore import QThread, Signal

from .safenames import safe_join

MARK_FILE = ".jeopsokheyou-drop"   # marker file placed inside folder placeholders


def make_placeholders(items: list[tuple[str, bool]]) -> tuple[str, list[str], bytes]:
    """items: [(name, is_dir)] → (staging folder, placeholder paths, marker bytes)"""
    token = uuid.uuid4().hex
    marker = f"JEOPSOKHEYOU-DROP {token}".encode("ascii")
    staging = os.path.join(tempfile.gettempdir(), "JeopsokHeyou", "drag", token)
    os.makedirs(staging, exist_ok=True)
    paths = []
    for name, is_dir in items:
        p = safe_join(staging, name)
        if is_dir:
            os.makedirs(p, exist_ok=True)
            with open(os.path.join(p, MARK_FILE), "wb") as f:
                f.write(marker)
        else:
            with open(p, "wb") as f:
                f.write(marker)
        paths.append(p)
    return staging, paths, marker


def is_placeholder(path: str, is_dir: bool, marker: bytes) -> bool:
    target = os.path.join(path, MARK_FILE) if is_dir else path
    try:
        if os.path.getsize(target) != len(marker):
            return False
        with open(target, "rb") as f:
            return f.read() == marker
    except OSError:
        return False


def remove_placeholders(folder: str, items: list[tuple[str, bool]], marker: bytes, only_untouched: bool) -> None:
    """Remove folder markers after download. On failure/cancel (only_untouched) also remove placeholders that were not overwritten."""
    for name, is_dir in items:
        p = os.path.join(folder, name)
        try:
            if is_dir:
                mark = os.path.join(p, MARK_FILE)
                if is_placeholder(p, True, marker):
                    os.remove(mark)
                if only_untouched and os.path.isdir(p) and not os.listdir(p):
                    os.rmdir(p)
            elif only_untouched and is_placeholder(p, False, marker):
                os.remove(p)
        except OSError:
            pass


def cleanup_staging(staging: str) -> None:
    shutil.rmtree(staging, ignore_errors=True)


FINDER_SCRIPT = """
set out to ""
tell application "Finder"
    repeat with w in (every Finder window)
        try
            set out to out & (POSIX path of (target of w as alias)) & linefeed
        end try
    end repeat
end tell
return out
"""


def explorer_folders() -> list[str]:
    """Folders of the open file-manager windows (Explorer / Finder) + the desktop path."""
    if sys.platform == "darwin":
        # Asks Finder via AppleScript; macOS shows a one-time "control Finder" permission prompt
        # (the reason text is NSAppleEventsUsageDescription in the app's Info.plist).
        try:
            r = subprocess.run(["osascript", "-e", FINDER_SCRIPT], capture_output=True,
                               text=True, timeout=5)
            lines = r.stdout.splitlines()
        except Exception:
            lines = []
        return _existing_folders(lines)
    if sys.platform != "win32":
        return _existing_folders([])
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
           "$s=New-Object -ComObject Shell.Application;"
           "$s.Namespace(0).Self.Path;"
           "foreach($w in $s.Windows()){ try { $w.Document.Folder.Self.Path } catch {} }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                           capture_output=True, encoding="utf-8", errors="replace", timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        lines = r.stdout.splitlines()
    except Exception:
        lines = []
    return _existing_folders(lines)


def _existing_folders(lines: list[str]) -> list[str]:
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    out = []
    for p in [*lines, desktop]:
        p = p.strip()
        if p and os.path.isdir(p) and p not in out:
            out.append(p)
    return out


class DropLocator(QThread):
    """Find which folder the dropped placeholder was copied to."""
    found = Signal(str)
    not_found = Signal()

    def __init__(self, name: str, is_dir: bool, marker: bytes, timeout: float = 6.0):
        super().__init__()
        self.name, self.is_dir, self.marker, self.timeout = name, is_dir, marker, timeout

    def _search(self, folders: list[str]) -> str | None:
        for f in folders:
            if is_placeholder(os.path.join(f, self.name), self.is_dir, self.marker):
                return f
        # dropped onto a subfolder icon inside Explorer
        for f in folders:
            try:
                with os.scandir(f) as it:
                    for n, e in enumerate(it):
                        if n > 3000:
                            break
                        if e.is_dir(follow_symlinks=False) and \
                                is_placeholder(os.path.join(e.path, self.name), self.is_dir, self.marker):
                            return e.path
            except OSError:
                continue
        return None

    def run(self):
        folders = explorer_folders()
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            hit = self._search(folders)
            if hit:
                self.found.emit(hit)
                return
            time.sleep(0.2)   # wait in case Explorer finishes the copy late
        self.not_found.emit()
