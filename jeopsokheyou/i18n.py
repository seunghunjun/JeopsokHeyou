# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Minimal translation layer.

Source strings in the code are English. Translations live in
``jeopsokheyou/locales/<lang>.json`` as ``{"English source": "translation"}``.
Placeholders use ``str.format`` syntax, e.g. ``tr("{n} items", n=3)``.

The language is chosen once at startup (before any widget is created):
``--lang`` command-line option > ``JEOPSOKHEYOU_LANG`` environment variable >
``language`` in settings.json > the language picked in the installer > Windows display
language. Anything that is not
Korean or Japanese falls back to English.
"""
from __future__ import annotations

import json
import os

from . import paths

LANGUAGES = {"en": "English", "ko": "한국어", "ja": "日本語"}
LOCALES_DIR = paths.LOCALES

_lang = "en"
_catalog: dict[str, str] = {}


def system_language() -> str:
    """Windows display language → 'ko' / 'ja' / 'en'."""
    try:
        from PySide6.QtCore import QLocale
        for code in QLocale.system().uiLanguages():
            code = code.lower()
            for lang in ("ko", "ja", "en"):
                if code.startswith(lang):
                    return lang
    except Exception:
        pass
    return "en"


def resolve(preference: str | None = None, cli: str | None = None) -> str:
    """Pick the language to use. ``preference`` is the settings value ('system' or a code)."""
    for candidate in (cli, os.environ.get("JEOPSOKHEYOU_LANG"), preference):
        if candidate and candidate in LANGUAGES:
            return candidate
    return system_language()


def load_catalog(lang: str) -> dict[str, str]:
    if lang == "en":
        return {}
    path = LOCALES_DIR / f"{lang}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_language(lang: str) -> None:
    global _lang, _catalog
    _lang = lang if lang in LANGUAGES else "en"
    _catalog = load_catalog(_lang)


_qt_translators: list = []


def install_qt_translations(app) -> None:
    """Load Qt's own translations so standard buttons (OK, Cancel, Yes, No, …) match the UI language."""
    if _lang == "en":
        return
    from PySide6.QtCore import QLibraryInfo, QTranslator
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in ("qtbase", "qt"):
        t = QTranslator(app)
        if t.load(f"{name}_{_lang}", folder):
            app.installTranslator(t)
            _qt_translators.append(t)


def current() -> str:
    return _lang


def tr(text: str, **kwargs) -> str:
    """Translate an English source string (falls back to English when missing)."""
    s = _catalog.get(text) or text
    if kwargs:
        try:
            return s.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text.format(**kwargs)
    return s
