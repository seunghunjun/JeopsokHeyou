# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""macOS Finder-style light/dark themes.

- Colors are based on Apple system colors (light/dark)
- Rounded selection, thin separators, distinct sidebar/content/toolbar surfaces
- On Windows 11, the title bar color and rounded window corners match the app (DWM)
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from . import paths


@dataclass(frozen=True)
class Theme:
    name: str
    dark: bool
    window: str        # base surface
    toolbar: str       # top toolbar / title bar
    sidebar: str       # session sidebar
    content: str       # list body
    alt_row: str       # alternating rows
    text: str
    muted: str         # secondary text
    faint: str         # fainter text (section titles)
    sep: str           # separators
    hover: str
    accent: str
    accent_text: str
    sel_inactive: str  # selection when the window is inactive
    field: str         # input fields
    field_border: str
    button: str
    button_border: str
    menu: str
    icon: str          # line icon color
    scroll: str


LIGHT = Theme(
    name="light", dark=False,
    window="#ECECEC", toolbar="#F6F6F6", sidebar="#EDEBEF", content="#FFFFFF", alt_row="#F5F5F5",
    text="#1D1D1F", muted="#6E6E73", faint="#9A9AA0", sep="#DCDCDE", hover="rgba(0,0,0,0.055)",
    accent="#0A64D8", accent_text="#FFFFFF", sel_inactive="#C4DCF8",
    field="#FFFFFF", field_border="#D2D2D7", button="#FFFFFF", button_border="#D2D2D7",
    menu="#F7F7F7", icon="#5B5B60", scroll="rgba(0,0,0,0.28)",
)

DARK = Theme(
    name="dark", dark=True,
    window="#232325", toolbar="#2B2B2D", sidebar="#262628", content="#1E1E1E", alt_row="#242426",
    text="#E8E8ED", muted="#A1A1A6", faint="#7C7C82", sep="#3A3A3C", hover="rgba(255,255,255,0.07)",
    accent="#0A84FF", accent_text="#FFFFFF", sel_inactive="#1F4A7A",
    field="#1C1C1E", field_border="#3F3F43", button="#3A3A3C", button_border="#48484A",
    menu="#2C2C2E", icon="#C7C7CC", scroll="rgba(255,255,255,0.30)",
)


def system_prefers_dark() -> bool:
    # Qt 6.5+ reports the OS color scheme on both Windows and macOS
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if app is not None:
            scheme = app.styleHints().colorScheme()
            if scheme != Qt.ColorScheme.Unknown:
                return scheme == Qt.ColorScheme.Dark
    except Exception:
        pass
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def resolve(mode: str) -> Theme:
    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK
    return DARK if system_prefers_dark() else LIGHT


FONTS_DIR = paths.ASSETS / "fonts"

# UI font choices: key -> (label (English, translated when shown), font family candidates, pixel size)
UI_FONTS = {
    "default": ("Default (system font)",
                ["Pretendard", "Pretendard Variable", "SUIT", "Segoe UI Variable Text", "Segoe UI",
                 ".AppleSystemUIFont", "Helvetica Neue"], 13),
    "gaegu": ("Gaegu (handwriting)", ["Gaegu"], 16),   # looks small, so use a larger size
}
# CJK fallback order per UI language. Kanji and Hanja share code points but differ in shape and
# coverage, so Japanese must prefer Japanese fonts and Korean must prefer Korean fonts.
# Windows fonts first, then macOS fonts (whichever exist on the machine are used).
CJK_FALLBACK = {
    "ja": ["Yu Gothic UI", "Meiryo UI", "Meiryo", "MS UI Gothic", "MS Gothic",
           "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Malgun Gothic", "Apple SD Gothic Neo"],
    "ko": ["Malgun Gothic", "Apple SD Gothic Neo", "Yu Gothic UI", "Meiryo", "Hiragino Sans"],
    "en": ["Malgun Gothic", "Apple SD Gothic Neo", "Yu Gothic UI", "Meiryo", "Hiragino Sans"],
}
_loaded_fonts = False


def load_bundled_fonts() -> None:
    """Register fonts in assets/fonts (Gaegu, ...) with the app — usable without system install."""
    global _loaded_fonts
    if _loaded_fonts:
        return
    _loaded_fonts = True
    if FONTS_DIR.exists():
        for f in sorted(FONTS_DIR.glob("*.ttf")) + sorted(FONTS_DIR.glob("*.otf")):
            QFontDatabase.addApplicationFont(str(f))


def ui_font(choice: str = "default") -> QFont:
    load_bundled_fonts()
    from . import i18n
    _, families, px = UI_FONTS.get(choice, UI_FONTS["default"])
    f = QFont()
    f.setFamilies(families + CJK_FALLBACK.get(i18n.current(), CJK_FALLBACK["en"]))
    f.setPixelSize(px)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def _ui_asset(name: str, svg: str) -> str:
    """QSS image: url() needs a file — write a theme-colored SVG to the app folder and return its path."""
    from .config import app_dir
    d = app_dir() / "ui"
    d.mkdir(exist_ok=True)
    f = d / name
    if not f.exists() or f.read_text(encoding="utf-8") != svg:
        f.write_text(svg, encoding="utf-8")
    return f.as_posix()


def _close_svg(color: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" '
            f'stroke="{color}" stroke-width="1.4" stroke-linecap="round"/></svg>')


def _chevron_svg(color: str, open_: bool) -> str:
    d = "M4.5 6.5l3.5 3.5 3.5-3.5" if open_ else "M6.5 4.5l3.5 3.5-3.5 3.5"
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="' + d + '" fill="none" '
            f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _chevron_up_svg(color: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4.5 9.5l3.5-3.5 3.5 3.5" fill="none" '
            f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def build_qss(t: Theme) -> str:
    combo_arrow = _ui_asset(f"combo-down-{t.name}.svg", _chevron_svg(t.muted, True))
    spin_up = _ui_asset(f"spin-up-{t.name}.svg", _chevron_up_svg(t.muted))
    spin_down = _ui_asset(f"spin-down-{t.name}.svg", _chevron_svg(t.muted, True))
    chev_closed = _ui_asset(f"chev-closed-{t.name}.svg", _chevron_svg(t.muted, False))
    chev_open = _ui_asset(f"chev-open-{t.name}.svg", _chevron_svg(t.muted, True))
    close = _ui_asset(f"close-{t.name}.svg", _close_svg(t.muted))
    close_hover = _ui_asset(f"close-hover-{t.name}.svg", _close_svg(t.text))
    return f"""
* {{ outline: 0; }}
QMainWindow, QDialog {{ background: {t.window}; }}
QWidget {{ color: {t.text}; }}
QToolTip {{ background: {t.menu}; color: {t.text}; border: 1px solid {t.sep}; border-radius: 6px; padding: 4px 8px; }}

/* menu bar / menus */
QMenuBar {{ background: {t.toolbar}; border: none; padding: 2px 6px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 5px; background: transparent; }}
QMenuBar::item:selected {{ background: {t.hover}; }}
QMenu {{ background: {t.menu}; border: 1px solid {t.sep}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 5px 22px 5px 12px; border-radius: 5px; margin: 1px 0; }}
QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
QMenu::item:disabled {{ color: {t.faint}; }}
QMenu::separator {{ height: 1px; background: {t.sep}; margin: 5px 8px; }}

/* toolbar */
QToolBar {{ background: {t.toolbar}; border: none; border-bottom: 1px solid {t.sep}; padding: 6px 10px; spacing: 4px; }}
QToolBar::separator {{ width: 1px; background: {t.sep}; margin: 4px 6px; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 4px 6px; color: {t.text}; }}
QToolButton:hover {{ background: {t.hover}; }}
QToolButton:pressed {{ background: {t.sep}; }}
QToolButton:checked {{ background: {t.hover}; color: {t.accent}; }}
QToolButton:disabled {{ color: {t.faint}; }}

/* input fields / buttons */
QLineEdit, QSpinBox, QComboBox {{
    background: {t.field}; border: 1px solid {t.field_border}; border-radius: 7px;
    padding: 4px 8px; selection-background-color: {t.accent}; selection-color: {t.accent_text};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {t.accent}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }}
QComboBox::down-arrow {{ image: url({combo_arrow}); width: 14px; height: 14px; }}
QComboBox::down-arrow:on {{ top: 1px; }}
QSpinBox {{ padding-right: 24px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 20px; border: none;
    border-left: 1px solid {t.field_border}; background: transparent; }}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 7px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 7px;
    border-top: 1px solid {t.field_border}; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {t.hover}; }}
QSpinBox::up-arrow {{ image: url({spin_up}); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url({spin_down}); width: 12px; height: 12px; }}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{ image: none; }}
QComboBox QAbstractItemView {{ background: {t.menu}; border: 1px solid {t.sep}; border-radius: 6px;
    selection-background-color: {t.accent}; selection-color: {t.accent_text}; padding: 4px; }}
QPushButton {{ background: {t.button}; border: 1px solid {t.button_border}; border-radius: 7px;
    padding: 5px 14px; }}
QPushButton:hover {{ border-color: {t.accent}; }}
QPushButton:pressed {{ background: {t.hover}; }}
QPushButton:default {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}
QPushButton#Card {{ text-align: left; padding: 10px 14px; border-radius: 10px; background: {t.content}; }}
QPushButton#Card:hover {{ border-color: {t.accent}; background: {t.hover}; }}
QPushButton#Flat {{ background: transparent; border: none; color: {t.muted}; padding: 5px 8px; }}
QPushButton#Flat:hover {{ background: {t.hover}; color: {t.text}; }}

/* tabs (Safari-style rounded tabs) */
QTabWidget::pane {{ border: none; background: {t.content}; }}
QTabBar {{ background: {t.toolbar}; }}
QTabBar::tab {{ background: transparent; color: {t.muted}; padding: 5px 14px; margin: 5px 2px 5px 2px;
    border-radius: 7px; min-width: 60px; }}
QTabBar::tab:hover {{ background: {t.hover}; color: {t.text}; }}
QTabBar::tab:selected {{ background: {t.content}; color: {t.text}; border: 1px solid {t.sep}; }}
QTabBar::close-button {{ image: url({close}); subcontrol-position: right; border-radius: 4px; margin: 2px; }}
QTabBar::close-button:hover {{ image: url({close_hover}); background: {t.hover}; }}

/* lists (common) */
QTreeView, QListView {{ background: {t.content}; alternate-background-color: {t.alt_row}; border: none;
    show-decoration-selected: 1; }}
QTreeView::item {{ min-height: 24px; padding: 0 2px; border: none; }}
QTreeView::item:hover {{ background: {t.hover}; }}
QTreeView::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
QTreeView::item:selected:!active {{ background: {t.sel_inactive}; color: {t.text}; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:selected {{ background: {t.accent}; }}
QTreeView::branch:selected:!active {{ background: {t.sel_inactive}; }}
QTreeView::branch:has-children:closed {{ image: url({chev_closed}); }}
QTreeView::branch:has-children:open {{ image: url({chev_open}); }}
QHeaderView {{ background: {t.content}; border: none; }}
QHeaderView::section {{ background: {t.content}; color: {t.muted}; border: none;
    border-bottom: 1px solid {t.sep}; border-right: 1px solid {t.sep}; padding: 4px 8px; }}
QHeaderView::section:last {{ border-right: none; }}

/* sidebar (sessions) — Finder sidebar */
#Sidebar, #Sidebar QTreeView {{ background: {t.sidebar}; }}
#Sidebar QTreeView {{ show-decoration-selected: 0; padding: 2px 6px; }}
#Sidebar QTreeView::item {{ min-height: 26px; border-radius: 6px; padding-left: 4px; }}
#Sidebar QTreeView::item:first {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
#Sidebar QTreeView::item:last {{ border-top-left-radius: 0; border-bottom-left-radius: 0; padding-left: 0; }}
#Sidebar QTreeView::item:only-one {{ border-radius: 6px; padding-left: 4px; }}
#Sidebar QTreeView::item:selected {{ background: {t.accent}; color: {t.accent_text}; margin-top: 1px; }}
#Sidebar QTreeView::item:selected:!active {{ background: {t.sel_inactive}; color: {t.text}; margin-top: 1px; }}
/* margin-top: at 125-175% display scaling the rounded selection's top edge otherwise bleeds one pixel into the
   arrow area as a thin line */
/* indent (arrow) area: if transparent, selection/hover color shows through as a sliver on the left -> paint with sidebar color */
#Sidebar QTreeView::branch, #Sidebar QTreeView::branch:selected, #Sidebar QTreeView::branch:hover,
#Sidebar QTreeView::branch:selected:!active {{ background: {t.sidebar}; }}
#Sidebar QLineEdit {{ border-radius: 7px; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {t.sidebar}; padding: 8px 12px 2px 12px; }}

/* explorer panel */
#ExplorerBar {{ background: {t.toolbar}; border-bottom: 1px solid {t.sep}; }}
#PathBar QToolButton {{ padding: 2px 5px; color: {t.muted}; }}
#PathBar QToolButton:hover {{ color: {t.text}; }}
#PathBar QToolButton#Current {{ color: {t.text}; font-weight: 600; }}
#PathBar QLabel {{ color: {t.faint}; }}
#StatusBar {{ background: {t.toolbar}; border-top: 1px solid {t.sep}; }}
QLabel#Muted {{ color: {t.muted}; }}
#IdleBanner {{ background: {"#3A3320" if t.dark else "#FFF4D6"}; border-bottom: 1px solid {"#5C4F26" if t.dark else "#F0D98C"}; }}
#IdleBanner QLabel {{ color: {"#F5D78E" if t.dark else "#6B4E00"}; }}
#DiskBanner[level="warn"] {{ background: {"#3A3320" if t.dark else "#FFF4D6"}; border-bottom: 1px solid {"#5C4F26" if t.dark else "#F0D98C"}; }}
#DiskBanner[level="warn"] QLabel {{ color: {"#F5D78E" if t.dark else "#6B4E00"}; font-weight: 600; }}
#DiskBanner[level="crit"] {{ background: {"#3D2225" if t.dark else "#FFE9E8"}; border-bottom: 1px solid {"#6B2E33" if t.dark else "#F5B8B4"}; }}
#DiskBanner[level="crit"] QLabel {{ color: {"#FF9C94" if t.dark else "#9B1C14"}; font-weight: 600; }}
#DiskBanner QPushButton {{ padding: 2px 12px; }}
QLabel#DiskCardTitle {{ font-size: 15px; font-weight: 600; }}
QFrame#PaneBar {{ background: {t.toolbar}; border-bottom: 1px solid {t.sep}; }}
QFrame#PaneBar[active="true"] {{ border-bottom: 2px solid {t.accent}; }}
QLabel#PaneTitle {{ color: {t.muted}; }}
QLabel#PaneTitle[active="true"] {{ color: {t.text}; }}
QLabel#PaneGrip {{ color: {t.faint}; }}
QToolButton#PaneButton {{ padding: 0 4px; color: {t.muted}; }}
QToolButton#PaneButton:hover {{ color: {t.text}; background: {t.hover}; }}
QFrame#EmptyTerminal {{ background: {t.window}; border: 2px dashed transparent; }}
QFrame#EmptyTerminal[dropHover="true"] {{ border-color: {t.accent}; }}
QTabBar[dropHover="true"] {{ background: {t.hover}; border-bottom: 2px solid {t.accent}; }}
QLabel#EmptyIcon {{ font-size: 40px; color: {t.faint}; }}
QLabel#EmptyTitle {{ font-size: 16px; font-weight: 600; }}
QFrame#TourCard {{ background: {t.menu if t.dark else t.content}; border: 1px solid {t.sep}; border-radius: 14px; }}
QLabel#TourTitle {{ font-size: 17px; font-weight: 600; }}
QPushButton#TourLink {{ border: none; background: transparent; color: {t.muted}; padding: 4px 2px; }}
QPushButton#TourLink:hover {{ color: {t.accent}; }}
QLabel#Title {{ font-size: 22px; font-weight: 600; }}
QLabel#Section {{ color: {t.faint}; font-size: 11px; font-weight: 600; }}

/* home tab (menu + pages) */
#NavBar {{ background: {t.sidebar}; border-right: 1px solid {t.sep}; }}
QListWidget#Nav {{ background: transparent; border: none; }}
QListWidget#Nav::item {{ padding: 8px 10px; margin: 1px 0; border-radius: 8px; color: {t.text}; }}
QListWidget#Nav::item:hover {{ background: {t.hover}; }}
QListWidget#Nav::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
QPushButton#NavButton {{ text-align: left; background: transparent; border: none; padding: 8px 10px; border-radius: 8px; }}
QPushButton#NavButton:hover {{ background: {t.hover}; }}
#Page, #Page > QWidget, QStackedWidget#Page {{ background: {t.window}; }}
QScrollArea {{ background: transparent; }}
QScrollArea > QWidget > QWidget#Page {{ background: {t.window}; }}
QLabel#PageTitle {{ font-size: 18px; font-weight: 700; }}
QPushButton#TreeHead {{ text-align: left; background: transparent; border: none; border-radius: 6px;
    padding: 4px 8px; }}
QPushButton#TreeHead:hover {{ background: {t.hover}; }}
QPushButton#TreeHead:checked {{ background: {t.accent}; color: {t.accent_text}; }}
#Sidebar QTreeView#HostTree {{ show-decoration-selected: 0; }}
QPushButton#Crumb {{ background: transparent; border: none; color: {t.muted}; font-size: 15px; padding: 2px 6px; }}
QPushButton#Crumb:hover {{ color: {t.accent}; background: {t.hover}; }}
QFrame#Card {{ background: {t.content}; border: 1px solid {t.sep}; border-radius: 12px; }}
QFrame#Card:hover {{ border-color: {t.accent}; }}
QFrame#Card[selected="true"] {{ border: 2px solid {t.accent}; }}
QLabel#CardNote {{ color: {t.faint}; font-size: 11px; }}
QToolButton#RowEdit {{ border: none; background: transparent; border-radius: 4px; }}
QToolButton#RowEdit:hover {{ background: {t.hover}; }}
QFrame#Card[dropHover="true"] {{ border: 2px solid {t.accent}; background: {t.hover}; }}
QPushButton#Crumb[dropHover="true"], QPushButton#TreeHead[dropHover="true"] {{ border: 2px solid {t.accent}; }}
QLabel#CardTitle {{ font-weight: 600; }}
QPushButton#Primary {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {t.accent}; border-color: {t.text}; }}
QToolButton#Button {{ background: {t.button}; border: 1px solid {t.button_border}; border-radius: 7px; padding: 5px 12px; }}
QToolButton#Button:hover {{ border-color: {t.accent}; }}
QToolButton#Button::menu-indicator {{ image: none; width: 0; }}
QLineEdit#Search {{ padding: 6px 10px; border-radius: 9px; }}
QFrame#EditPanel {{ background: {t.toolbar}; border-left: 1px solid {t.sep}; }}
QFrame#EditPanel QDialog {{ background: transparent; }}

/* scrollbars: thin and rounded */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {t.scroll}; border-radius: 3px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {t.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* splitter handles: 1px */
QSplitter::handle {{ background: {t.sep}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QMainWindow::separator {{ background: {t.sep}; width: 1px; height: 1px; }}

QProgressBar {{ background: {t.sep}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}
QCheckBox {{ spacing: 6px; }}
"""


def apply_palette(app: QApplication, t: Theme) -> None:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.window, QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.content, QPalette.ColorRole.AlternateBase: t.alt_row,
        QPalette.ColorRole.ToolTipBase: t.menu, QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.Text: t.text, QPalette.ColorRole.Button: t.button,
        QPalette.ColorRole.ButtonText: t.text, QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.accent_text, QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.PlaceholderText: t.faint,
    }
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.faint))
    app.setPalette(p)


class ThemeManager(QObject):
    changed = Signal(object)   # Theme

    def __init__(self):
        super().__init__()
        self.mode = "system"
        self.font_choice = "default"
        self.current: Theme = LIGHT

    def apply(self, app: QApplication, mode: str | None = None, font_choice: str | None = None) -> Theme:
        self.mode = mode or self.mode
        self.font_choice = font_choice or self.font_choice
        self.current = resolve(self.mode)
        app.setStyle("Fusion")
        app.setFont(ui_font(self.font_choice))
        apply_palette(app, self.current)
        # Qt skips re-applying an identical stylesheet, so changing only the font leaves the old font
        # on some widgets -> clear it once and set it again so every widget is repolished
        app.setStyleSheet("")
        app.setStyleSheet(build_qss(self.current))
        for w in app.topLevelWidgets():
            style_window(w, self.current)
        self.changed.emit(self.current)
        return self.current


manager = ThemeManager()


def current() -> Theme:
    return manager.current


def _colorref(hex_color: str) -> int:
    c = QColor(hex_color)
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def style_window(w, t: Theme) -> None:
    """Windows 11: match title bar color/text to the toolbar and round the corners. Silently ignored if unsupported."""
    if sys.platform != "win32" or not w.isWindow():
        return
    try:
        hwnd = int(w.winId())
        dwm = ctypes.windll.dwmapi

        def setattr_(attr, value):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        setattr_(20, 1 if t.dark else 0)          # DWMWA_USE_IMMERSIVE_DARK_MODE
        setattr_(33, 2)                            # DWMWA_WINDOW_CORNER_PREFERENCE = ROUND
        setattr_(35, _colorref(t.toolbar))         # DWMWA_CAPTION_COLOR
        setattr_(36, _colorref(t.text))            # DWMWA_TEXT_COLOR
        setattr_(34, _colorref(t.sep))             # DWMWA_BORDER_COLOR
    except Exception:
        pass
