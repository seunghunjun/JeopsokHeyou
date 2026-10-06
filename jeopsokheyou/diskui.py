# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Disk space widgets: the capsule in the explorer status bar and the per-disk card it opens."""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from . import icons, theme
from .diskusage import Disk, Summary, level
from .i18n import tr

DEFAULT_WARN = 10
DEFAULT_CRIT = 5


def thresholds(settings: dict) -> tuple[float, float]:
    """(warn, crit) free-space percentages from the settings, kept sane (0 <= crit <= warn <= 50)."""
    try:
        warn = float(settings.get("disk_warn_pct", DEFAULT_WARN))
        crit = float(settings.get("disk_crit_pct", DEFAULT_CRIT))
    except (TypeError, ValueError):
        warn, crit = DEFAULT_WARN, DEFAULT_CRIT
    warn = min(50.0, max(0.0, warn))
    return warn, min(warn, max(0.0, crit))


def size_text(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if v < 1024 or unit == "PB":
            if unit == "B":
                return f"{v:.0f} B"
            return f"{v:.0f} {unit}" if v >= 100 else f"{v:.1f} {unit}".replace(".0 ", " ")
        v /= 1024
    return str(n)


def pct_text(p: float) -> str:
    return f"{p:.0f}%" if p >= 10 or p == 0 else f"{p:.1f}%".replace(".0%", "%")


def level_color(lv: str, t=None, for_text: bool = False) -> QColor:
    t = t or theme.current()
    if lv == "crit":
        return QColor("#FF453A" if t.dark or not for_text else "#D70015")
    if lv == "warn":
        return QColor("#FF9F0A" if t.dark or not for_text else "#B25000")
    return QColor(t.accent)


def _track(t) -> QColor:
    return QColor("#3A3A3C" if t.dark else "#E3E3E8")


def paint_ring(p: QPainter, center_x: float, center_y: float, radius: float, width: float,
               used_ratio: float, color: QColor, track: QColor) -> None:
    r = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(track, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawEllipse(r)
    used_ratio = min(1.0, max(0.0, used_ratio))
    if used_ratio > 0:
        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, -max(1, int(360 * 16 * used_ratio)))


def paint_bar(p: QPainter, r: QRectF, used_ratio: float, color: QColor, track: QColor) -> None:
    rad = r.height() / 2
    path = QPainterPath()
    path.addRoundedRect(r, rad, rad)
    p.fillPath(path, track)
    used_ratio = min(1.0, max(0.0, used_ratio))
    if used_ratio <= 0:
        return
    w = max(r.height(), r.width() * used_ratio)
    fill = QPainterPath()
    fill.addRoundedRect(QRectF(r.x(), r.y(), w, r.height()), rad, rad)
    g = QLinearGradient(r.topLeft(), r.topRight())
    g.setColorAt(0, color.lighter(130))
    g.setColorAt(1, color)
    p.fillPath(fill, g)


def resized(font: QFont, factor: float) -> QFont:
    """Copy of the font scaled by factor; works whether the font was set in points or pixels."""
    f = QFont(font)
    if font.pointSizeF() > 0:
        f.setPointSizeF(max(6.0, font.pointSizeF() * factor))
    elif font.pixelSize() > 0:
        f.setPixelSize(max(8, round(font.pixelSize() * factor)))
    return f


def _used_ratio(used: int, avail: int) -> float:
    room = used + avail
    return used / room if room else 0.0


def ago_text(when: float, now: float | None = None) -> str:
    sec = max(0, (now if now is not None else time.time()) - when)
    if sec < 60:
        return tr("just now")
    if sec < 3600:
        return tr("{n} min ago", n=int(sec // 60))
    if sec < 86400:
        return tr("{n} h ago", n=int(sec // 3600))
    return tr("{n} days ago", n=int(sec // 86400))


class DiskBadge(QWidget):
    """Small ring + free % on the name line of a host card (the last value seen on this PC)."""

    def __init__(self, entry: dict, warn: float, crit: float, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.free_pct = float(entry.get("free_pct", 100.0))
        self.lv = level(self.free_pct, warn, crit)
        self.text = f"{self.free_pct:.0f}%"
        w = 17 + QFontMetrics(self._font()).horizontalAdvance(self.text) + 2
        self.setFixedSize(w, 16)
        theme.manager.changed.connect(lambda _t: self.update())
        self.setToolTip(badge_tooltip(entry))

    def _font(self) -> QFont:
        f = resized(self.font(), 0.85)
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def paintEvent(self, _e):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_ring(p, 7, 8, 5.5, 2.2, 1 - self.free_pct / 100.0, level_color(self.lv, t), _track(t))
        p.setFont(self._font())
        p.setPen(level_color(self.lv, t, for_text=True) if self.lv != "ok" else QColor(t.muted))
        p.drawText(QRectF(17, 0, self.width() - 17, 16), Qt.AlignmentFlag.AlignVCenter, self.text)
        p.end()


def badge_tooltip(entry: dict, now: float | None = None) -> str:
    lines = [tr("Disk space, checked {ago}", ago=ago_text(float(entry.get("time", 0)), now))]
    lines.append(tr("Lowest: {mount} has {pct} free", mount=entry.get("mount", "/"),
                    pct=pct_text(float(entry.get("free_pct", 0)))) + f" ({size_text(int(entry.get('avail', 0)))})")
    lines.append(tr("{free} free of {total}", free=size_text(int(entry.get("total_avail", 0))),
                    total=size_text(int(entry.get("total", 0)))))
    return "\n".join(lines)


# ---------------------------------------------------------------- status bar capsule
class DiskPill(QWidget):
    """Rounded capsule: ring gauge + "204 GB free" + "of 1 TB · 20%". Shrinks to ring + % when narrow."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.summary: Summary | None = None
        self.warn, self.crit = DEFAULT_WARN, DEFAULT_CRIT
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(22)
        self.hide()
        theme.manager.changed.connect(lambda _t: self.update())

    # -- data
    def set_summary(self, summary: Summary | None, warn: float, crit: float) -> None:
        self.summary, self.warn, self.crit = summary, warn, crit
        if summary is None:
            self.setToolTip("")
        else:
            worst = summary.worst()
            tip = tr("Server disk space: {used} used of {total}, {free} free ({pct})",
                     used=size_text(summary.used), total=size_text(summary.total),
                     free=size_text(summary.avail), pct=pct_text(summary.free_pct))
            if worst is not None and len(summary.measured) > 1:
                tip += "\n" + tr("Lowest: {mount} has {pct} free", mount=worst.mount, pct=pct_text(worst.free_pct))
            self.setToolTip(tip + "\n" + tr("Click to see every disk"))
        self.updateGeometry()
        self.update()

    def level(self) -> str:
        """Overall level: the worst disk decides, so one full disk is never hidden by the total."""
        if self.summary is None:
            return "ok"
        worst = self.summary.worst()
        return level(worst.free_pct if worst else self.summary.free_pct, self.warn, self.crit)

    def texts(self) -> tuple[str, str]:
        s = self.summary
        if s is None:
            return "", ""
        return (tr("{free} free", free=size_text(s.avail)),
                tr("of {total}", total=size_text(s.total)) + "  ·  " + pct_text(s.free_pct))

    # -- geometry
    def _fonts(self) -> tuple[QFont, QFont]:
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        return bold, QFont(self.font())

    def _full_width(self) -> int:
        main, rest = self.texts()
        bold, normal = self._fonts()
        return int(28 + QFontMetrics(bold).horizontalAdvance(main) + 8
                   + QFontMetrics(normal).horizontalAdvance(rest) + 12)

    def _short_width(self) -> int:
        bold, _n = self._fonts()
        pct = pct_text(self.summary.free_pct) if self.summary else "100%"
        return int(28 + QFontMetrics(bold).horizontalAdvance(pct) + 12)

    def sizeHint(self) -> QSize:
        return QSize(self._full_width(), 22)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._short_width(), 22)

    # -- events
    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        if self.summary is None:
            return
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        if t.dark:
            bg = QColor(255, 255, 255, 30 if self._hover else 16)
        else:
            bg = QColor(0, 0, 0, 22 if self._hover else 11)
        p.fillPath(path, bg)
        lv = self.level()
        s = self.summary
        cy = r.center().y()
        paint_ring(p, r.x() + 14, cy, 5.5, 2.4, _used_ratio(s.used, s.avail), level_color(lv, t), _track(t))
        bold, normal = self._fonts()
        x = r.x() + 28
        text_color = level_color(lv, t, for_text=True) if lv != "ok" else QColor(t.text)
        if self.width() >= self._full_width():
            main, rest = self.texts()
            p.setFont(bold)
            p.setPen(text_color)
            p.drawText(QRectF(x, r.y(), r.width(), r.height()), Qt.AlignmentFlag.AlignVCenter, main)
            x += QFontMetrics(bold).horizontalAdvance(main) + 8
            p.setFont(normal)
            p.setPen(QColor(t.muted))
            p.drawText(QRectF(x, r.y(), r.right() - x, r.height()), Qt.AlignmentFlag.AlignVCenter, rest)
        else:
            p.setFont(bold)
            p.setPen(text_color)
            p.drawText(QRectF(x, r.y(), r.right() - x, r.height()), Qt.AlignmentFlag.AlignVCenter,
                       pct_text(s.free_pct))
        p.end()


# ---------------------------------------------------------------- per-disk card
class DiskRow(QWidget):
    ROW_H = 46

    def __init__(self, disk: Disk, warn: float, crit: float, parent=None):
        super().__init__(parent)
        self.disk, self.warn, self.crit = disk, warn, crit
        self.setFixedHeight(self.ROW_H)
        if disk.network:
            self.setToolTip(tr("Network disks are not checked, so a slow share can never hold up the server."))

    def paintEvent(self, _e):
        t = theme.current()
        d = self.disk
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        small = resized(self.font(), 0.86)
        name_w = min(150, int(w * 0.32))
        fm = QFontMetrics(bold)
        p.setFont(bold)
        p.setPen(QColor(t.text))
        p.drawText(QRectF(0, 4, name_w - 8, 20), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(d.mount, Qt.TextElideMode.ElideMiddle, name_w - 8))
        p.setFont(small)
        p.setPen(QColor(t.faint))
        sub = " · ".join(x for x in (d.fstype, d.device) if x)
        p.drawText(QRectF(0, 24, name_w - 8, 16), Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(small).elidedText(sub, Qt.TextElideMode.ElideMiddle, name_w - 8))
        pct_w = 64
        bx, bw = name_w, max(40, w - name_w - pct_w - 8)
        if d.network:
            p.setFont(self.font())
            p.setPen(QColor(t.muted))
            p.drawText(QRectF(bx, 4, w - bx, 36), Qt.AlignmentFlag.AlignVCenter, tr("Network disk — not checked"))
            p.end()
            return
        lv = level(d.free_pct, self.warn, self.crit)
        col = level_color(lv, t)
        paint_bar(p, QRectF(bx, 10, bw, 7), _used_ratio(d.used, d.avail), col, _track(t))
        p.setFont(small)
        p.setPen(QColor(t.muted))
        p.drawText(QRectF(bx, 22, bw, 18), Qt.AlignmentFlag.AlignVCenter,
                   tr("{free} free of {total}", free=size_text(d.avail), total=size_text(d.total)))
        big = resized(bold, 1.3)
        p.setFont(big)
        p.setPen(level_color(lv, t, for_text=True) if lv != "ok" else QColor(t.text))
        p.drawText(QRectF(w - pct_w, 0, pct_w, 26), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                   pct_text(d.free_pct))
        p.setFont(small)
        p.setPen(QColor(t.faint))
        p.drawText(QRectF(w - pct_w, 26, pct_w, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                   tr("free"))
        p.end()


class DiskCard(QFrame):
    """Popup card listing every disk. Built from the last result; Refresh asks the server once more."""
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("DiskCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("DiskCardTitle")
        self.updated = QLabel()
        self.updated.setObjectName("Muted")
        self.refresh_btn = QToolButton()
        self.refresh_btn.setToolTip(tr("Check again"))
        self.refresh_btn.setAutoRaise(True)
        icons.bind(self.refresh_btn, "refresh")
        self.refresh_btn.clicked.connect(self._refresh)
        head.addWidget(self.title, 1)
        head.addWidget(self.updated)
        head.addWidget(self.refresh_btn)
        lay.addLayout(head)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(4)
        lay.addLayout(self.rows)
        self.note = QLabel(tr("Read from numbers the server already keeps — nothing is scanned."))
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

    def fill(self, name: str, summary: Summary, warn: float, crit: float, when: float) -> None:
        self.title.setText(tr("Storage — {name}", name=name) if name else tr("Storage"))
        self.updated.setText(tr("Checked at {time}", time=time.strftime("%H:%M", time.localtime(when))))
        self.refresh_btn.setEnabled(True)
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for d in summary.disks:
            self.rows.addWidget(DiskRow(d, warn, crit, self))
        self.adjustSize()

    def _refresh(self):
        self.refresh_btn.setEnabled(False)
        self.updated.setText(tr("Checking…"))
        self.refresh_requested.emit()

    def show_at(self, anchor: QWidget) -> None:
        """Open above the anchor, right edges aligned, kept on screen."""
        self.adjustSize()
        g = anchor.mapToGlobal(QPoint(anchor.width(), 0))
        x, y = g.x() - self.width(), g.y() - self.height() - 6
        scr = QGuiApplication.screenAt(g) or QGuiApplication.primaryScreen()
        if scr is not None:
            a = scr.availableGeometry()
            x = max(a.left() + 4, min(x, a.right() - self.width() - 4))
            if y < a.top() + 4:
                y = anchor.mapToGlobal(QPoint(0, anchor.height())).y() + 6
        self.move(x, y)
        self.show()

    def paintEvent(self, _e):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, QColor(t.menu if t.dark else t.content))
        p.setPen(QPen(QColor(t.sep), 1))
        p.drawPath(path)
        p.end()
