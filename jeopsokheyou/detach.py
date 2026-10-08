# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Tear terminal tabs and split panes off into their own windows, and dock them back, by dragging.

- Tabs: drag a session tab away from the tab bar. Dropped on another window's tab bar it moves there;
  dropped outside the app it opens in a new window. Closing that window brings its tabs back.
- Panes: drag a pane's title bar onto another pane of the same connection to dock it on that
  side, or outside the app to give it a window of its own. Closing that window docks its panes back.
The connection is never touched: only widgets move.
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QObject, QPoint, QSize, Qt
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy,
                               QSplitter, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .i18n import tr

MIME_TAB = "application/x-jeopsokheyou-tab"
MIME_PANE = "application/x-jeopsokheyou-pane"
dragging: dict = {"tab": None, "pane": None}     # what is being dragged right now (same process only)


def _mime(kind: str) -> QMimeData:
    m = QMimeData()
    m.setData(kind, b"1")
    return m


def _pixmap(w: QWidget, width: int = 260):
    pix = w.grab()
    if pix.width() > width:
        pix = pix.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    return pix


def add_shortcuts(window: QWidget, main) -> None:
    """Menu shortcuts (split, close pane, find, …) also work in a detached window."""
    for a in main.findChildren(QAction):
        if not a.shortcut().isEmpty():
            window.addAction(a)


# ---------------------------------------------------------------- tabs
class DragTabBar(QTabBar):
    """Tab bar whose session tabs can be dragged out (new window) or onto another window's tab bar."""

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.setAcceptDrops(True)
        self._press: QPoint | None = None
        self._press_index = -1

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
            self._press_index = self.tabAt(self._press)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and e.buttons() & Qt.MouseButton.LeftButton:
            pos = e.position().toPoint()
            out = abs(pos.y() - self.rect().center().y()) > self.height() + 12
            if out and self._press_index >= 0:
                tabs = self.parentWidget()
                w = tabs.widget(self._press_index) if isinstance(tabs, QTabWidget) else None
                if self.main.is_session_tab(w):
                    self._press = None
                    release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, e.position(), e.globalPosition(),
                                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, e.modifiers())
                    super().mouseReleaseEvent(release)       # end Qt's own tab reordering cleanly
                    self.drag_tab(w)
                    return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def drag_tab(self, tab) -> None:
        start_tab_drag(self, tab)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_TAB) and dragging["tab"] is not None:
            e.setDropAction(Qt.DropAction.MoveAction)
            e.accept()
        else:
            e.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        tab = dragging["tab"]
        tabs = self.parentWidget()
        if tab is None or not isinstance(tabs, QTabWidget):
            e.ignore()
            return
        e.setDropAction(Qt.DropAction.MoveAction)
        e.accept()
        idx = self.tabAt(e.position().toPoint())
        self.main.move_tab(tab, tabs, idx if idx >= 0 else tabs.count())


def make_tabs(main, parent=None) -> QTabWidget:
    tabs = QTabWidget(parent)
    tabs.setTabBar(DragTabBar(main, tabs))
    tabs.setTabsClosable(True)
    tabs.setMovable(True)
    tabs.setDocumentMode(True)
    tabs.tabBar().setDrawBase(False)
    return tabs


class TabWindow(QMainWindow):
    """A window holding session tabs torn off the main window."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.tabs = make_tabs(main, self)
        self.tabs.tabCloseRequested.connect(lambda i: main.close_session_tab(self.tabs.widget(i)))
        self.tabs.currentChanged.connect(lambda _i: self._retitle())
        self.setCentralWidget(self.tabs)
        self.setWindowIcon(main.windowIcon())
        add_shortcuts(self, main)
        self._closing_quietly = False
        self.docker = MoveDocker(self, self._target_at, self._show_target, self._dock)

    # moving this window over the main window's tab bar puts its tabs back there
    def _target_at(self, pos: QPoint):
        bar = self.main.tabs.tabBar()
        area = bar.rect().adjusted(0, -12, self.main.tabs.width(), 12)
        return bar if self.main.isVisible() and area.contains(bar.mapFromGlobal(pos)) else None

    def _show_target(self, target):
        bar = self.main.tabs.tabBar()
        on = target is not None
        if bool(bar.property("dropHover")) != on:
            bar.setProperty("dropHover", on)
            bar.style().unpolish(bar)
            bar.style().polish(bar)

    def _dock(self, _target):
        while self.tabs.count():
            self.main.move_tab(self.tabs.widget(0), self.main.tabs, self.main.tabs.count())

    def moveEvent(self, e):
        super().moveEvent(e)
        self.docker.moved()

    def nativeEvent(self, event_type, message):
        self.docker.native(message)
        return super().nativeEvent(event_type, message)

    def _retitle(self):
        w = self.tabs.currentWidget()
        self.setWindowTitle(f"{w.session.title()} — JeopsokHeyou" if w is not None else "JeopsokHeyou")
        if w is None and not self._closing_quietly:
            self.close_quietly()

    def current(self):
        return self.tabs.currentWidget()

    def close_quietly(self):
        """Close without moving tabs back (used when it is already empty)."""
        self._closing_quietly = True
        self.close()

    def closeEvent(self, e):
        if not self._closing_quietly:
            self._closing_quietly = True
            while self.tabs.count():               # closing the window ends its sessions
                tab = self.tabs.widget(0)
                if hasattr(tab, "shutdown"):
                    tab.shutdown()
                self.tabs.removeTab(0)
                tab.deleteLater()
        if self in self.main.tab_windows:
            self.main.tab_windows.remove(self)
        super().closeEvent(e)


# ---------------------------------------------------------------- panes
def drop_zone(size: QSize, pos: QPoint) -> str:
    """Nearest edge of a pane: left / right / top / bottom."""
    w, h = max(1, size.width()), max(1, size.height())
    d = {"left": pos.x() / w, "right": 1 - pos.x() / w, "top": pos.y() / h, "bottom": 1 - pos.y() / h}
    return min(d, key=d.get)


class PaneWindow(QWidget):
    """A window holding panes torn off a session tab (they keep using that tab's connection)."""

    def __init__(self, tab):
        super().__init__(None, Qt.WindowType.Window)
        self.tab = tab
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.is_root = True
        lay.addWidget(self.split)
        self.setWindowTitle(f"{tab.session.title()} — JeopsokHeyou")
        self.setWindowIcon(tab.main.windowIcon())
        add_shortcuts(self, tab.main)
        self._closing_quietly = False
        self.docker = MoveDocker(self, self._target_at, self._show_target, self._dock)

    # moving this window over its tab docks it there
    def _target_at(self, pos: QPoint):
        tab = self.tab
        if not tab.isVisible():
            return None
        card = tab.empty_card
        if card is not None and card.isVisible() and card.rect().contains(card.mapFromGlobal(pos)):
            return (card, "card")
        for p in tab.panes:
            if p.window() is self or not p.isVisible() or not tab.term_split.isAncestorOf(p):
                continue
            local = p.mapFromGlobal(pos)
            if p.rect().contains(local):
                return (p, drop_zone(p.size(), local))
        return None

    def _show_target(self, target):
        if target is None:
            for p in self.tab.panes:
                if p._drop_zone:
                    p._drop_zone = None
                    p.update()
            if self.tab.empty_card is not None:
                self.tab.empty_card._set_hover(False)
            return
        w, zone = target
        if zone == "card":
            w._set_hover(True)
        else:
            w._drop_zone = zone
            w.update()

    def _dock(self, target):
        panes = self.panes()
        if not panes:
            return
        w, zone = target
        for p in panes:
            if zone == "card":
                self.tab.dock_pane_back(p)
            else:
                self.tab.dock_pane(p, w, zone)

    def moveEvent(self, e):
        super().moveEvent(e)
        self.docker.moved()

    def nativeEvent(self, event_type, message):
        self.docker.native(message)
        return super().nativeEvent(event_type, message)

    def retitle(self):
        p = self.panes()
        cwd = p[0].cwd if p else ""
        self.setWindowTitle(f"{self.tab.session.title()}{'  ·  ' + cwd if cwd else ''} — JeopsokHeyou")

    def panes(self) -> list:
        return [p for p in self.tab.panes if p.window() is self]

    def close_quietly(self):
        self._closing_quietly = True
        self.close()

    def closeEvent(self, e):
        panes = self.panes()
        if self in self.tab.pane_windows:
            self.tab.pane_windows.remove(self)
        if not self._closing_quietly:
            self._closing_quietly = True
            for p in panes:                           # closing the window ends its terminals
                self.tab.close_terminal(p)
        super().closeEvent(e)


# ---------------------------------------------------------------- pane title bar
class PaneBar(QFrame):
    """Thin bar on top of each terminal: drag it to move the pane, double-click to fill the tab with it."""

    def __init__(self, pane):
        super().__init__()
        self.pane = pane
        self.setObjectName("PaneBar")
        self.setFixedHeight(28)
        self.setToolTip(tr("Drag to move this terminal: onto another terminal to dock it, "
                           "or outside the window to open it in its own window. Double-click to fill the tab."))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 4, 0)
        lay.setSpacing(4)
        grip = QLabel("⠗")
        grip.setObjectName("PaneGrip")
        self.title = QLabel()
        self.title.setObjectName("PaneTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("PaneButton")
        self.close_btn.setText("✕")
        self.close_btn.setToolTip(tr("Close this terminal"))
        self.close_btn.setAutoRaise(True)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.clicked.connect(lambda: pane.close_requested.emit(pane))
        lay.addWidget(grip)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.close_btn)
        self._full = ""
        self._press: QPoint | None = None

    def set_title(self, text: str) -> None:
        self._full = text
        self._elide()

    def _elide(self):
        w = max(10, self.title.width())
        self.title.setText(self.title.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, w))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def set_active(self, on: bool) -> None:
        if bool(self.property("active")) != on:
            self.setProperty("active", on)
            for w in (self, self.title):
                w.style().unpolish(w)
                w.style().polish(w)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
            self.pane.setFocus()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and e.buttons() & Qt.MouseButton.LeftButton and \
                (e.position().toPoint() - self._press).manhattanLength() >= QGuiApplication.styleHints().startDragDistance():
            self._press = None
            tab = getattr(self.pane, "owner_tab", None)
            if tab is not None:
                tab.drag_pane(self.pane)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        tab = getattr(self.pane, "owner_tab", None)
        if tab is not None and e.button() == Qt.MouseButton.LeftButton:
            tab.toggle_maximize(self.pane)


class PaneFrame(QWidget):
    """What sits in a splitter: the title bar and the terminal under it."""

    def __init__(self, pane, show_bar: bool = True):
        super().__init__()
        self.pane = pane
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.bar = PaneBar(pane)
        self.bar.setVisible(show_bar)
        lay.addWidget(self.bar)
        lay.addWidget(pane, 1)


class EmptyTerminalCard(QFrame):
    """Shown in a tab whose terminals all went to other windows; also a place to drop them back."""

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setObjectName("EmptyTerminal")
        self.setAcceptDrops(True)
        self._hover = False
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        icon = QLabel("⧉")
        icon.setObjectName("EmptyIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(tr("The terminal is open in its own window"))
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel(tr("Closing that window ends the terminal."))
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        row = QHBoxLayout()
        row.addStretch(1)
        self.new_btn = QPushButton(tr("New terminal"))
        self.new_btn.setObjectName("Primary")
        self.new_btn.clicked.connect(tab.new_terminal_here)
        row.addWidget(self.new_btn)
        row.addStretch(1)
        for w in (icon, title, hint):
            lay.addWidget(w)
        lay.addSpacing(8)
        lay.addLayout(row)
        lay.addStretch(2)

    def _accepts(self, e) -> bool:
        p = dragging["pane"]
        return e.mimeData().hasFormat(MIME_PANE) and p is not None and getattr(p, "owner_tab", None) is self.tab

    def _set_hover(self, on: bool):
        if self._hover != on:
            self._hover = on
            self.setProperty("dropHover", on)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragEnterEvent(self, e):
        if self._accepts(e):
            self._set_hover(True)
            e.setDropAction(Qt.DropAction.MoveAction)
            e.accept()
        else:
            e.ignore()

    dragMoveEvent = dragEnterEvent

    def dragLeaveEvent(self, e):
        self._set_hover(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._set_hover(False)
        if not self._accepts(e):
            e.ignore()
            return
        p = dragging["pane"]
        e.setDropAction(Qt.DropAction.MoveAction)
        e.accept()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.tab.dock_pane_back(p))


# ---------------------------------------------------------------- dock a torn-off window by moving it back
WM_ENTERSIZEMOVE, WM_EXITSIZEMOVE = 0x0231, 0x0232


class MoveDocker:
    """Lets a torn-off window be docked by dragging the window itself (its system title bar) back over the
    main window: the drop place lights up while it moves and it docks when the mouse is released.

    Windows reports the start and end of a window move; elsewhere the end is taken as the moment the window
    stops moving with no mouse button down."""

    def __init__(self, window, find_target, show_target, dock):
        from PySide6.QtCore import QTimer
        self.window = window
        self.find_target = find_target      # global pos -> target or None
        self.show_target = show_target      # (target or None) -> highlight it
        self.dock = dock                    # target -> dock there
        self.target = None
        self.moving = False
        self.settle = QTimer(window)
        self.settle.setSingleShot(True)
        self.settle.setInterval(400)
        self.settle.timeout.connect(self._settled)

    def native(self, message) -> None:
        import sys
        if sys.platform != "win32":
            return
        import ctypes.wintypes
        msg = ctypes.wintypes.MSG.from_address(int(message))
        if msg.message == WM_ENTERSIZEMOVE:
            self.moving = True
        elif msg.message == WM_EXITSIZEMOVE:
            self.moving = False
            self.finish()

    def moved(self) -> None:
        import sys
        if sys.platform == "win32" and not self.moving:
            return                          # moved by the program, not by the user
        target = self.find_target(QCursor.pos())
        if target != self.target:
            self.show_target(None)
            self.target = target
            self.show_target(target)
        if sys.platform != "win32":
            self.settle.start()

    def _settled(self):
        if QGuiApplication.mouseButtons() == Qt.MouseButton.NoButton:
            self.finish()
        else:
            self.settle.start()

    def finish(self) -> None:
        target, self.target = self.target, None
        self.show_target(None)
        if target is not None:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.dock(target))


# ---------------------------------------------------------------- dragging a pane or a tab (handled by the app)
# Programs over which a terminal may not be torn off (exe names, from Settings)
BLOCKED_APPS: set[str] = set()
DESKTOP_CLASSES = {"Progman", "WorkerW"}
# Taskbar, Start menu, notification area, task view: nowhere to put a window
SYSTEM_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
                  "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland", "Xaml_WindowedPopupClass",
                  "MultitaskingViewFrame", "XamlExplorerHostIslandWindow"}


def set_blocked_apps(text: str) -> None:
    BLOCKED_APPS.clear()
    for part in (text or "").replace(";", ",").replace("\n", ",").split(","):
        name = part.strip().lower()
        if name:
            BLOCKED_APPS.add(name if name.endswith(".exe") else name + ".exe")


def tear_off_blocked(class_name: str, full_screen: bool, elevated: bool, exe: str) -> bool:
    """Whether a terminal may not be torn off over a window of another program:
    system areas, full-screen programs (slide shows, videos, games), programs running as administrator
    (Windows would keep our window behind them) and programs listed in Settings."""
    if class_name in DESKTOP_CLASSES:
        return False
    if class_name in SYSTEM_CLASSES:
        return True
    if full_screen or elevated:
        return True
    return bool(exe) and exe.lower() in BLOCKED_APPS


def _window_facts(root) -> tuple[str, bool, bool, str]:
    """(class name, full screen, running as administrator while we are not, exe name) — Windows only."""
    import ctypes
    import ctypes.wintypes as wt
    import os
    user32, kernel32, advapi32 = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.advapi32
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(root, buf, 256)
    cls = buf.value
    # full screen: the window covers its whole monitor and has no title bar
    full = False
    rect = wt.RECT()
    if user32.GetWindowRect(root, ctypes.byref(rect)):
        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
        user32.MonitorFromWindow.restype = wt.HMONITOR
        mon = user32.MonitorFromWindow(root, 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            m = mi.rcMonitor
            covers = rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom
            style = user32.GetWindowLongW(root, -16)          # GWL_STYLE
            full = covers and not (style & 0x00C00000)        # WS_CAPTION
    # process: exe name and elevation
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(root, ctypes.byref(pid))
    exe, elevated = "", False

    def is_elevated(handle) -> bool | None:
        token = wt.HANDLE()
        if not advapi32.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):   # TOKEN_QUERY
            return None
        try:
            val, size = wt.DWORD(), wt.DWORD()
            if advapi32.GetTokenInformation(token, 20, ctypes.byref(val), ctypes.sizeof(val), ctypes.byref(size)):
                return bool(val.value)                                           # TokenElevation
            return None
        finally:
            kernel32.CloseHandle(token)

    kernel32.OpenProcess.restype = wt.HANDLE
    h = kernel32.OpenProcess(0x1000, False, pid.value)                         # QUERY_LIMITED_INFORMATION
    if h:
        try:
            n = wt.DWORD(1024)
            path = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, path, ctypes.byref(n)):
                exe = os.path.basename(path.value)
            theirs = is_elevated(h)
        finally:
            kernel32.CloseHandle(h)
        mine = is_elevated(kernel32.GetCurrentProcess())
        # an elevated program's token can't be read from a normal one: that alone means it is elevated
        elevated = not mine and (theirs is None or theirs)
    return cls, full, elevated, exe


def foreign_window_at() -> bool:
    """Is the mouse over another program's window where a terminal may not be torn off? (Windows only;
    the desktop and ordinary windows are fine — the new window always comes to the front.)"""
    import sys
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.argtypes = [wt.POINT]
        user32.WindowFromPoint.restype = wt.HWND
        user32.GetAncestor.argtypes = [wt.HWND, ctypes.c_uint]
        user32.GetAncestor.restype = wt.HWND
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))            # physical pixels, like WindowFromPoint wants
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return False
        root = user32.GetAncestor(hwnd, 2) or hwnd       # GA_ROOT
        ours = {int(w.winId()) for w in QApplication.topLevelWidgets() if w.isVisible()}
        if int(root) in ours:
            return False
        return tear_off_blocked(*_window_facts(root))
    except Exception:
        return False


class ManualDrag(QObject):
    """Drag that the app follows itself (instead of the system drag and drop), so it can tell the desktop
    (tear off) from another program's window (not allowed) and show the right cursor."""

    def __init__(self, source: QWidget, pixmap, resolve, show, drop):
        super().__init__(source)
        self.source = source
        self.resolve = resolve          # global pos -> target tuple; ("none",) = not allowed here
        self.show = show                # target -> highlight it (None clears)
        self.drop = drop                # (target, global pos) -> act
        self.target = None
        self.preview = QLabel(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                              | Qt.WindowType.WindowTransparentForInput)
        self.preview.setPixmap(pixmap)
        self.preview.setWindowOpacity(0.8)
        self.preview.resize(pixmap.size())

    def start(self):
        QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)
        self.source.installEventFilter(self)
        self.source.grabMouse()
        self.source.grabKeyboard()
        self.preview.show()
        self.move(QCursor.pos())

    def move(self, pos: QPoint):
        self.preview.move(pos + QPoint(16, 16))
        target = self.resolve(pos)
        if target != self.target:
            self.show(None)
            self.target = target
            self.show(target)
            QApplication.changeOverrideCursor(Qt.CursorShape.ForbiddenCursor if target[0] == "none"
                                              else Qt.CursorShape.ClosedHandCursor)

    def end(self, pos):
        self.source.removeEventFilter(self)
        self.source.releaseMouse()
        self.source.releaseKeyboard()
        QApplication.restoreOverrideCursor()
        self.preview.hide()
        self.preview.deleteLater()
        target, self.target = self.target, None
        self.show(None)
        if pos is not None and target is not None and target[0] != "none":
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.drop(target, pos))
        self.deleteLater()

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        t = e.type()
        if t == QEvent.Type.MouseMove:
            self.move(e.globalPosition().toPoint())
            return True
        if t == QEvent.Type.MouseButtonRelease:
            self.end(e.globalPosition().toPoint())
            return True
        if t == QEvent.Type.KeyPress and e.key() == Qt.Key.Key_Escape:
            self.end(None)
            return True
        if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.KeyPress):
            return True
        return False


def our_widget_at(pos: QPoint):
    """Our widget under a screen point (None outside our windows). The active window is checked first."""
    tops = [w for w in QApplication.topLevelWidgets()
            if w.isVisible() and not (w.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            and w.windowType() not in (Qt.WindowType.ToolTip, Qt.WindowType.Popup)]
    tops.sort(key=lambda w: not w.isActiveWindow())
    for w in tops:
        if w.frameGeometry().contains(pos):
            return w.childAt(w.mapFromGlobal(pos)) or w
    return None


def _ancestor(w, test):
    while w is not None:
        if test(w):
            return w
        w = w.parentWidget()
    return None


def pane_target(tab, pane, pos: QPoint):
    """Where a dragged pane would go: ("dock", pane, zone) / ("card", card) / ("tear",) / ("none",)."""
    w = our_widget_at(pos)
    if w is None:
        return ("none",) if foreign_window_at() else ("tear",)
    card = _ancestor(w, lambda x: isinstance(x, EmptyTerminalCard))
    if card is not None and card.tab is tab:
        return ("card", card)
    other = _ancestor(w, lambda x: hasattr(x, "owner_tab") and hasattr(x, "_drop_zone"))
    if other is not None and other is not pane and other.owner_tab is tab and other.isVisible():
        return ("dock", other, drop_zone(other.size(), other.mapFromGlobal(pos)))
    return ("none",)


def start_pane_drag(tab, pane) -> None:
    def show(target):
        for p in tab.panes:
            if p._drop_zone:
                p._drop_zone = None
                p.update()
        if tab.empty_card is not None:
            tab.empty_card._set_hover(False)
        if target is None:
            return
        if target[0] == "dock":
            target[1]._drop_zone = target[2]
            target[1].update()
        elif target[0] == "card":
            target[1]._set_hover(True)

    def drop(target, pos):
        if target[0] == "dock":
            tab.dock_pane(pane, target[1], target[2])
        elif target[0] == "card":
            tab.dock_pane_back(pane)
        elif target[0] == "tear":
            tab.float_pane(pane, pos)

    source = pane.frame.bar if getattr(pane, "frame", None) is not None else pane
    ManualDrag(source, _pixmap(pane, 220), lambda pos: pane_target(tab, pane, pos), show, drop).start()


def tab_target(pos: QPoint):
    w = our_widget_at(pos)
    if w is None:
        return ("none",) if foreign_window_at() else ("tear",)
    bar = _ancestor(w, lambda x: isinstance(x, DragTabBar))
    return ("bar", bar) if bar is not None else ("none",)


def start_tab_drag(bar, tab) -> None:
    main = bar.main

    def show(target):
        for tw in main.tab_widgets():
            b = tw.tabBar()
            on = target is not None and target[0] == "bar" and target[1] is b
            if bool(b.property("dropHover")) != on:
                b.setProperty("dropHover", on)
                b.style().unpolish(b)
                b.style().polish(b)

    def drop(target, pos):
        if target[0] == "bar":
            b = target[1]
            idx = b.tabAt(b.mapFromGlobal(pos))
            tabs = b.parentWidget()
            main.move_tab(tab, tabs, idx if idx >= 0 else tabs.count())
        elif target[0] == "tear":
            main.float_tab(tab, pos)

    ManualDrag(bar, _pixmap(tab), tab_target, show, drop).start()
