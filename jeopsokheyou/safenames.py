# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Safely turn remote (Linux) file names into local (Windows) paths.

Linux allows \\ : * ? " < > | in file names, so a malicious or compromised server
could send names like '..\\..\\Startup\\evil.bat' or 'C:\\Windows\\evil.dll'; a plain
os.path.join would then write files outside the target folder (path traversal).
Here the name is made into a single safe file name component, and the resulting
path is checked once more to be inside the target folder.
"""
from __future__ import annotations

import os
import re

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class UnsafeName(ValueError):
    pass


def local_name(remote_name: str) -> str:
    """Remote file name → one safe Windows file name component. UnsafeName if unusable."""
    name = _BAD_CHARS.sub("_", remote_name or "")
    name = name.rstrip(" .")                      # Windows ignores trailing dots/spaces
    if not name or name in (".", "..") or set(name) <= {"."}:
        raise UnsafeName(remote_name)
    stem = name.split(".", 1)[0].upper()
    if stem in _RESERVED:                         # device names such as CON, NUL.txt
        name = "_" + name
    return name


def safe_join(base: str, remote_name: str) -> str:
    """Return a path only if it is inside base. UnsafeName if it escapes."""
    path = os.path.join(base, local_name(remote_name))
    base_abs = os.path.abspath(base)
    if os.path.commonpath([base_abs, os.path.abspath(path)]) != base_abs:
        raise UnsafeName(remote_name)
    return path
