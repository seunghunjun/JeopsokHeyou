# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Getting-started guide shown over the main window.

Shown automatically until it is finished or turned off; closing it part way (Skip, or quitting the app)
resumes at the same step next time. Help > Getting started guide runs it again from the start.
Progress lives in settings.json: "first_run_at" (first start) and "tour" {"step", "done", "dismissed"}.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget)

from . import config, icons, paths, theme
from .i18n import tr


@dataclass
class Step:
    key: str
    title: str
    body: str
    target: Callable | None = None     # main window -> widget to highlight (None: centred card)
    prepare: Callable | None = None    # main window -> None, run before the step is shown
    picture: str = ""                  # small drawing in the card for things not on screen yet


def _hosts(main):
    main.show_home("hosts")


BASICS = 6    # steps 1-6 are the basics; the rest show what JeopsokHeyou does differently

STEPS = [
    Step("welcome", "Welcome to JeopsokHeyou",
         "An SSH terminal with a file explorer next to it. No account, no tracking, free and open source. "
         "Six short steps cover the basics, then three show what makes it different."),
    Step("add_host", "Add a server",
         "Click New host to save a server. Already have sessions in PuTTY, MobaXterm, SecureCRT, Tabby, "
         "iTerm2 or ~/.ssh/config? Use Import next to it.",
         target=lambda m: m.home.hosts.new_btn, prepare=_hosts),
    Step("connect", "Connect",
         "Double-click a host card to connect. You can also type user@host here and press Enter.",
         target=lambda m: m.home.hosts.search, prepare=_hosts),
    Step("session", "Terminal and files move together",
         "Each connection opens the terminal with a file explorer for the server, shown as a folder tree. "
         "cd in the terminal and the explorer follows; open a folder in the explorer and the terminal goes there too.",
         picture="session"),
    Step("toolbar", "Tabs, splits and Home",
         "Home brings you back here. Split the terminal left/right or top/bottom. Drag a terminal by its title bar "
         "onto another one to dock it beside it, or out of the window to give it a window of its own — even the only "
         "one. Double-click a title bar to let that terminal fill the tab.",
         target=lambda m: m.main_toolbar),
    Step("settings", "Make it yours",
         "Theme, fonts, language, keyword highlighting, session logs and disk space warnings are in Settings.",
         target=lambda m: m.home.settings_btn, prepare=lambda m: m.show_home("start")),
    Step("edit", "Edit server files in your own editor",
         "Double-click a file to open it in the app you already use. Save it, and JeopsokHeyou offers to "
         "upload the change — no vi needed.",
         picture="edit"),
    Step("dragout", "Drag files to your desktop",
         "Drag files or whole folders from the explorer onto the desktop or any folder window, and they are "
         "downloaded right there. Drop files in to upload.",
         picture="dragout"),
    Step("disk", "Disk space at a glance",
         "See how much space the server has left as soon as you connect, with a warning when a disk runs low "
         "— without putting any load on the server. Run this guide again any time from Help > Getting started guide.",
         picture="disk"),
]


# ---------------------------------------------------------------- saved progress
def state(settings: dict) -> dict:
    t = settings.get("tour")
    t = dict(t) if isinstance(t, dict) else {}
    try:
        step = int(t.get("step", 0))
    except (TypeError, ValueError):
        step = 0
    return {"step": min(max(0, step), len(STEPS) - 1), "done": bool(t.get("done")),
            "dismissed": bool(t.get("dismissed"))}


def should_autostart(settings: dict) -> bool:
    s = state(settings)
    return not s["done"] and not s["dismissed"]


def mark_first_run(settings: dict) -> bool:
    """Record the first start; True when this is it."""
    if settings.get("first_run_at"):
        return False
    settings["first_run_at"] = time.time()
    return True


# ---------------------------------------------------------------- drawing for steps with nothing on screen yet
class Picture(QWidget):
    """Small drawings for steps that show something not on screen yet."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedHeight(118)

    def paintEvent(self, _e):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        frame = QPainterPath()
        frame.addRoundedRect(r, 10, 10)
        p.fillPath(frame, QColor(t.window))
        p.setPen(QPen(QColor(t.sep), 1))
        p.drawPath(frame)
        p.setPen(Qt.PenStyle.NoPen)
        getattr(self, "_" + self.kind, self._session)(p, t, r)
        p.end()

    # -- helpers
    @staticmethod
    def _font(px, bold=False, mono=False):
        f = QFont("Consolas") if mono else QFont()
        f.setPixelSize(px)
        if bold:
            f.setWeight(QFont.Weight.DemiBold)
        return f

    def _rows(self, p, t, x, y, w, n, folders=2):
        for i in range(n):
            yy = y + i * 16
            p.setBrush(QColor("#5AC8FA") if i < folders else QColor(t.faint))
            p.drawRoundedRect(QRectF(x, yy, 10, 8), 2, 2)
            p.setBrush(QColor(t.sep))
            p.drawRoundedRect(QRectF(x + 16, yy + 1, w * (0.5 if i % 2 else 0.35), 6), 3, 3)

    def _arrow(self, p, t, x1, y1, x2, y2):
        p.setPen(QPen(QColor(t.accent), 1.8, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPoint(int(x1), int(y1)), QPoint(int(x2), int(y2)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.accent))
        p.drawEllipse(QRectF(x2 - 3, y2 - 3, 6, 6))

    # -- drawings
    def _session(self, p, t, r):
        p.setBrush(QColor(t.content))
        p.drawRoundedRect(QRectF(r.x() + 10, r.y() + 8, 70, 14), 4, 4)
        p.setBrush(QColor(t.sep))
        p.drawRoundedRect(QRectF(r.x() + 86, r.y() + 8, 50, 14), 4, 4)
        body = QRectF(r.x() + 10, r.y() + 28, r.width() - 20, r.height() - 38)
        split = body.x() + body.width() * 0.38
        p.setBrush(QColor(t.content))
        p.drawRoundedRect(QRectF(body.x(), body.y(), split - body.x() - 4, body.height()), 5, 5)
        self._rows(p, t, body.x() + 8, body.y() + 8, split - body.x(), 4)
        term = QRectF(split, body.y(), body.right() - split, body.height())
        p.setBrush(QColor("#1C1C1E"))
        p.drawRoundedRect(term, 5, 5)
        p.setFont(self._font(10, mono=True))
        p.setPen(QColor("#E5E5EA"))
        p.drawText(QRectF(term.x() + 8, term.y() + 4, term.width() - 12, 16), Qt.AlignmentFlag.AlignVCenter,
                   "$ cd /var/www")
        p.setPen(QColor("#34C759"))
        p.drawText(QRectF(term.x() + 8, term.y() + 20, term.width() - 12, 16), Qt.AlignmentFlag.AlignVCenter,
                   "deploy@web:/var/www$ \u258d")
        self._arrow(p, t, term.x() + 4, term.y() + 12, split - 12, body.y() + 12)
        self._arrow(p, t, split - 12, body.y() + 28, term.x() + 4, term.y() + 28)

    def _edit(self, p, t, r):
        # editor window
        ed = QRectF(r.x() + 12, r.y() + 12, r.width() * 0.52, r.height() - 24)
        p.setBrush(QColor(t.content))
        p.drawRoundedRect(ed, 6, 6)
        p.setBrush(QColor(t.sep))
        p.drawRoundedRect(QRectF(ed.x(), ed.y(), ed.width(), 14), 6, 6)
        p.setFont(self._font(9, mono=True))
        p.setPen(QColor(t.muted))
        for i, line in enumerate(("server_name web;", "listen 443 ssl;", "root /var/www;")):
            p.drawText(QRectF(ed.x() + 8, ed.y() + 20 + i * 14, ed.width() - 12, 14), Qt.AlignmentFlag.AlignVCenter,
                       line)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.accent))
        p.drawRoundedRect(QRectF(ed.right() - 54, ed.bottom() - 22, 46, 16), 8, 8)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(self._font(9, bold=True))
        p.drawText(QRectF(ed.right() - 54, ed.bottom() - 22, 46, 16), Qt.AlignmentFlag.AlignCenter,
                   "⌘S" if paths.IS_MAC else "Ctrl+S")
        # server
        sx = r.right() - 70
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(2):
            p.setBrush(QColor(t.content))
            p.drawRoundedRect(QRectF(sx, r.y() + 28 + i * 26, 56, 22), 5, 5)
            p.setBrush(QColor("#34C759"))
            p.drawEllipse(QRectF(sx + 8, r.y() + 36 + i * 26, 6, 6))
        p.setPen(QColor(t.text))
        p.setFont(self._font(10, bold=True))
        p.drawText(QRectF(sx - 10, r.y() + 82, 76, 16), Qt.AlignmentFlag.AlignCenter, "\u2191 " + tr("Server"))
        self._arrow(p, t, ed.right() + 6, r.y() + 52, sx - 6, r.y() + 52)

    def _dragout(self, p, t, r):
        ex = QRectF(r.x() + 12, r.y() + 12, r.width() * 0.42, r.height() - 24)
        p.setBrush(QColor(t.content))
        p.drawRoundedRect(ex, 6, 6)
        self._rows(p, t, ex.x() + 8, ex.y() + 10, ex.width() - 10, 5)
        p.setBrush(QColor(t.accent))
        p.setOpacity(0.25)
        p.drawRoundedRect(QRectF(ex.x() + 4, ex.y() + 40, ex.width() - 8, 14), 3, 3)
        p.setOpacity(1.0)
        desk = QRectF(r.right() - r.width() * 0.4, r.y() + 12, r.width() * 0.4 - 12, r.height() - 24)
        g = QColor(t.accent)
        g.setAlpha(40)
        p.setBrush(g)
        p.drawRoundedRect(desk, 6, 6)
        for i, color in enumerate(("#FF9F0A", "#5AC8FA")):
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(desk.x() + 14 + i * 40, desk.y() + 18, 26, 22), 4, 4)
        p.setPen(QColor(t.muted))
        p.setFont(self._font(9))
        p.drawText(QRectF(desk.x(), desk.bottom() - 22, desk.width(), 16), Qt.AlignmentFlag.AlignCenter, tr("Desktop"))
        self._arrow(p, t, ex.right() - 10, ex.y() + 47, desk.x() + 30, desk.y() + 52)

    def _disk(self, p, t, r):
        from . import diskui
        pill = QRectF(r.x() + 16, r.y() + 16, r.width() - 32, 26)
        path = QPainterPath()
        path.addRoundedRect(pill, 13, 13)
        p.fillPath(path, QColor(255, 255, 255, 18) if t.dark else QColor(0, 0, 0, 12))
        diskui.paint_ring(p, pill.x() + 16, pill.center().y(), 6.5, 2.6, 0.79, QColor(t.accent),
                          QColor("#3A3A3C" if t.dark else "#E3E3E8"))
        p.setPen(QColor(t.text))
        bold = self._font(12, bold=True)
        p.setFont(bold)
        main_text = tr("{free} free", free="234 GB")
        p.drawText(QRectF(pill.x() + 32, pill.y(), pill.width() - 36, pill.height()), Qt.AlignmentFlag.AlignVCenter,
                   main_text)
        x = pill.x() + 32 + QFontMetrics(bold).horizontalAdvance(main_text) + 8
        p.setPen(QColor(t.muted))
        p.setFont(self._font(11))
        p.drawText(QRectF(x, pill.y(), pill.right() - x - 8, pill.height()), Qt.AlignmentFlag.AlignVCenter,
                   tr("of {total}", total="1.1 TB") + " \u00b7 21%")
        warn = QRectF(r.x() + 16, r.y() + 56, r.width() - 32, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3A3320" if t.dark else "#FFF4D6"))
        p.drawRoundedRect(warn, 6, 6)
        p.setPen(QColor("#F5D78E" if t.dark else "#6B4E00"))
        p.setFont(self._font(11, bold=True))
        p.drawText(warn.adjusted(10, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter,
                   tr("Low disk space · {mount} has {pct} free ({free})", mount="/var/log", pct="7%", free="1.4 GB"))
        p.setPen(Qt.PenStyle.NoPen)
        diskui.paint_bar(p, QRectF(r.x() + 16, r.y() + 94, r.width() - 32, 7), 0.93, QColor("#FF9F0A"),
                         QColor("#3A3A3C" if t.dark else "#E3E3E8"))


# ---------------------------------------------------------------- overlay
class TourOverlay(QWidget):
    """Dims the window, cuts a hole around the step's target and shows a card next to it."""

    PAD = 6

    def __init__(self, main, persist: bool, start: int = 0):
        super().__init__(main)
        self.main = main
        self.persist = persist           # False when replayed from Help after it was finished
        self.index = start
        self.hole: QRect | None = None
        self.setObjectName("TourOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.card = QFrame(self)
        self.card.setObjectName("TourCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.card.setFixedWidth(360)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(20, 16, 16, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.counter = QLabel()
        self.counter.setObjectName("Section")
        close = QToolButton()
        close.setAutoRaise(True)
        close.setToolTip(tr("Close (continue next time)"))
        icons.bind(close, "close")
        close.clicked.connect(self.skip)
        head.addWidget(self.counter, 1)
        head.addWidget(close)
        lay.addLayout(head)
        self.title = QLabel()
        self.title.setObjectName("TourTitle")
        self.title.setWordWrap(True)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setObjectName("Muted")
        lay.addWidget(self.title)
        lay.addWidget(self.body)
        self.picture_box = QVBoxLayout()
        lay.addLayout(self.picture_box)
        buttons = QHBoxLayout()
        self.never_btn = QPushButton(tr("Don't show again"))
        self.never_btn.setObjectName("TourLink")
        self.never_btn.setFlat(True)
        self.never_btn.clicked.connect(self.dismiss)
        self.basics_btn = QPushButton(tr("Finish with the basics"))
        self.basics_btn.setObjectName("TourLink")
        self.basics_btn.setFlat(True)
        self.basics_btn.clicked.connect(self.finish_basics)
        self.back_btn = QPushButton(tr("Back"))
        self.back_btn.clicked.connect(self.back)
        self.next_btn = QPushButton()
        self.next_btn.setObjectName("Primary")
        self.next_btn.clicked.connect(self.next)
        buttons.addWidget(self.never_btn)
        buttons.addWidget(self.basics_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)
        lay.addSpacing(4)
        lay.addLayout(buttons)
        main.installEventFilter(self)
        theme.manager.changed.connect(lambda _t: self.update())
        self.setGeometry(main.rect())
        self.show()
        self.raise_()
        self.show_step()
        self.setFocus()

    # -- steps
    def step(self) -> Step:
        return STEPS[self.index]

    def show_step(self):
        st = self.step()
        if st.prepare:
            st.prepare(self.main)
        self.counter.setText(tr("Step {n} of {total}", n=self.index + 1, total=len(STEPS)))
        self.title.setText(tr(st.title))
        self.body.setText(tr(st.body))
        while self.picture_box.count():
            w = self.picture_box.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        if st.picture:
            self.picture_box.addWidget(Picture(st.picture, self.card))
        last = self.index == len(STEPS) - 1
        self.back_btn.setVisible(self.index > 0)
        self.next_btn.setText(tr("Done") if last else (tr("Start") if self.index == 0 else tr("Next")))
        at_basics_end = self.index == BASICS - 1
        self.basics_btn.setVisible(at_basics_end)
        self.never_btn.setVisible(self.persist and not at_basics_end)
        if at_basics_end:
            self.next_btn.setText(tr("See what's different"))
        self._save(step=self.index)
        self.card.adjustSize()
        self.place()
        QTimer.singleShot(0, self.place)       # again once the new texts are laid out
        self.next_btn.setFocus()

    def next(self):
        if self.index >= len(STEPS) - 1:
            self._save(done=True, step=0)
            self.finish()
            return
        self.index += 1
        self.show_step()

    def finish_basics(self):
        self._save(done=True, step=0)
        self.finish()

    def back(self):
        if self.index > 0:
            self.index -= 1
            self.show_step()

    def skip(self):
        """Close now; it comes back at this step next time (unless finished or turned off)."""
        self.finish()

    def dismiss(self):
        self._save(dismissed=True)
        self.finish()

    def finish(self):
        self.main.removeEventFilter(self)
        if getattr(self.main, "tour", None) is self:
            self.main.tour = None
        self.hide()
        self.deleteLater()

    def _save(self, **kw):
        if not self.persist:
            return
        s = state(self.main.settings)
        s.update(kw)
        self.main.settings["tour"] = s
        try:
            config.save_settings(self.main.settings)
        except OSError:
            pass

    # -- layout
    def place(self):
        self.setGeometry(self.main.rect())
        st = self.step()
        target = None
        if st.target:
            try:
                target = st.target(self.main)
            except AttributeError:
                target = None
        if target is not None and target.isVisible():
            tl = target.mapTo(self.main, QPoint(0, 0))
            self.hole = QRect(tl, target.size()).adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)
        else:
            self.hole = None
        cw = self.card.width()
        for wdg in (self.card, self.counter, self.title, self.body):
            wdg.ensurePolished()               # style-sheet fonts must be in place before measuring
        self.card.layout().invalidate()
        self.card.layout().activate()
        ch = self.card.layout().totalHeightForWidth(cw) if self.card.layout().hasHeightForWidth()             else self.card.sizeHint().height()
        self.card.resize(cw, ch)
        W, H = self.width(), self.height()
        if self.hole is None:
            x, y = (W - cw) // 2, (H - ch) // 2
        else:
            h = self.hole
            gap = 14
            if h.bottom() + gap + ch <= H - 8:          # below
                x, y = h.center().x() - cw // 2, h.bottom() + gap
            elif h.top() - gap - ch >= 8:               # above
                x, y = h.center().x() - cw // 2, h.top() - gap - ch
            elif h.right() + gap + cw <= W - 8:         # right
                x, y = h.right() + gap, h.center().y() - ch // 2
            else:                                       # left
                x, y = h.left() - gap - cw, h.center().y() - ch // 2
        x = max(8, min(x, W - cw - 8))
        y = max(8, min(y, H - ch - 8))
        self.card.move(x, y)
        self.raise_()
        self.update()

    def eventFilter(self, obj, e):
        if obj is self.main and e.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self.place()
        return False

    def paintEvent(self, _e):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        if self.hole is not None:
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self.hole), 10, 10)
            dim = dim.subtracted(hole)
        p.fillPath(dim, QColor(0, 0, 0, 150 if t.dark else 90))
        if self.hole is not None:
            p.setPen(QPen(QColor(t.accent), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.hole), 10, 10)
        p.end()

    # the dimmed area does not pass clicks through; keys: Esc closes, Enter/→ next, ← back
    def mousePressEvent(self, e):
        e.accept()

    def keyPressEvent(self, e: QKeyEvent):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.skip()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.next()
        elif k == Qt.Key.Key_Left:
            self.back()
        else:
            super().keyPressEvent(e)


def start(main, from_help: bool = False) -> TourOverlay | None:
    """Open the guide. Automatic start resumes at the saved step; Help starts from the beginning and only
    saves progress while the guide has not been finished or turned off."""
    old = getattr(main, "tour", None)
    if old is not None:
        old.finish()
    s = state(main.settings)
    persist = not s["done"] and not s["dismissed"]
    if not from_help and not persist:
        return None
    main.tour = TourOverlay(main, persist=persist, start=0 if from_help else s["step"])
    return main.tour
