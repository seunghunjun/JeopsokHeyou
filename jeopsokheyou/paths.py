# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Platform facts and file locations, for running from source and as a packaged app
(PyInstaller onedir on Windows, .app bundle on macOS)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
OS_NAME = "macOS" if IS_MAC else "Windows"
FROZEN = bool(getattr(sys, "frozen", False))

# Read-only resources (assets/, jeopsokheyou/locales/): the repository root from source,
# or PyInstaller's extraction folder in a build.
RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

# Folder that contains the program itself (the Windows installer writes installer-language here).
INSTALL_DIR = Path(sys.executable).resolve().parent if FROZEN else RESOURCES

# LICENSE / THIRD-PARTY-NOTICES.md / licenses/: next to the .exe on Windows,
# JeopsokHeyou.app/Contents/Resources on macOS, the repository root from source.
DOCS_DIR = (INSTALL_DIR.parent / "Resources") if (FROZEN and IS_MAC) else INSTALL_DIR

ASSETS = RESOURCES / "assets"
LOCALES = RESOURCES / "jeopsokheyou" / "locales"


def app_data_dir() -> Path:
    """Per-user data folder (sessions, known_hosts, settings).

    Windows: %APPDATA%\\JeopsokHeyou. macOS: ~/Library/Application Support/JeopsokHeyou.
    An APPDATA environment variable always wins (tests use it to isolate their data).
    """
    base = os.environ.get("APPDATA")
    if base:
        root = Path(base)
    elif IS_MAC:
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path.home()
    d = root / "JeopsokHeyou"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tabby_config() -> Path:
    if IS_MAC and not os.environ.get("APPDATA"):
        return Path.home() / "Library" / "Application Support" / "tabby" / "config.yaml"
    return Path(os.environ.get("APPDATA") or str(Path.home())) / "tabby" / "config.yaml"


def installer_language() -> str | None:
    """Language chosen in the Windows installer ('en' / 'ko' / 'ja'), if any."""
    try:
        code = (INSTALL_DIR / "installer-language").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return code or None


def file_manager_name() -> str:
    """Name of the system file manager, in the UI language."""
    from .i18n import tr
    return tr("Finder") if IS_MAC else tr("Windows Explorer")
