# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Diagnostic log of what the app does (connections, transfers, errors), kept on this PC only.

Never logged: passwords, passphrases, keys, or what is typed or shown in a terminal.
Windows: %APPDATA%\\JeopsokHeyou\\logs\\app.log. macOS: ~/Library/Logs/JeopsokHeyou/app.log.
The file rolls over at 1 MB and keeps three old copies.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

from . import paths

LOG_NAME = "app.log"
MAX_BYTES = 1 << 20
BACKUPS = 3
_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"

log = logging.getLogger("jeopsokheyou")
log.addHandler(logging.NullHandler())   # until setup(): nothing is printed or written
_handler: logging.Handler | None = None


def log_dir() -> Path:
    if paths.IS_MAC and not os.environ.get("APPDATA"):
        d = Path.home() / "Library" / "Logs" / "JeopsokHeyou"
    else:
        d = paths.app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup(level: int = logging.INFO) -> Path | None:
    """Start writing the log file. Safe to call more than once; never raises."""
    global _handler
    if _handler is not None:
        return Path(_handler.baseFilename)
    try:
        path = log_dir() / LOG_NAME
        h = logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    except OSError:
        return None
    h.setFormatter(logging.Formatter(_FORMAT))
    log.addHandler(h)
    log.setLevel(level)
    log.propagate = False
    _handler = h
    _install_excepthooks()
    from . import __version__
    log.info("JeopsokHeyou %s started (%s, Python %s)", __version__, sys.platform, sys.version.split()[0])
    return path


def shutdown() -> None:
    global _handler
    if _handler is not None:
        log.info("JeopsokHeyou closed")
        log.removeHandler(_handler)
        _handler.close()
        _handler = None


def _install_excepthooks() -> None:
    old_hook = sys.excepthook

    def hook(etype, value, tb):
        log.error("Unhandled error", exc_info=(etype, value, tb))
        old_hook(etype, value, tb)
    sys.excepthook = hook

    old_thread_hook = threading.excepthook

    def thread_hook(args):
        log.error("Unhandled error in thread %s", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        old_thread_hook(args)
    threading.excepthook = thread_hook


def get(name: str) -> logging.Logger:
    return log.getChild(name)
