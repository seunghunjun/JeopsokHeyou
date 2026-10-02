# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Keyword highlighting and session logging."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "highlight-log")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
sys.path.insert(0, os.path.dirname(TESTS))
import pyte  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou.highlights import DEFAULT_RULES, compile_rules, row_colors  # noqa: E402
from jeopsokheyou.sessionlog import SessionLog, log_path  # noqa: E402
from jeopsokheyou.terminal import TermScreen  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def screen_with(text, cols=60):
    s = TermScreen(cols, 5, 100)
    pyte.ByteStream(s).feed(text.encode())
    return s


# ---------------------------------------------------------------- highlighting
rules = compile_rules(DEFAULT_RULES)
s = screen_with("[ERROR] boom, warning: disk; errors=0 SUCCESS")
cols = row_colors(s.buffer[0], s.columns, rules)
check("ERROR colored", all(x in cols for x in range(1, 6)) and cols[1].name() == "#ff5f57")
check("case-insensitive by default (warning)", 14 in cols and cols[14].name() == "#ffbd2e")
check("whole words only ('errors' is not 'error')", 28 not in cols)
check("SUCCESS green", cols.get(39) is not None and cols[39].name() == "#28c840")
strict = compile_rules([{"words": "Error", "color": "#123456", "case": True}])
check("match case when asked", row_colors(screen_with("error Error").buffer[0], 60, strict).keys() == set(range(6, 11)))
s = screen_with("".join(map(chr, (0xC624, 0xB958))) + " ERROR")
wide = row_colors(s.buffer[0], 60, rules)
check("columns stay right after wide characters", set(wide) == set(range(5, 10)), sorted(wide))
s = screen_with("java.lang.IllegalStateException: closed")
exc = row_colors(s.buffer[0], 60, rules)
check("*Exception matches class names", set(exc) == set(range(10, 31)), sorted(exc)[:3])
check("empty or bad rules are ignored", compile_rules([{"words": " , "}, {}]) == [])

# ---------------------------------------------------------------- session log
p = Path(SP) / "log1.log"
log = SessionLog(p, timestamps=False)
log.write("\x1b[1;31mred\x1b[0m text\r\n")
log.write("downloading 10%\r")
log.write("downloading 100%\r\n")
log.write("abc\bd\r\n")
log.write("split \x1b[3")          # an escape sequence cut between two chunks
log.write("2mgreen\x1b[0m\r\n")
log.write("\x1b]0;window title\x07title gone\r\n")
log.write("no newline at the end")
log.close()
lines = p.read_text(encoding="utf-8").splitlines()
body = [ln for ln in lines if not ln.startswith("#")]
check("colors removed", body[0] == "red text", body[0])
check("progress line keeps only the final state", body[1] == "downloading 100%", body[1])
check("backspace applied", body[2] == "abd", body[2])
check("escape split across chunks", body[3] == "split green", body[3])
check("window-title codes removed", body[4] == "title gone", body[4])
check("last partial line written on close", body[5] == "no newline at the end", body[5])
check("header and footer", lines[0].startswith("# JeopsokHeyou session log") and lines[-1].startswith("# ended"))
p2 = Path(SP) / "log2.log"
log = SessionLog(p2, timestamps=True)
log.write("hello\n")
log.close()
stamped = [ln for ln in p2.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")][0]
check("time stamp on every line", stamped[0] == "[" and stamped[9:] == "] hello", stamped)
lp = log_path(Path(SP), 'web:01 / "prod"', 2)
check("safe file name per session and pane", lp.parent.name == "web_01 _ _prod" and lp.name.endswith("_2.log"), lp)

# ---------------------------------------------------------------- in the app (fake server)
root = os.path.join(SP, "srv")
os.makedirs(root)
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
from _util import stop_server  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme  # noqa: E402


def wait(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


apply_dark_theme(app)
w = MainWindow()
w.show()
logdir = Path(SP) / "logs"
w.settings.update({"log_sessions": True, "log_timestamps": False, "log_dir": str(logdir)})
w.open_session(Session(host="127.0.0.1", port=2299, user="tester", name="srv one"), "pw")
tab = w.current_tab()
pane = tab.panes[0]
check("connected", wait(lambda: tab.state == "connected"))
check("highlight rules active by default", bool(pane.highlight_rules))
check("auto logging started", pane.logger is not None and pane.logger.path.parent == logdir / "srv one")
wait(lambda: pane._inject_state == "done", 15)
pane.send_text("echo ERROR\r")
wait(lambda: False, 1.0)
w.toggle_log()
check("toggle stops logging", pane.logger is None)
logs = list((logdir / "srv one").glob("*.log"))
text = logs[0].read_text(encoding="utf-8") if logs else ""
check("server output logged as plain text", "Welcome to demo server" in text and "\x1b" not in text, text[:200])
check("hidden helper commands are not logged", "PROMPT_COMMAND" not in text)
w.toggle_log()
check("toggle starts a new log", pane.logger is not None)
w.settings["highlight_enabled"] = False
pane.apply_highlights(w.settings)
check("highlighting can be turned off", pane.highlight_rules == [])
pane.grab()          # paints with logging on and highlighting off without errors
w.close()
check("closing the tab closes the log", pane.logger is None)
stop_server(srv)
print("DONE")
