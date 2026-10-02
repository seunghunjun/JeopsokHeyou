# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
r"""GUI smoke test on the real window system (Cocoa on macOS, Windows on Windows) with screenshots.

Used by .github/workflows/gui-smoke.yml to check the macOS build without a Mac at hand:
it drives the real UI against the local fake SSH/SFTP server and saves a screenshot of every step
to gui-smoke/ (uploaded as a workflow artifact). Exit code 1 when a step fails.

    python tools/gui_smoke.py            # needs a desktop session (not QT_QPA_PLATFORM=offscreen)
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "gui-smoke"
WORK = ROOT / "tests" / ".work" / "gui-smoke"
shutil.rmtree(OUT, ignore_errors=True)
shutil.rmtree(WORK, ignore_errors=True)
OUT.mkdir(parents=True)
WORK.mkdir(parents=True)
os.environ["APPDATA"] = str(WORK / "appdata")           # keep away from the user's real data (Windows)
os.environ.setdefault("JEOPSOKHEYOU_LANG", "en")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

failures: list[str] = []


def step(name: str, ok: bool, extra="") -> None:
    print(("PASS " if ok else "FAIL ") + name, extra, flush=True)
    if not ok:
        failures.append(name)


def main() -> int:
    srv_root = WORK / "srv"
    (srv_root / "home" / "tester" / "logs").mkdir(parents=True)
    (srv_root / "home" / "tester" / "logs" / "app.log").write_text("ok\n", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, str(ROOT / "tests" / "fake_server.py"), "2299", str(srv_root)],
                           stdout=subprocess.PIPE)
    srv.stdout.readline()
    app = QApplication([])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    from jeopsokheyou import __version__, paths
    from jeopsokheyou.config import Session
    from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme
    print(f"platform={app.platformName()} version={__version__} mac={paths.IS_MAC}", flush=True)

    def pump(sec=0.3, cond=None):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)
            if cond and cond():
                return True
        return cond is None

    n = [0]

    def shot(widget, name):
        pump(0.5)
        n[0] += 1
        path = OUT / f"{n[0]:02d}-{name}.png"
        widget.grab().save(str(path))
        if sys.platform == "darwin":   # the whole screen as macOS shows it (best effort)
            subprocess.run(["screencapture", "-x", str(OUT / f"{n[0]:02d}-{name}-screen.png")], capture_output=True)

    apply_dark_theme(app)
    w = MainWindow()
    w.resize(1280, 800)
    w.show()
    w.raise_()
    w.activateWindow()
    step("window shows with the version in the title", w.windowTitle() == f"JeopsokHeyou {__version__}", w.windowTitle())
    shot(w, "start-page")

    s = Session(host="127.0.0.1", port=2299, user="tester", name="smoke", group="Smoke / Nested")
    s.password = "pw"
    w.store.upsert(s)
    w.reload_sessions()
    step("password saved (Keychain on macOS)", w.store.get(s.id).password == "pw")
    w.show_home("hosts")
    shot(w, "hosts")

    w.open_session(w.store.get(s.id))
    tab = w.current_tab()
    step("connects", pump(15, lambda: tab.state == "connected"), tab.state)
    pane = tab.panes[0]
    step("shell hook injected", pump(15, lambda: pane._inject_state == "done"))
    step("explorer lists the home folder", pump(10, lambda: tab.explorer.cwd == "/home/tester"), tab.explorer.cwd)
    pane.send_text("cd logs\r")
    pane._note_user_input("\r")
    step("explorer follows cd", pump(10, lambda: tab.explorer.cwd.endswith("/logs")), tab.explorer.cwd)
    shot(w, "terminal-and-explorer")

    long = "echo " + "x" * 150
    pane.send_text(long + "\r")
    pump(1)
    tab.split_pane(Qt.Orientation.Horizontal)
    pump(15, lambda: len(tab.panes) == 2 and tab.panes[1]._inject_state == "done")
    pump(1)
    step("split pane opened", len(tab.panes) == 2)
    shot(w, "split-reflowed")

    pane.open_search()
    pane._search_bar.edit.setText("logs")
    step("find in terminal", len(pane.search_hits) >= 1, len(pane.search_hits))
    shot(w, "find")
    pane.close_search()

    scheme = {"ansi": ["#073642", "#dc322f", "#859900", "#b58900", "#268bd2", "#d33682", "#2aa198", "#eee8d5",
                       "#002b36", "#cb4b16", "#586e75", "#657b83", "#839496", "#6c71c4", "#93a1a1", "#fdf6e3"],
              "fg": "#839496", "bg": "#002b36", "cursor": "#93a1a1", "selection": "#073642"}
    for p in tab.panes:
        p.apply_scheme(scheme)
    shot(w, "color-scheme")

    w.apply_appearance(mode="dark")
    w.show_home("forwarding")
    shot(w, "dark-port-forwarding")
    w.apply_appearance(mode="light")

    w.close()
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(srv.pid)], capture_output=True) if sys.platform == "win32" \
        else srv.kill()
    print(f"screenshots: {OUT}", flush=True)
    print("FAILED: " + ", ".join(failures) if failures else "ALL PASSED", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
