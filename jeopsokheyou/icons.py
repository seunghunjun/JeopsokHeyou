# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""SVG icons (SF Symbols-style line icons + Finder-style folder/document icons).

- Line icons use the theme's icon color; buttons attached via bind() are repainted on theme change
- File icons are document shapes with a color band per extension kind
"""
from __future__ import annotations

import posixpath
import weakref

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme
from .i18n import tr

_S = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{d}</svg>')

LINE = {
    "back": '<path d="M15 18l-6-6 6-6"/>',
    "forward": '<path d="M9 6l6 6-6 6"/>',
    "up": '<path d="M12 19V6"/><path d="M6 11l6-6 6 6"/>',
    "home": '<path d="M3.5 11L12 4l8.5 7"/><path d="M5.5 9.5V20h5v-5.5h3V20h5V9.5"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4.2h-4.2"/>',
    "upload": '<path d="M12 15V4"/><path d="M7.5 8.5L12 4l4.5 4.5"/><path d="M4.5 15v3.5A1.5 1.5 0 0 0 6 20h12a1.5 1.5 0 0 0 1.5-1.5V15"/>',
    "download": '<path d="M12 4v11"/><path d="M7.5 10.5L12 15l4.5-4.5"/><path d="M4.5 15v3.5A1.5 1.5 0 0 0 6 20h12a1.5 1.5 0 0 0 1.5-1.5V15"/>',
    "folder_plus": '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M12 11v5M9.5 13.5h5"/>',
    "terminal": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M7 9.5l3 2.5-3 2.5"/><path d="M12.5 15h4.5"/>',
    "split_h": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M12 4.5v15"/>',
    "split_v": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M3 12h18"/>',
    "sidebar": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M9 4.5v15"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "server": '<rect x="4" y="4" width="16" height="7" rx="2"/><rect x="4" y="13" width="16" height="7" rx="2"/><path d="M8 7.5h.01M8 16.5h.01"/>',
    "bolt": '<path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/>',
    "close": '<path d="M7 7l10 10M17 7L7 17"/>',
    "tunnel": '<path d="M4 8h11"/><path d="M12 5l3 3-3 3"/><path d="M20 16H9"/><path d="M12 13l-3 3 3 3"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8"/><path d="M16 7l2.5 2.5M14 9l2 2"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2.2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    "pencil": '<path d="M4 20l1-4.5L15.5 5a2 2 0 0 1 2.8 0l.7.7a2 2 0 0 1 0 2.8L8.5 19z"/><path d="M13.5 7l3.5 3.5"/>',
    "folder": '<path d="M3.5 7A1.5 1.5 0 0 1 5 5.5h4l2 2h8A1.5 1.5 0 0 1 20.5 9v8.5A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    "code": '<path d="M8.5 7.5L4 12l4.5 4.5"/><path d="M15.5 7.5L20 12l-4.5 4.5"/><path d="M13 5.5l-2 13"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6 6l1.6 1.6M16.4 16.4L18 18M6 18l1.6-1.6M16.4 7.6L18 6"/>',
    "shield": '<path d="M12 3.5l7 2.8v5.2c0 4.4-3 7.7-7 9-4-1.3-7-4.6-7-9V6.3z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
}

FOLDER = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
          '<path d="M2.5 6.2A1.9 1.9 0 0 1 4.4 4.3h4.9l2 2h8.3a1.9 1.9 0 0 1 1.9 1.9v9.6a1.9 1.9 0 0 1-1.9 1.9H4.4'
          'a1.9 1.9 0 0 1-1.9-1.9z" fill="#4E9CEB"/>'
          '<path d="M2.5 9.3a1.3 1.3 0 0 1 1.3-1.3h16.4a1.3 1.3 0 0 1 1.3 1.3v8.5a1.9 1.9 0 0 1-1.9 1.9H4.4'
          'a1.9 1.9 0 0 1-1.9-1.9z" fill="#7BBDF7"/></svg>')

DOC = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
       '<path d="M6.2 2.8h8l4.6 4.6v12.3a1.5 1.5 0 0 1-1.5 1.5H6.2a1.5 1.5 0 0 1-1.5-1.5V4.3a1.5 1.5 0 0 1 1.5-1.5z"'
       ' fill="#FFFFFF" stroke="#B9B9BF" stroke-width="0.9"/>'
       '<path d="M14.2 2.8v3.3a1.3 1.3 0 0 0 1.3 1.3h3.3" fill="#E9E9EE" stroke="#B9B9BF" stroke-width="0.9"/>'
       '<rect x="4.7" y="14.6" width="14.1" height="4.4" fill="{band}"/>'
       '</svg>')

LINK_BADGE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
              '<rect x="1.5" y="13.5" width="9" height="9" rx="2" fill="#FFFFFF" stroke="#8E8E93" stroke-width="0.8"/>'
              '<path d="M4 20l4-4M5.2 16h2.8v2.8" fill="none" stroke="#1D1D1F" stroke-width="1.2" '
              'stroke-linecap="round" stroke-linejoin="round"/></svg>')

KINDS = {  # key -> (kind label (English, translated when shown), band color, extensions)
    "text": ("Text", "#8E8E93", {"txt", "md", "log", "csv", "tsv", "out", "rst"}),
    "code": ("Source code", "#AF52DE", {"py", "java", "js", "ts", "c", "h", "cpp", "go", "rs", "kt", "cs",
                                      "php", "rb", "jsp", "html", "htm", "css", "vue", "sql", "scala"}),
    "script": ("Script", "#34C759", {"sh", "bash", "zsh", "bat", "cmd", "ps1", "pl"}),
    "config": ("Configuration", "#5E8FBF", {"conf", "cfg", "ini", "properties", "yml", "yaml", "toml", "env", "json"}),
    "xml": ("XML document", "#FF9500", {"xml", "xsl", "xsd", "wsdl", "pom"}),
    "image": ("Image", "#30B0C7", {"png", "jpg", "jpeg", "gif", "bmp", "svg", "webp", "ico", "dcm"}),
    "archive": ("Archive", "#A2845E", {"zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "jar", "war", "ear"}),
    "pdf": ("PDF document", "#FF3B30", {"pdf"}),
    "binary": ("Executable", "#636366", {"exe", "bin", "so", "dll", "class", "o", "a"}),
}

_cache: dict = {}
_bound: list = []   # (weakref(widget), name)
SIZES = (16, 20, 24, 32, 48, 64)


def _render(svg: str, size: int, dpr: float = 2.0) -> QPixmap:
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _icon_from_svg(svg: str, overlay: str | None = None) -> QIcon:
    ic = QIcon()
    for s in SIZES:
        pm = _render(svg, s)
        if overlay:
            p = QPainter(pm)
            p.drawPixmap(0, 0, _render(overlay, s))
            p.end()
        ic.addPixmap(pm)
    return ic


def line(name: str, color: str | None = None) -> QIcon:
    color = color or theme.current().icon
    key = ("line", name, color)
    if key not in _cache:
        _cache[key] = _icon_from_svg(_S.format(c=color, d=LINE[name]))
    return _cache[key]


def line_selectable(name: str, color: str, selected_color: str = "#FFFFFF") -> QIcon:
    """Line icon drawn in color normally and in selected_color on selected rows."""
    key = ("line_sel", name, color, selected_color)
    if key not in _cache:
        ic = QIcon()
        normal = _S.format(c=color, d=LINE[name])
        sel = _S.format(c=selected_color, d=LINE[name])
        for s in SIZES:
            ic.addPixmap(_render(normal, s), QIcon.Mode.Normal)
            ic.addPixmap(_render(sel, s), QIcon.Mode.Selected)
        _cache[key] = ic
    return _cache[key]


def bind(button, name: str) -> None:
    """Attach a line icon to a button and repaint it when the theme changes."""
    button.setIcon(line(name))
    _bound.append((weakref.ref(button), name))


def _on_theme(_t) -> None:
    alive = []
    for ref, name in _bound:
        w = ref()
        if w is None:
            continue
        try:
            w.setIcon(line(name))
            alive.append((ref, name))
        except RuntimeError:
            pass  # C++ object already deleted
    _bound[:] = alive


theme.manager.changed.connect(_on_theme)


def kind_of(filename: str) -> tuple[str, str]:
    ext = posixpath.splitext(filename)[1].lower().lstrip(".")
    for _key, (label, color, exts) in KINDS.items():
        if ext in exts:
            return tr(label), color
    return (tr("{ext} file", ext=ext.upper()) if ext else tr("Document")), "#C7C7CC"


def folder(link: bool = False) -> QIcon:
    key = ("folder", link)
    if key not in _cache:
        _cache[key] = _icon_from_svg(FOLDER, LINK_BADGE if link else None)
    return _cache[key]


def file(filename: str, link: bool = False) -> QIcon:
    _, band = kind_of(filename)
    key = ("file", band, link)
    if key not in _cache:
        _cache[key] = _icon_from_svg(DOC.format(band=band), LINK_BADGE if link else None)
    return _cache[key]


def app_pixmap(path: str, size: int) -> QPixmap:
    pm = QIcon(path).pixmap(QSize(size, size))
    return pm


def dot(color: str) -> QIcon:
    """A small filled status dot."""
    key = ("dot", color)
    if key not in _cache:
        _cache[key] = _icon_from_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                                     f'<circle cx="12" cy="12" r="5" fill="{color}"/></svg>')
    return _cache[key]
