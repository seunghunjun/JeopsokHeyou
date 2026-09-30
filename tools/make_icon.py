# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""assets/<source> → assets/app.png (transparent background, square) + assets/app.ico (multi-size 16-256).

Usage: .venv\\Scripts\\python tools\\make_icon.py [source file name, default icon2.jpg]
- Only white background connected to the edges becomes transparent (white inside the character is kept, blocked by the outline)
- Trims the margins, makes it square, then packs per-size PNGs into an ICO container
"""
from __future__ import annotations

import struct
import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / (sys.argv[1] if len(sys.argv) > 1 else "icon2.jpg")
OUT_PNG = ROOT / "assets" / "app.png"
OUT_ICO = ROOT / "assets" / "app.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)
WHITE_TOL = 40  # values within this distance of 255 count as background white


def remove_background(img: QImage) -> QImage:
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()

    def is_bg(x, y):
        c = img.pixelColor(x, y)
        return min(c.red(), c.green(), c.blue()) >= 255 - WHITE_TOL

    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.append((x, 0))
        q.append((x, h - 1))
    for y in range(h):
        q.append((0, y))
        q.append((w - 1, y))
    clear = QColor(0, 0, 0, 0)
    bg = bytearray(w * h)
    while q:
        x, y = q.popleft()
        i = y * w + x
        if seen[i]:
            continue
        seen[i] = 1
        if not is_bg(x, y):
            continue
        bg[i] = 1
        img.setPixelColor(x, y, clear)
        if x > 0:
            q.append((x - 1, y))
        if x < w - 1:
            q.append((x + 1, y))
        if y > 0:
            q.append((x, y - 1))
        if y < h - 1:
            q.append((x, y + 1))
    defringe(img, bg)
    return img


def defringe(img: QImage, bg: bytearray, rings: int = 2) -> None:
    """Turn gray edges touching the background (anti-aliasing of black outline + white background)
    into 'semi-transparent black' so no white fringe shows on dark backgrounds."""
    w, h = img.width(), img.height()
    edge = bg
    for _ in range(rings):
        nxt = bytearray(w * h)
        for y in range(h):
            row = y * w
            for x in range(w):
                i = row + x
                if bg[i]:
                    continue
                if not ((x > 0 and edge[i - 1]) or (x < w - 1 and edge[i + 1])
                        or (y > 0 and edge[i - w]) or (y < h - 1 and edge[i + w])):
                    continue
                c = img.pixelColor(x, y)
                r, g, b = c.red(), c.green(), c.blue()
                if max(r, g, b) - min(r, g, b) > 40 or c.alpha() < 255:
                    continue  # leave colored pixels (artwork, not outline) untouched
                lum = (r + g + b) // 3
                img.setPixelColor(x, y, QColor(0, 0, 0, 255 - lum))
                nxt[i] = 1
        for i in range(w * h):
            if nxt[i]:
                bg[i] = 1
        edge = nxt


def crop_square(img: QImage, margin_ratio: float = 0.04) -> QImage:
    w, h = img.width(), img.height()
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if img.pixelColor(x, y).alpha() > 16:
                xs.append(x)
                ys.append(y)
    if not xs:
        return img
    box = QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
    side = int(max(box.width(), box.height()) * (1 + margin_ratio * 2))
    out = QImage(side, side, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawImage((side - box.width()) // 2, (side - box.height()) // 2, img, box.x(), box.y(), box.width(), box.height())
    p.end()
    return out


def png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(img: QImage, path: Path) -> None:
    entries = []
    for s in SIZES:
        scaled = img.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        entries.append((s, png_bytes(scaled)))
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    dir_bytes, data = b"", b""
    for s, blob in entries:
        dim = 0 if s >= 256 else s
        dir_bytes += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    path.write_bytes(header + dir_bytes + data)


def main() -> int:
    if not SRC.exists():
        print(f"Source not found: {SRC}")
        return 1
    QGuiApplication(sys.argv)
    img = QImage(str(SRC))
    if img.isNull():
        print("Could not read the image")
        return 1
    if img.width() > 1024:
        img = img.scaled(1024, 1024, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    img = crop_square(remove_background(img))
    img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
               Qt.TransformationMode.SmoothTransformation).save(str(OUT_PNG), "PNG")
    write_ico(img, OUT_ICO)
    print(f"Created: {OUT_PNG}\nCreated: {OUT_ICO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
