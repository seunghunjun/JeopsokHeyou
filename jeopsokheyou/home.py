# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Home tab (Termius-style): a menu on the left and one screen per menu item —
Hosts, Keychain, Port Forwarding, Snippets, Known Hosts, History — plus Settings."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import config, icons, library, theme, vault
from .config import Session
from .dialogs import SessionDialog
from .i18n import tr
from .tunnels import TunnelsPage

# (key, English label, icon)
PAGES = (("start", "Start page", "home"), ("hosts", "Hosts", "server"), ("keychain", "Keychain", "key"),
         ("forwarding", "Port Forwarding", "tunnel"), ("snippets", "Snippets", "code"),
         ("known_hosts", "Known Hosts", "shield"), ("history", "History", "clock"))


# ------------------------------------------------------------------ helpers
class FlowLayout(QLayout):
    """Lays out cards left to right, wrapping to the next row (Qt's flow layout example)."""

    def __init__(self, parent=None, spacing: int = 12):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            w = it.sizeHint()
            if x + w.width() > rect.right() + 1 and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + self._spacing, 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), w))
            x += w.width() + self._spacing
            line_h = max(line_h, w.height())
        return y + line_h - rect.y()

    def clear(self):
        while self._items:
            it = self._items.pop()
            w = it.widget()
            if w:
                # Take it off screen now — deleteLater alone can leave the old card painted under the new one
                w.hide()
                w.setParent(None)
                w.deleteLater()


def page_header(title: str) -> tuple[QHBoxLayout, QLabel]:
    row = QHBoxLayout()
    lb = QLabel(title)
    lb.setObjectName("PageTitle")
    row.addWidget(lb)
    row.addStretch(1)
    return row, lb


def section(text: str) -> QLabel:
    lb = QLabel(text.upper() if text.isascii() else text)
    lb.setObjectName("Section")
    return lb


def primary(text: str, icon: str | None = None) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("Primary")
    if icon:
        b.setIcon(icons.line(icon, "#FFFFFF"))
    return b


def table(cols: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.verticalHeader().hide()
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    hh.setStretchLastSection(True)
    return t


def item(text: str, data=None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    return it


def selected_rows(t: QTableWidget) -> list[int]:
    return sorted({i.row() for i in t.selectedIndexes()})


# ------------------------------------------------------------------ cards
class Card(QFrame):
    """A Termius-style card: colored icon tile, title, subtitle. Double-click opens; right-click shows a menu."""
    activated = Signal()
    clicked = Signal()
    menu_requested = Signal(QPoint)
    edit_requested = Signal()

    def __init__(self, title: str, subtitle: str, icon: str, tile: str, editable: bool = True):
        super().__init__()
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(272, 64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 8, 10)
        lay.setSpacing(10)
        tile_lb = QLabel()
        tile_lb.setObjectName("Tile")
        tile_lb.setFixedSize(38, 38)
        tile_lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile_lb.setStyleSheet(f"background: {tile}; border-radius: 9px;")
        tile_lb.setPixmap(icons.line(icon, "#FFFFFF").pixmap(20, 20))
        lay.addWidget(tile_lb)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("Muted")
        for lb in (self.title, self.subtitle):
            lb.setMinimumWidth(10)
            lb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        lay.addLayout(text, 1)
        self.edit_btn = None
        if editable:
            self.edit_btn = QToolButton()
            self.edit_btn.setIcon(icons.line("pencil"))
            self.edit_btn.setToolTip(tr("Edit…"))
            self.edit_btn.clicked.connect(self.edit_requested)
            self.edit_btn.setVisible(False)
            lay.addWidget(self.edit_btn)
        self.setToolTip(f"{title}\n{subtitle}")

    def enterEvent(self, e):
        if self.edit_btn:
            self.edit_btn.setVisible(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.edit_btn:
            self.edit_btn.setVisible(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def set_selected(self, on: bool):
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()

    def contextMenuEvent(self, e):
        self.menu_requested.emit(e.globalPos())


TILE_COLORS = ("#0A84FF", "#30B0C7", "#34C759", "#FF9F0A", "#AF52DE", "#FF375F", "#5E5CE6", "#64D2FF")


def tile_color(key: str) -> str:
    return TILE_COLORS[sum(map(ord, key)) % len(TILE_COLORS)]


# ------------------------------------------------------------------ Start page (the 1.0.x start screen)
class WelcomePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("Welcome")
        outer = QVBoxLayout(self)
        outer.addStretch(2)
        col = QVBoxLayout()
        col.setSpacing(6)
        logo = QLabel()
        ico = config.paths.ASSETS / "app.png"
        if ico.exists():
            logo.setPixmap(icons.app_pixmap(str(ico), 88))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("JeopsokHeyou")
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel(tr("Pick a session, or enter user@host:port in the box above"))
        sub.setObjectName("Muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(logo)
        col.addWidget(title)
        col.addWidget(sub)
        col.addSpacing(18)
        self.recent_label = QLabel(tr("Recent sessions"))
        self.recent_label.setObjectName("Section")
        col.addWidget(self.recent_label, 0, Qt.AlignmentFlag.AlignHCenter)
        from PySide6.QtWidgets import QGridLayout
        self.recent_grid = QGridLayout()
        self.recent_grid.setSpacing(10)
        col.addLayout(self.recent_grid)
        col.addSpacing(18)
        hint = QLabel(tr("Ctrl+Shift+D split left/right · Ctrl+Shift+E split top/bottom · Ctrl+Shift+T duplicate tab · "
                         "Ctrl+Shift+W close pane\n"
                         "Drag = copy · Right-click = paste · Ctrl+Wheel = font size"))
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addLayout(col)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(3)
        self.refresh()

    def refresh(self):
        while self.recent_grid.count():
            it = self.recent_grid.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        store = self.main.store
        order = [sid for sid in self.main.settings.get("recent", []) if store.get(sid)]
        order += [s.id for s in store.sessions if s.id not in order]
        for i, sid in enumerate(order[:6]):
            s = store.get(sid)
            b = QPushButton(f"{s.title()}\n{s.user}@{s.host}" + (f"  ·  {s.group}" if s.group else ""))
            b.setObjectName("Card")
            b.setIcon(icons.line("server", theme.current().accent))
            b.setIconSize(QSize(22, 22))
            b.setMinimumWidth(230)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=s: self.main.open_session(s))
            self.recent_grid.addWidget(b, i // 2, i % 2)
        self.recent_label.setVisible(bool(order))


# ------------------------------------------------------------------ Hosts
class HostsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.group = ""            # "" = all hosts (root)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # Left: group / subgroup / host tree to jump anywhere
        tree_box = QFrame()
        tree_box.setObjectName("Sidebar")
        tree_box.setFixedWidth(230)
        tl = QVBoxLayout(tree_box)
        tl.setContentsMargins(6, 14, 6, 8)
        tl.setSpacing(4)
        # "All hosts" row with the hide button on its right (kept out of the tree so selections stay whole)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.all_hosts_btn = QPushButton(tr("All hosts"))
        home_icon = icons.line("home")
        home_icon.addPixmap(icons.line("home", "#FFFFFF").pixmap(18, 18), home_icon.Mode.Normal, home_icon.State.On)
        self.all_hosts_btn.setIcon(home_icon)     # white icon while selected
        self.all_hosts_btn.setObjectName("TreeHead")
        self.all_hosts_btn.setCheckable(True)
        self.all_hosts_btn.clicked.connect(lambda: QTimer.singleShot(0, lambda: self.open_group("")))
        head.addWidget(self.all_hosts_btn, 1)
        self.tree_hide_btn = QToolButton()
        self.tree_hide_btn.setIcon(icons.line("sidebar"))
        self.tree_hide_btn.setToolTip(tr("Hide the host list"))
        self.tree_hide_btn.clicked.connect(self.toggle_tree)
        head.addWidget(self.tree_hide_btn)
        tl.addLayout(head)
        self.tree = QTreeWidget()
        self.tree.setObjectName("HostTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.itemDoubleClicked.connect(self._tree_double)
        self.tree.itemExpanded.connect(lambda it: self._collapsed.discard(self._tree_key(it)))
        self.tree.itemCollapsed.connect(lambda it: self._collapsed.add(self._tree_key(it)))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self._collapsed: set[str] = set()
        tl.addWidget(self.tree)
        outer.addWidget(tree_box)
        # Collapsed: a slim strip with a button to bring the tree back
        strip = QFrame()
        strip.setObjectName("Sidebar")
        strip.setFixedWidth(36)
        sl = QVBoxLayout(strip)
        sl.setContentsMargins(4, 14, 4, 8)
        self.tree_expand_btn = QToolButton()
        self.tree_expand_btn.setIcon(icons.line("sidebar"))
        self.tree_expand_btn.setToolTip(tr("Show the host list"))
        self.tree_expand_btn.clicked.connect(self.toggle_tree)
        sl.addWidget(self.tree_expand_btn)
        sl.addStretch(1)
        outer.addWidget(strip)
        self.tree_box, self.tree_strip = tree_box, strip
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.setSpacing(12)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText(tr("Search hosts, or type user@host to connect"))
        self.search.addAction(icons.line("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self._enter)
        top.addWidget(self.search, 1)
        self.new_btn = primary(tr("New host"), "plus")
        self.new_btn.clicked.connect(lambda: self.edit(None))
        top.addWidget(self.new_btn)
        grp = QPushButton(tr("New group"))
        grp.clicked.connect(lambda: self.main.add_group(parent=self.group))   # inside a group: a subgroup
        top.addWidget(grp)
        imp = QToolButton()
        imp.setText(tr("Import"))
        imp.setObjectName("Button")
        imp.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(imp)
        m.addAction(tr("Import PuTTY sessions"), self.main.import_putty)
        m.addAction(tr("Import Tabby sessions"), self.main.import_tabby)
        m.addAction(tr("Import MobaXterm sessions…"), self.main.import_mobaxterm)
        m.addAction(tr("Import OpenSSH config…"), self.main.import_ssh_config)
        m.addAction(tr("Import iTerm2 profiles…"), self.main.import_iterm)
        imp.setMenu(m)
        self.import_menu = m
        top.addWidget(imp)
        lay.addLayout(top)
        # Path of the open group: every step can be clicked ("All hosts › A › B › C")
        crumbs = QHBoxLayout()
        crumbs.setSpacing(2)
        self.back = QToolButton()
        self.back.setIcon(icons.line("back"))
        self.back.clicked.connect(lambda: self.open_group(config.group_parent(self.group)))   # one level up
        crumbs.addWidget(self.back)
        self.crumb_box = QWidget()
        self.crumb_lay = QHBoxLayout(self.crumb_box)
        self.crumb_lay.setContentsMargins(0, 0, 0, 0)
        self.crumb_lay.setSpacing(0)
        crumbs.addWidget(self.crumb_box)
        crumbs.addStretch(1)
        lay.addLayout(crumbs)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("Page")
        # Right-click on empty space: new host / group, import, and actions for the open group
        inner.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        inner.customContextMenuRequested.connect(lambda pos: self._page_menu(inner.mapToGlobal(pos)))
        self.inner_lay = QVBoxLayout(inner)
        self.inner_lay.setContentsMargins(0, 0, 0, 0)
        self.inner_lay.setSpacing(10)
        self.groups_label = section(tr("Groups"))
        self.groups_box = QWidget()
        self.groups_flow = FlowLayout(self.groups_box)
        self.hosts_label = section(tr("Hosts"))
        self.hosts_box = QWidget()
        self.hosts_flow = FlowLayout(self.hosts_box)
        self.empty = QLabel()
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        for w in (self.groups_label, self.groups_box, self.hosts_label, self.hosts_box, self.empty):
            self.inner_lay.addWidget(w)
        self.inner_lay.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        outer.addWidget(body, 1)
        # Right-side edit panel (like Termius)
        self.panel = QFrame()
        self.panel.setObjectName("EditPanel")
        self.panel.setFixedWidth(500)
        self.panel_lay = QVBoxLayout(self.panel)
        self.panel_lay.setContentsMargins(16, 14, 16, 12)
        head = QHBoxLayout()
        self.panel_title = QLabel()
        self.panel_title.setObjectName("PageTitle")
        head.addWidget(self.panel_title, 1)
        self.panel_close = QToolButton()
        self.panel_close.setIcon(icons.line("close"))
        self.panel_close.setToolTip(tr("Close"))
        self.panel_close.clicked.connect(self.close_panel)
        head.addWidget(self.panel_close)
        self.panel_lay.addLayout(head)
        self.editing_id = ""
        self.selected_id = ""
        self.editor: QScrollArea | None = None
        self.editor_dialog: SessionDialog | None = None
        self.panel.hide()
        outer.addWidget(self.panel)
        self.cards: dict[str, Card] = {}
        self.refresh()
        self._apply_tree_visibility()

    # --- data
    def _visible_sessions(self) -> list[Session]:
        q = self.search.text().strip().lower()
        out = []
        for s in self.main.store.sessions:
            if q:
                if q in f"{s.title()} {s.host} {s.user} {s.group}".lower():
                    out.append(s)
            elif not self.group or s.group == self.group:
                out.append(s)          # top level: every host; inside a group: the hosts directly in it
        return sorted(out, key=lambda x: (x.group.lower(), x.title().lower()))

    # --- tree
    TREE_ROLE = Qt.ItemDataRole.UserRole

    @staticmethod
    def _tree_key(it: QTreeWidgetItem) -> str:
        kind, value = it.data(0, HostsPage.TREE_ROLE)
        return value if kind == "group" else ""

    def refresh_tree(self):
        t = self.tree
        t.blockSignals(True)
        t.clear()
        th = theme.current()
        root = t.invisibleRootItem()
        nodes = {"": root}
        paths = set()
        for g in self.main.store.groups():
            parts = g.split(config.GROUP_SEP)
            for i in range(1, len(parts) + 1):
                paths.add(config.GROUP_SEP.join(parts[:i]))
        folder = icons.line_selectable("folder", th.icon, th.accent_text)
        for g in sorted(paths, key=lambda x: (x.count(config.GROUP_SEP), x.lower())):
            it = QTreeWidgetItem([config.group_leaf(g)])
            it.setData(0, self.TREE_ROLE, ("group", g))
            it.setIcon(0, folder)
            nodes.get(config.group_parent(g), root).addChild(it)
            nodes[g] = it
        server = icons.line_selectable("server", th.accent, th.accent_text)
        for s in sorted(self.main.store.sessions, key=lambda x: x.title().lower()):
            it = QTreeWidgetItem([s.title()])
            it.setData(0, self.TREE_ROLE, ("host", s.id))
            it.setIcon(0, server)
            it.setToolTip(0, f"{s.user + '@' if s.user else ''}{s.host}:{s.port}")
            parent = nodes.get(s.group, root)
            if parent is root:
                parent.addChild(it)          # ungrouped hosts after the groups
            else:                            # a group's own hosts right under it, before its subgroups
                pos = sum(1 for i in range(parent.childCount()) if parent.child(i).data(0, self.TREE_ROLE)[0] == "host")
                parent.insertChild(pos, it)
        for key, it in nodes.items():
            if key:
                it.setExpanded(key not in self._collapsed)
        # The tree follows the open group; a host is highlighted only right after it is clicked
        if self.group and self.group in nodes:
            t.setCurrentItem(nodes[self.group])
        else:
            t.setCurrentItem(None)
            t.clearSelection()
        self.all_hosts_btn.setChecked(not self.group)
        t.blockSignals(False)

    def toggle_tree(self):
        self.main.settings["show_host_tree"] = not bool(self.main.settings.get("show_host_tree", True))
        self._apply_tree_visibility()

    def _apply_tree_visibility(self):
        shown = bool(self.main.settings.get("show_host_tree", True))
        self.tree_box.setVisible(shown)
        self.tree_strip.setVisible(not shown)

    def _tree_items(self):
        out, stack = [], [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            out.append(it)
            stack.extend(it.child(i) for i in range(it.childCount()))
        return out

    def _tree_clicked(self, it, _col=0):
        kind, value = it.data(0, self.TREE_ROLE)
        # The tree is rebuilt on refresh — act after this click finishes
        if kind == "group":
            QTimer.singleShot(0, lambda: self.open_group(value))
        else:
            s = self.main.store.get(value)
            if s:
                QTimer.singleShot(0, lambda: self._host_clicked(s))

    def _tree_double(self, it, _col=0):
        kind, value = it.data(0, self.TREE_ROLE)
        s = self.main.store.get(value) if kind == "host" else None
        if s:
            QTimer.singleShot(0, lambda: self.main.open_session(s))

    def _tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        gpos = self.tree.viewport().mapToGlobal(pos)
        if it is None:
            return self._page_menu(gpos)
        kind, value = it.data(0, self.TREE_ROLE)
        if kind == "host" and self.main.store.get(value):
            self._host_menu(self.main.store.get(value), gpos)
        elif value:
            self._group_menu(value, gpos)
        else:
            self._page_menu(gpos)

    def refresh(self):
        q = self.search.text().strip()
        self.refresh_tree()
        self.groups_flow.clear()
        self.hosts_flow.clear()
        self.cards = {}
        store = self.main.store
        in_group = bool(self.group) and not q
        self.back.setVisible(in_group)
        self.crumb_box.setVisible(in_group)
        parent = config.group_parent(self.group)
        self.back.setToolTip(config.group_leaf(parent) if parent else tr("All hosts"))
        self._build_crumbs()
        groups = [] if q else self._child_groups(self.group)
        for g in groups:
            n = sum(1 for s in store.sessions if config.in_group(s.group, g))
            c = Card(config.group_leaf(g), tr("1 host") if n == 1 else tr("{n} hosts", n=n), "folder", "#8E8E93",
                     editable=False)
            c.clicked.connect(lambda g=g: self.open_group(g))
            c.menu_requested.connect(lambda pos, g=g: self._group_menu(g, pos))
            self.groups_flow.addWidget(c)
        self.groups_label.setVisible(bool(groups))
        self.groups_box.setVisible(bool(groups))
        sessions = self._visible_sessions()
        for s in sessions:
            sub = f"{s.user + '@' if s.user else ''}{s.host}" + (f":{s.port}" if int(s.port or 22) != 22 else "")
            if s.group and (q or not self.group):
                sub += f"  ·  {s.group}"
            c = Card(s.title(), sub, "server", tile_color(s.group or s.title()))
            c.activated.connect(lambda s=s: self.main.open_session(s))
            c.clicked.connect(lambda s=s: self._host_clicked(s))
            c.edit_requested.connect(lambda s=s: self.edit(s))
            c.menu_requested.connect(lambda pos, s=s: self._host_menu(s, pos))
            self.hosts_flow.addWidget(c)
            self.cards[s.id] = c
            c.set_selected(s.id == (self.editing_id or self.selected_id))
        self.hosts_label.setVisible(bool(sessions))
        self.hosts_box.setVisible(bool(sessions))
        if q and not sessions:
            self.empty.setText(tr("No hosts match. Press Enter to connect to {target}.", target=q)
                               if Session.parse_quick(q) else tr("No hosts match."))
        elif not store.sessions:
            self.empty.setText(tr("No hosts yet. Add one with New host, or import from PuTTY, Tabby, "
                                  "MobaXterm or an SSH config file."))
        else:
            self.empty.setText("")
        self.empty.setVisible(bool(self.empty.text()))

    def _build_crumbs(self):
        while self.crumb_lay.count():
            it = self.crumb_lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        if not self.group:
            return
        parts = self.group.split(config.GROUP_SEP)
        steps = [("", tr("All hosts"))] + [(config.GROUP_SEP.join(parts[:i + 1]), parts[i]) for i in range(len(parts))]
        for i, (path, label) in enumerate(steps):
            if i:
                sep = QLabel("›")
                sep.setObjectName("Muted")
                self.crumb_lay.addWidget(sep)
            if i == len(steps) - 1:
                cur = QLabel(label)
                cur.setObjectName("PageTitle")
                cur.setContentsMargins(6, 0, 0, 0)
                self.crumb_lay.addWidget(cur)
            else:
                b = QPushButton(label)
                b.setObjectName("Crumb")
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setProperty("path", path)
                b.clicked.connect(lambda _=False, p=path: QTimer.singleShot(0, lambda: self.open_group(p)))
                self.crumb_lay.addWidget(b)

    def crumb_buttons(self) -> list[QPushButton]:
        return [self.crumb_lay.itemAt(i).widget() for i in range(self.crumb_lay.count())
                if isinstance(self.crumb_lay.itemAt(i).widget(), QPushButton)]

    def _child_groups(self, parent: str) -> list[str]:
        """Groups one level below ``parent`` ("" = top level), including path parts that only exist
        because a deeper subgroup has them (e.g. "A / B / C" also gives "A" and "A / B")."""
        out = []
        prefix = parent + config.GROUP_SEP if parent else ""
        for g in self.main.store.groups():
            if parent and not g.startswith(prefix):
                continue
            first = g[len(prefix):].split(config.GROUP_SEP)[0]
            if first:
                out.append(prefix + first)
        return sorted(dict.fromkeys(out), key=str.lower)

    def open_group(self, g: str):
        self.group = g
        self.selected_id = ""      # choosing a group moves the focus off the previously selected host
        self.search.clear()
        self.refresh()

    def _enter(self):
        sessions = self._visible_sessions()
        q = self.search.text().strip()
        if len(sessions) == 1:
            self.main.open_session(sessions[0])
        elif not sessions and q:
            s = Session.parse_quick(q)
            if s:
                self.search.clear()
                self.main.open_session(s)

    # --- menus
    def _host_menu(self, s: Session, pos: QPoint):
        m = QMenu(self)
        m.addAction(tr("Connect"), lambda: self.main.open_session(s))
        m.addAction(tr("Edit…"), lambda: self.edit(s))
        m.addAction(tr("Duplicate"), lambda: self.main._clone_session(s))
        mv = m.addMenu(tr("Move to group"))
        for g in self.main.store.groups():
            a = mv.addAction(g, lambda g=g: self.main._move_sessions([s.id], g))
            a.setEnabled(g != s.group)
        mv.addSeparator()
        mv.addAction(tr("(No group)"), lambda: self.main._move_sessions([s.id], "")).setEnabled(bool(s.group))
        mv.addAction(tr("Move to new group…"), lambda: self.main.add_group(move_ids=[s.id]))
        m.addAction(tr("New tunnel through this host…"), lambda: self.main.home.new_tunnel(s.id))
        m.addSeparator()
        m.addAction(tr("Delete"), lambda: self.main._delete_session(s))
        m.exec(pos)

    def page_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction(icons.line("plus"), tr("New host"), lambda: self.edit(None, self.group))
        m.addAction(tr("New subgroup…") if self.group else tr("New group"),
                    lambda: self.main.add_group(parent=self.group))
        if self.group:
            g = self.group
            m.addSeparator()
            m.addAction(tr("Rename group…"), lambda: self.main.rename_group(g))
            m.addAction(tr("Delete group"), lambda: self.main.remove_group(g))
        m.addSeparator()
        imp = m.addMenu(tr("Import"))
        for a in self.import_menu.actions():
            imp.addAction(a)
        return m

    def _page_menu(self, pos: QPoint):
        self.page_menu().exec(pos)

    def _group_menu(self, g: str, pos: QPoint):
        m = QMenu(self)
        m.addAction(tr("Open"), lambda: self.open_group(g))
        m.addSeparator()
        m.addAction(tr("New host in this group"), lambda: self.edit(None, g))
        m.addAction(tr("New subgroup…"), lambda: self.main.add_group(parent=g))
        m.addSeparator()
        m.addAction(tr("Rename group…"), lambda: self.main.rename_group(g))
        m.addAction(tr("Delete group"), lambda: self.main.remove_group(g))
        m.exec(pos)

    # --- edit panel
    def _host_clicked(self, s: Session):
        """One click selects a host. The edit panel opens from Edit (pencil / right-click); while it is open,
        clicking another host shows that host in it."""
        self.selected_id = s.id
        if self.editor is not None:
            self.edit(s)
        else:
            self._mark_selected()

    def edit(self, s: Session | None, group: str = ""):
        """Open the side panel for a host (or a new one). Picking another host swaps its details in."""
        if s is not None and s.id == self.editing_id and self.editor is not None:
            return                      # already showing this host — keep what was typed
        self.close_panel()
        self.editing_id = s.id if s else ""
        self.selected_id = self.editing_id or self.selected_id
        self._mark_selected()
        copy = Session.from_dict(dict(s.__dict__)) if s else None
        d = SessionDialog(copy, self.main._groups(), self, sessions=self.main.store.sessions)
        d.setWindowFlags(Qt.WindowType.Widget)
        if not s:
            d.group.setCurrentText(group or self.group)
        d.accepted.connect(lambda: self._saved(d, s is None))
        d.rejected.connect(self.close_panel)
        self.panel_title.setText(tr("Edit host") if s else tr("New host"))
        d.setMinimumWidth(0)
        holder = QScrollArea()
        holder.setWidgetResizable(True)
        holder.setFrameShape(QFrame.Shape.NoFrame)
        holder.setWidget(d)
        self.panel_lay.addWidget(holder, 1)
        self.editor = holder
        self.editor_dialog = d
        self.panel.show()
        d.show()
        d.host.setFocus() if not s else d.name.setFocus()

    def _saved(self, d: SessionDialog, new: bool):
        self.main.store.upsert(d.session)
        self.close_panel()
        self.main.reload_sessions()

    def close_panel(self):
        if self.editor is not None:
            self.editor.setParent(None)
            self.editor.deleteLater()
            self.editor = None
            self.editor_dialog = None
        self.panel.hide()
        self.editing_id = ""
        self._mark_selected()

    def _mark_selected(self):
        current = self.editing_id or self.selected_id
        for sid, card in self.cards.items():
            card.set_selected(sid == current)
        if current:
            for it in self._tree_items():
                if it.data(0, self.TREE_ROLE) == ("host", current):
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(it)
                    self.tree.blockSignals(False)


# ------------------------------------------------------------------ Keychain
class KeychainPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 14)
        lay.setSpacing(10)
        head, _ = page_header(tr("Keychain"))
        lay.addLayout(head)

        lay.addWidget(section(tr("Master password")))
        mp = QHBoxLayout()
        self.vault_status = QLabel()
        self.vault_status.setWordWrap(True)
        mp.addWidget(self.vault_status, 1)
        self.lock_btn = QPushButton(icons.line("lock"), tr("Lock now"))
        self.lock_btn.clicked.connect(lambda: (vault.lock(), self.refresh()))
        manage = QPushButton(tr("Master password…"))
        manage.clicked.connect(lambda: (self.main.open_vault_settings(), self.refresh()))
        mp.addWidget(self.lock_btn)
        mp.addWidget(manage)
        lay.addLayout(mp)

        keys_head = QHBoxLayout()
        keys_head.addWidget(section(tr("SSH keys")))
        keys_head.addStretch(1)
        gen = primary(tr("Generate key…"), "plus")
        gen.clicked.connect(self.generate)
        copy = QPushButton(tr("Copy public key"))
        copy.clicked.connect(self.copy_public)
        keys_head.addWidget(copy)
        keys_head.addWidget(gen)
        lay.addLayout(keys_head)
        self.keys = table([tr("Name"), tr("Type"), tr("Used by"), tr("Path")])
        self.keys.cellDoubleClicked.connect(lambda *_: self.copy_public())
        lay.addWidget(self.keys, 1)

        pw_head = QHBoxLayout()
        pw_head.addWidget(section(tr("Saved passwords")))
        pw_head.addStretch(1)
        forget = QPushButton(tr("Forget"))
        forget.clicked.connect(self.forget)
        pw_head.addWidget(forget)
        lay.addLayout(pw_head)
        self.secrets = table([tr("Host"), tr("Secret"), tr("Protected by")])
        lay.addWidget(self.secrets, 1)
        self.refresh()

    def refresh(self):
        if not vault.enabled():
            self.vault_status.setText(tr("Off — saved passwords are protected by your {os} account.",
                                         os=config.paths.OS_NAME))
        else:
            self.vault_status.setText(tr("On — unlocked.") if vault.unlocked() else tr("On — locked."))
        self.lock_btn.setEnabled(vault.unlocked())
        keys = library.key_files(self.main.store.sessions)
        self.keys.setRowCount(len(keys))
        for r, k in enumerate(keys):
            name = k["name"] + ("" if k["exists"] else "  " + tr("(missing)"))
            self.keys.setItem(r, 0, item(name, str(k["path"])))
            self.keys.setItem(r, 1, item(k["type"]))
            self.keys.setItem(r, 2, item(", ".join(k["used_by"])))
            self.keys.setItem(r, 3, item(str(k["path"])))
        rows = []
        for s in self.main.store.sessions:
            for f, label in (("password", "Password"), ("passphrase", "Key passphrase")):
                tok = getattr(s, f + "_enc")
                if tok:
                    by = tr("Master password") if tok.startswith(vault.TOKEN_PREFIX) else \
                        (tr("macOS Keychain") if tok == config.KEYCHAIN_TOKEN else tr("{os} account", os=config.paths.OS_NAME))
                    rows.append((s, f, tr(label), by))
        self.secrets.setRowCount(len(rows))
        for r, (s, f, label, by) in enumerate(rows):
            self.secrets.setItem(r, 0, item(s.title(), (s.id, f)))
            self.secrets.setItem(r, 1, item(label))
            self.secrets.setItem(r, 2, item(by))

    def _selected_key(self) -> Path | None:
        rows = selected_rows(self.keys)
        return Path(self.keys.item(rows[0], 0).data(Qt.ItemDataRole.UserRole)) if rows else None

    def copy_public(self):
        p = self._selected_key()
        if p is None:
            QMessageBox.information(self, tr("Keychain"), tr("Select a key first."))
            return
        try:
            line = library.public_key(p)
        except Exception:
            pw, ok = QInputDialog.getText(self, tr("Key passphrase"), tr("Passphrase for {name}:", name=p.name),
                                          QLineEdit.EchoMode.Password)
            if not ok:
                return
            try:
                line = library.public_key(p, pw)
            except Exception as e:
                QMessageBox.warning(self, tr("Keychain"), tr("Could not read the key: {error}", error=e))
                return
        QGuiApplication.clipboard().setText(line)
        QMessageBox.information(self, tr("Keychain"),
                                tr("The public key was copied. Add it to ~/.ssh/authorized_keys on the server."))

    def generate(self):
        d = QDialog(self)
        d.setWindowTitle(tr("Generate key"))
        form = QFormLayout(d)
        name = QLineEdit("id_ed25519_jeopsokheyou")
        pw = QLineEdit()
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        pw.setPlaceholderText(tr("Optional"))
        form.addRow(tr("File name (in ~/.ssh)"), name)
        form.addRow(tr("Key passphrase"), pw)
        form.addRow(QLabel(tr("Type: ed25519 (recommended)")))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        form.addRow(bb)
        if not d.exec():
            return
        fname = name.text().strip()
        if not fname or "/" in fname or "\\" in fname or fname.startswith("."):
            QMessageBox.warning(self, tr("Check Input"), tr("Enter a plain file name."))
            return
        try:
            line = library.generate_ed25519(library.SSH_DIR / fname, pw.text(), "jeopsokheyou")
        except FileExistsError:
            QMessageBox.warning(self, tr("Generate key"), tr("{name} already exists.", name=fname))
            return
        QGuiApplication.clipboard().setText(line)
        QMessageBox.information(self, tr("Generate key"),
                                tr("Created {path}. The public key was copied to the clipboard.",
                                   path=library.SSH_DIR / fname))
        self.refresh()

    def forget(self):
        rows = selected_rows(self.secrets)
        if not rows:
            return
        if QMessageBox.question(self, tr("Forget"), tr("Forget the selected saved passwords?")) != \
                QMessageBox.StandardButton.Yes:
            return
        for r in rows:
            sid, f = self.secrets.item(r, 0).data(Qt.ItemDataRole.UserRole)
            s = self.main.store.get(sid)
            if s:
                config.delete_secret(f"{s.id}.{f}", getattr(s, f + "_enc"))
                setattr(s, f + "_enc", "")
        self.main.store.save()
        self.refresh()


# ------------------------------------------------------------------ Snippets
class SnippetDialog(QDialog):
    def __init__(self, snip: library.Snippet, parent=None):
        super().__init__(parent)
        self.snip = snip
        self.setWindowTitle(tr("Edit snippet") if snip.name else tr("New snippet"))
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.name = QLineEdit(snip.name)
        self.cmd = QPlainTextEdit(snip.command)
        self.cmd.setPlaceholderText("sudo systemctl restart nginx")
        self.cmd.setMinimumHeight(110)
        self.run = QCheckBox(tr("Run immediately (press Enter after pasting)"))
        self.run.setChecked(snip.run)
        form.addRow(tr("Name"), self.name)
        form.addRow(tr("Command"), self.cmd)
        form.addRow("", self.run)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _accept(self):
        if not self.cmd.toPlainText().strip():
            QMessageBox.warning(self, tr("Check Input"), tr("Enter a command."))
            return
        self.snip.command = self.cmd.toPlainText()
        self.snip.name = self.name.text().strip() or self.snip.command.strip().splitlines()[0][:40]
        self.snip.run = self.run.isChecked()
        self.accept()


class SnippetsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.store = main.snippets
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 14)
        head, _ = page_header(tr("Snippets"))
        self.send_btn = QPushButton(icons.line("terminal"), tr("Paste into terminal"))
        self.send_btn.clicked.connect(self.send_selected)
        new = primary(tr("New snippet"), "plus")
        new.clicked.connect(self.new)
        head.addWidget(self.send_btn)
        head.addWidget(new)
        lay.addLayout(head)
        note = QLabel(tr("Saved commands. Double-click one to paste it into the last terminal you used "
                         "(also from the terminal: Terminal → Snippets…, Ctrl+Shift+P)."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = table([tr("Name"), tr("Command"), tr("Run")])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda *_: self.send_selected())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)
        self.refresh()

    def refresh(self):
        sn = self.store.snippets
        self.table.setRowCount(len(sn))
        for r, s in enumerate(sn):
            first = s.command.strip().splitlines()[0] if s.command.strip() else ""
            more = " …" if len(s.command.strip().splitlines()) > 1 else ""
            self.table.setItem(r, 0, item(s.name, s.id))
            self.table.setItem(r, 1, item(first + more))
            self.table.setItem(r, 2, item("✓" if s.run else ""))

    def _selected(self) -> library.Snippet | None:
        rows = selected_rows(self.table)
        if not rows:
            return None
        sid = self.table.item(rows[0], 0).data(Qt.ItemDataRole.UserRole)
        return next((s for s in self.store.snippets if s.id == sid), None)

    def new(self):
        s = library.Snippet()
        if SnippetDialog(s, self).exec():
            self.store.upsert(s)
            self.refresh()

    def edit(self):
        s = self._selected()
        if s and SnippetDialog(s, self).exec():
            self.store.upsert(s)
            self.refresh()

    def delete(self):
        s = self._selected()
        if s and QMessageBox.question(self, tr("Delete"), tr("Delete snippet '{name}'?", name=s.name)) == \
                QMessageBox.StandardButton.Yes:
            self.store.remove(s.id)
            self.refresh()

    def send_selected(self):
        s = self._selected()
        if s:
            self.main.send_snippet(s)

    def _menu(self, pos):
        if not self._selected():
            return
        m = QMenu(self)
        m.addAction(tr("Paste into terminal"), self.send_selected)
        m.addAction(tr("Edit…"), self.edit)
        m.addAction(tr("Delete"), self.delete)
        m.exec(self.table.viewport().mapToGlobal(pos))


class SnippetPicker(QDialog):
    """Quick picker used from a terminal (Ctrl+Shift+P)."""

    def __init__(self, store: library.SnippetStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Snippets"))
        self.setMinimumSize(460, 320)
        self.store = store
        self.chosen: library.Snippet | None = None
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Search snippets"))
        self.filter.textChanged.connect(self.refresh)
        self.filter.returnPressed.connect(self._pick)
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _i: self._pick())
        lay.addWidget(self.filter)
        lay.addWidget(self.list, 1)
        self.refresh()

    def refresh(self):
        q = self.filter.text().strip().lower()
        self.list.clear()
        for s in self.store.snippets:
            if q and q not in (s.name + " " + s.command).lower():
                continue
            it = QListWidgetItem(f"{s.name}    —    {s.command.strip().splitlines()[0] if s.command.strip() else ''}")
            it.setData(Qt.ItemDataRole.UserRole, s.id)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _pick(self):
        it = self.list.currentItem()
        if it:
            sid = it.data(Qt.ItemDataRole.UserRole)
            self.chosen = next((s for s in self.store.snippets if s.id == sid), None)
            self.accept()


# ------------------------------------------------------------------ Known hosts
class KnownHostsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 14)
        head, _ = page_header(tr("Known Hosts"))
        rm = QPushButton(tr("Remove"))
        rm.clicked.connect(self.remove)
        head.addWidget(rm)
        lay.addLayout(head)
        note = QLabel(tr("Servers whose host key you trusted. If a server's key changed on purpose "
                         "(reinstalled or replaced), remove its entry here and connect again."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = table([tr("Host"), tr("Key type"), tr("Fingerprint")])
        lay.addWidget(self.table, 1)
        self.refresh()

    def refresh(self):
        rows = library.known_hosts()
        self.table.setRowCount(len(rows))
        for r, k in enumerate(rows):
            self.table.setItem(r, 0, item(tr("(hashed)") if k["hashed"] else k["host"], (k["host"], k["type"])))
            self.table.setItem(r, 1, item(k["type"]))
            self.table.setItem(r, 2, item(k["fingerprint"]))

    def remove(self):
        rows = selected_rows(self.table)
        if not rows:
            return
        names = ", ".join(self.table.item(r, 0).text() for r in rows)
        if QMessageBox.question(self, tr("Remove"), tr("Remove the trusted keys of {names}? "
                                                      "You will be asked to verify them again on the next connection.",
                                                      names=names)) != QMessageBox.StandardButton.Yes:
            return
        for r in rows:
            host, ktype = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            library.forget_known_host(host, ktype)
        self.refresh()


# ------------------------------------------------------------------ History
class HistoryPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 14)
        head, _ = page_header(tr("History"))
        connect = QPushButton(tr("Connect"))
        connect.clicked.connect(self.connect_selected)
        clear = QPushButton(tr("Clear history"))
        clear.clicked.connect(self.clear)
        head.addWidget(connect)
        head.addWidget(clear)
        lay.addLayout(head)
        self.table = table([tr("Time"), tr("Host"), tr("Address")])
        self.table.cellDoubleClicked.connect(lambda *_: self.connect_selected())
        lay.addWidget(self.table, 1)
        self.refresh()

    def refresh(self):
        rows = library.load_history()
        self.table.setRowCount(len(rows))
        for r, h in enumerate(rows):
            t = time.strftime("%Y-%m-%d %H:%M", time.localtime(h.get("time", 0)))
            s = self.main.store.get(h.get("session_id", ""))
            title = s.title() if s else h.get("title", "")
            addr = f"{h.get('user') + '@' if h.get('user') else ''}{h.get('host', '')}:{h.get('port', 22)}"
            self.table.setItem(r, 0, item(t, h))
            self.table.setItem(r, 1, item(title))
            self.table.setItem(r, 2, item(addr))

    def connect_selected(self):
        rows = selected_rows(self.table)
        if not rows:
            return
        h = self.table.item(rows[0], 0).data(Qt.ItemDataRole.UserRole)
        s = self.main.store.get(h.get("session_id", "")) or \
            Session(host=h.get("host", ""), user=h.get("user", ""), port=int(h.get("port", 22)))
        if s.host:
            self.main.open_session(s)

    def clear(self):
        if QMessageBox.question(self, tr("Clear history"), tr("Clear the connection history?")) == \
                QMessageBox.StandardButton.Yes:
            library.clear_history()
            self.refresh()


# ------------------------------------------------------------------ the tab
class HomeTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("Home")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        nav = QFrame()
        nav.setObjectName("NavBar")
        nav.setFixedWidth(210)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(10, 14, 10, 10)
        nl.setSpacing(6)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(18, 18))
        for key, label, icon in PAGES:
            it = QListWidgetItem(icons.line_selectable(icon, theme.current().icon, theme.current().accent_text), tr(label))
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(it)
        nl.addWidget(self.nav, 1)
        settings = QPushButton(icons.line("gear"), tr("Settings"))
        settings.setObjectName("NavButton")
        settings.clicked.connect(self.main.open_settings)
        nl.addWidget(settings)
        lay.addWidget(nav)
        self.stack = QStackedWidget()
        self.stack.setObjectName("Page")
        self.start = WelcomePage(main)
        self.hosts = HostsPage(main)
        self.keychain = KeychainPage(main)
        self.forwarding = TunnelsPage(main.tunnels)
        self.forwarding.layout().setContentsMargins(22, 18, 22, 14)
        self.snippets = SnippetsPage(main)
        self.known_hosts = KnownHostsPage(main)
        self.history = HistoryPage(main)
        self.pages = {"start": self.start, "hosts": self.hosts, "keychain": self.keychain, "forwarding": self.forwarding,
                      "snippets": self.snippets, "known_hosts": self.known_hosts, "history": self.history}
        for key, _l, _i in PAGES:
            self.stack.addWidget(self.pages[key])
        lay.addWidget(self.stack, 1)
        self.nav.currentRowChanged.connect(self._on_nav)
        # Clicking "Hosts" again goes back to the top level (all hosts)
        self.nav.itemClicked.connect(lambda it: self.hosts.open_group("")
                                     if it.data(Qt.ItemDataRole.UserRole) == "hosts" else None)
        self.nav.setCurrentRow(0)

    def _on_nav(self, row: int):
        if row < 0:
            return
        key = PAGES[row][0]
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        if hasattr(page, "refresh"):
            page.refresh()

    def show_page(self, key: str):
        keys = [k for k, _l, _i in PAGES]
        if key in keys:
            self.nav.setCurrentRow(keys.index(key))

    def new_tunnel(self, session_id: str = ""):
        self.main.tabs.setCurrentWidget(self)
        self.show_page("forwarding")
        self.forwarding.new_tunnel(session_id)

    def refresh_current(self):
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()
