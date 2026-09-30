# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Open a file with the system default program, or let the user choose one.

Windows: ShellExecute (os.startfile) and the "Open with" dialog (SHOpenWithDialog).
macOS: `open`, and an application picker (AppleScript `choose application`) + `open -a`.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys

IS_MAC = sys.platform == "darwin"

OAIF_ALLOW_REGISTRATION = 0x1   # allow the "Always use this app" checkbox
OAIF_REGISTER_EXT = 0x2
OAIF_EXEC = 0x4                 # run the chosen program immediately


class _OPENASINFO(ctypes.Structure):
    _fields_ = [("pcszFile", wt.LPCWSTR), ("pcszClass", wt.LPCWSTR), ("oaifInFlags", ctypes.c_int)]


def open_default(path: str) -> bool:
    """Open with the default program. False if no program is associated."""
    if IS_MAC:
        # `open` exits non-zero when no application can open the file
        try:
            return subprocess.run(["open", path], capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.startfile(path)  # noqa: S606 - file opened by the user
        return True
    except OSError:
        return False


def open_with_dialog(path: str, hwnd: int = 0) -> None:
    """Let the user pick the application ("Open with…")."""
    if IS_MAC:
        _mac_open_with(path)
        return
    if sys.platform != "win32":
        return
    info = _OPENASINFO(path, None, OAIF_ALLOW_REGISTRATION | OAIF_REGISTER_EXT | OAIF_EXEC)
    try:
        hr = ctypes.windll.shell32.SHOpenWithDialog(wt.HWND(hwnd), ctypes.byref(info))
    except (AttributeError, OSError):
        hr = -1
    # If the user cancelled (0x800704C7) just stop; fall back to the legacy way only on other failures
    if (hr & 0xFFFFFFFF) not in (0, 0x800704C7):
        subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", path])


def _mac_open_with(path: str) -> None:
    """macOS: show the standard application chooser, then open the file with the chosen app."""
    script = 'POSIX path of (choose application as alias)'
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return
    app = r.stdout.strip()
    if r.returncode == 0 and app:        # non-zero = the user cancelled
        subprocess.Popen(["open", "-a", app, path])
