# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Generate README screenshots and the demo animation (.github/media/).

Usage: .venv\\Scripts\\python -m pip install pillow   (dev only, not needed to run the app)
       .venv\\Scripts\\python tools\\make_readme_media.py

To avoid capturing real server details, only tests/fake_server.py (127.0.0.1) and
tests/fixtures/tabby-config.yaml (documentation-reserved addresses) are used.
The UI language is forced to English for the screenshots.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".github" / "media"
WORK = ROOT / "tests" / ".work" / "media"
os.environ["APPDATA"] = str(WORK / "appdata")            # keep separate from user settings
os.environ["JEOPSOKHEYOU_LANG"] = "en"                   # screenshots are in English
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
shutil.rmtree(WORK, ignore_errors=True)
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

SIZE = (1440, 860)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    srv_root = WORK / "srv"
    home = srv_root / "home" / "tester"
    for d in ("conf", "logs/2026", "webapps/ROOT", "backup"):
        (home / d).mkdir(parents=True, exist_ok=True)
    for name, size in (("server.xml", 7421), ("web.xml", 1893), ("deploy.sh", 612), ("app.jar", 48213),
                       ("notes.txt", 311), ("logo.png", 9120), ("application.yml", 954)):
        (home / name).write_bytes(b"x" * size)
    for name in ("catalina.out", "access.log", "error.log"):
        (home / "logs" / name).write_bytes(b"x" * 20480)

    srv = subprocess.Popen([sys.executable, str(ROOT / "tests" / "fake_server.py"), "2299", str(srv_root)],
                           stdout=subprocess.PIPE)
    srv.stdout.readline()
    app = QApplication([])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from jeopsokheyou import config, diskusage, i18n
    # Disk space: the fake server has no statvfs, so show made-up numbers (nothing real is captured)
    gb = 1 << 30
    diskusage.read_mounts = lambda sftp: ("/dev/sda1 / ext4 rw 0 0\n/dev/sdb1 /data xfs rw 0 0\n"
                                          "/dev/sdc1 /var/log ext4 rw 0 0\n192.0.2.50:/vol1 /backup nfs4 rw 0 0\n")
    fake_disks = {"/": (50 * gb, 21 * gb, 29 * gb), "/data": (1024 * gb, 820 * gb, 204 * gb),
                  "/var/log": (20 * gb, 17 * gb, 3 * gb)}
    diskusage.statvfs = lambda sftp, path: fake_disks.get(path)
    from jeopsokheyou.config import Session
    from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme
    apply_dark_theme(app)

    def pump(sec: float = 0.3, cond=None):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)
            if cond and cond():
                return True
        return cond is None

    frames: list[Image.Image] = []

    def shot(widget, name: str | None = None, frame: bool = True):
        pump(0.4)
        path = WORK / "tmp.png"
        widget.grab().save(str(path))
        img = Image.open(path).convert("RGB")
        if name:
            img.save(OUT / name, optimize=True)
        if frame:
            frames.append(img.copy())
        return img

    i18n.set_language("en")
    w = MainWindow()
    w.resize(*SIZE)
    w.show()
    w.store.sessions += config.import_tabby_sessions(ROOT / "tests" / "fixtures" / "tabby-config.yaml")
    demo = Session(host="127.0.0.1", port=2299, user="tester", name="web-01", group="Development")
    w.store.sessions.insert(0, demo)
    w.store.save()
    from jeopsokheyou.forwarding import Forward
    from jeopsokheyou.tunnels import Tunnel
    prod = next((s for s in w.store.sessions if s.group == "Production"), demo)
    w.tunnels.upsert(Tunnel(name="Production database", session_id=prod.id,
                            forward=Forward("L", "127.0.0.1", 15432, "db.internal", 5432).to_dict()))
    w.tunnels.upsert(Tunnel(name="SOCKS proxy", session_id=demo.id, forward=Forward("D", "127.0.0.1", 1080).to_dict()))
    w.tunnels.upsert(Tunnel(name="Share local web app", session_id=demo.id,
                            forward=Forward("R", "localhost", 8080, "127.0.0.1", 3000).to_dict()))
    # show a subgroup in the tree (Production › Databases)
    for s in w.store.sessions:
        if s.group == "Production" and "db" in s.name.lower():
            s.group = "Production / Databases"
    w.store.save()
    w.reload_sessions()
    # last disk values on a few host cards
    import json
    cache = {}
    for s, pct in zip([s for s in w.store.sessions if s is not demo][:4], (42, 7, 63, 18)):
        cache[s.id] = {"time": time.time() - 3600, "mount": "/data", "free_pct": pct, "avail": pct * gb,
                       "total_avail": pct * gb, "total": 100 * gb, "total_free_pct": pct}
    diskusage.cache_file().write_text(json.dumps(cache), encoding="utf-8")
    w.apply_appearance(mode="light", ui_font="default")
    w.home.show_page("hosts")
    shot(w, "home.png")
    # getting-started guide (step 2: the New host button highlighted)
    t = w.start_tour(from_help=True)
    t.next()
    shot(w, "guide.png", frame=False)
    t.skip()
    w.home.show_page("hosts")
    w.home.show_page("forwarding")
    shot(w, "port-forwarding.png", frame=False)
    w.home.show_page("hosts")

    w.open_session(demo, "pw")
    tab = w.current_tab()
    pane = tab.panes[0]
    pump(15, lambda: tab.state == "connected" and pane._inject_state == "done"
         and tab.explorer.item_count() > 3)
    pane.feed(b"ls --color\r\n\x1b[1;34mbackup\x1b[0m  \x1b[1;34mconf\x1b[0m  \x1b[1;34mlogs\x1b[0m  "
              b"\x1b[1;34mwebapps\x1b[0m  app.jar  application.yml  \x1b[32mdeploy.sh\x1b[0m  server.xml\r\n"
              b"tester:/home/tester$ ")
    pump(5, lambda: tab.explorer.disk_pill.isVisible())
    shot(w, "main-light.png")
    # disk space card over the window (the card is a popup window, so paste it in)
    tab.explorer.show_disk_card()
    pump(0.5)
    base = shot(w, None, frame=False)
    card = tab.explorer._disk_card
    card.grab().save(str(WORK / "card.png"))
    pos = card.mapToGlobal(card.rect().topLeft()) - w.mapToGlobal(w.rect().topLeft())
    overlay = Image.open(WORK / "card.png").convert("RGBA")
    base.paste(overlay, (max(0, pos.x()), max(0, pos.y())), overlay)
    base.save(OUT / "disk.png", optimize=True)
    card.hide()

    # cd in the terminal → the explorer follows
    pane.send_text("cd logs\r")
    pane._note_user_input("\r")
    pump(8, lambda: tab.explorer.cwd.endswith("/logs"))
    shot(w, "sync.png")

    tab.split_pane(Qt.Orientation.Horizontal)
    tab.split_pane(Qt.Orientation.Vertical)
    pump(15, lambda: all(p._inject_state == "done" for p in tab.panes))
    for p in tab.panes[1:]:
        p.feed(b"uptime\r\n 12:04:11 up 41 days,  3:12,  2 users,  load average: 0.08, 0.05, 0.01\r\n"
               b"tester:/home/tester$ ")
    shot(w, "split-panes.png")

    w.apply_appearance(mode="dark")
    pump(8, lambda: tab.explorer.item_count() > 0)
    shot(w, "main-dark.png")

    # Home tab in dark mode
    w.show_home("hosts")
    shot(w, "home-dark.png", frame=False)
    w.apply_appearance(mode="light")

    # demo animation (webp)
    demo_frames = [f.resize((1100, int(1100 * f.height / f.width)), Image.LANCZOS) for f in frames]
    demo_frames[0].save(OUT / "demo.webp", save_all=True, append_images=demo_frames[1:],
                        duration=[1800, 1800, 2200, 2200, 2200], loop=0, quality=82, method=6)
    w.close()
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(srv.pid)], capture_output=True) if sys.platform == "win32" else srv.kill()
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:22} {f.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
