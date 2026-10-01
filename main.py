# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""JeopsokHeyou — tabbed/split SSH terminal + SFTP explorer."""
import argparse
import ctypes
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from jeopsokheyou import config, i18n, paths
from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme


RUN_MUTEX = "JeopsokHeyou.Running"   # checked by the installer (packaging/installer.nsi)
_run_mutex = None


def mark_running() -> None:
    """Windows: hold a named mutex while the app runs so the installer can ask to close it first."""
    global _run_mutex
    if sys.platform == "win32" and _run_mutex is None:
        _run_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, RUN_MUTEX)


def app_icon() -> QIcon | None:
    for name in ("app.ico", "app.png"):
        p = paths.ASSETS / name
        if p.exists():
            return QIcon(str(p))
    return None


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Parse our own options; everything else (e.g. Qt options) is passed through."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--lang", default=None, help="UI language: en, ko or ja")
    parser.add_argument("--self-test", metavar="REPORT.json", default=None,
                        help="build verification: start, check bundled resources, write a report and exit")
    return parser.parse_known_args(argv)


def main() -> int:
    args, rest = parse_args(sys.argv[1:])
    if sys.platform == "win32":
        # Use a separate app ID so the taskbar shows the app icon instead of the python icon
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JeopsokHeyou.App")
        mark_running()
    app = QApplication([sys.argv[0], *rest])
    app.setApplicationName("JeopsokHeyou")
    # Pick the UI language before any window is created
    settings = config.load_settings()
    # A language chosen in Settings wins; otherwise the installer's choice; otherwise Windows
    preference = settings.get("language") or paths.installer_language() or "system"
    i18n.set_language(i18n.resolve(preference, cli=args.lang))
    i18n.install_qt_translations(app)
    icon = app_icon()
    if icon:
        app.setWindowIcon(icon)
    apply_dark_theme(app)
    w = MainWindow()
    if args.self_test:
        return self_test(app, w, args.self_test)
    w.show()
    return app.exec()


def self_test(app: QApplication, w: MainWindow, report_path: str) -> int:
    """Used by tools/build_release.py to verify a frozen build without a console."""
    import json

    from PySide6.QtGui import QFontDatabase

    from jeopsokheyou import __version__, i18n as _i18n
    report = {
        "version": __version__,
        "frozen": paths.FROZEN,
        "language": _i18n.current(),
        "catalog_entries": len(_i18n.load_catalog(_i18n.current())),
        "icon": not app.windowIcon().isNull(),
        "gaegu_font": "Gaegu" in QFontDatabase.families(),
        "qt_translators": len(_i18n._qt_translators),
        "window_title": w.windowTitle(),
        "menus": [a.text() for a in w.menuBar().actions()],
    }
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
