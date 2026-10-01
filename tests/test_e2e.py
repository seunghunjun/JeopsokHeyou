# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys, time, subprocess
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")   # test work folder (git-ignored)
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata")   # keep the user's real settings untouched
import shutil; shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
root = os.path.join(SP, "srvroot"); os.makedirs(root, exist_ok=True)
py = sys.executable
srv = subprocess.Popen([py, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou import explorer as _explorer  # noqa: E402
_explorer.ask_overwrite = lambda *a, **k: "overwrite"   # files left by an earlier run would otherwise ask
from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme
from jeopsokheyou.config import Session
from jeopsokheyou.explorer import job_download
apply_dark_theme(app)
w = MainWindow(); w.resize(1300, 700); w.show()
def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
        if cond(): return True
    return False
s = Session(host="127.0.0.1", port=2299, user="tester", name="test-server", group="Testing")
w.store.upsert(s); w.reload_sessions()
w.open_session(s, "pw")
tab = w.current_tab()
print("connected:", wait(lambda: tab.state == "connected"))
print("explorer listed:", wait(lambda: tab.explorer.tree.topLevelItemCount() >= 2), tab.explorer.cwd)
print("inject done:", wait(lambda: tab.panes[0]._inject_state == "done", 15))
disp = "\n".join(tab.panes[0].screen.display)
print("inject hidden:", "PROMPT_COMMAND" not in disp, "| screen:", [l.rstrip() for l in tab.panes[0].screen.display if l.strip()])
tab._cd("/home/tester/docs")
print("follow cd:", wait(lambda: tab.explorer.cwd == "/home/tester/docs"), tab.explorer.cwd)
up = os.path.join(SP, "upme.txt"); open(up, "w", encoding="utf-8").write("upload test")
tab.explorer.upload([up], tab.explorer.cwd)
print("upload:", wait(lambda: os.path.exists(os.path.join(root, "home/tester/docs/upme.txt"))))
print("refresh after upload:", wait(lambda: tab.explorer.tree.topLevelItemCount() == 1))
dl = os.path.join(SP, "dl"); os.makedirs(dl, exist_ok=True)
tab.explorer.transfer.submit("download", job_download(["/home/tester/hello.txt"], dl))
print("download:", wait(lambda: os.path.exists(os.path.join(dl, "hello.txt"))), open(os.path.join(dl,"hello.txt"),encoding="utf-8").read().strip() if os.path.exists(os.path.join(dl,"hello.txt")) else "")
tab.explorer.go_up()
print("go_up:", wait(lambda: tab.explorer.cwd == "/home/tester"), tab.explorer.tree.currentItem().text(0) if tab.explorer.tree.currentItem() else None)
tab.split_pane(Qt.Orientation.Horizontal)
print("split panes:", len(tab.panes), wait(lambda: tab.panes[1]._inject_state == "done"))
tab.split_pane(Qt.Orientation.Vertical)
print("nested split:", len(tab.panes))
wait(lambda: False, 1)
# Sample output for the screenshot
ESC = "\x1b"
demo = (f"ls --color\r\n{ESC}[1;34mdocs{ESC}[0m  hello.txt  {ESC}[32mrun.sh{ESC}[0m\r\n"
        f"日本語 出力テスト {ESC}[33mwarning{ESC}[0m {ESC}[41m error {ESC}[0m\r\n$ ")
tab.panes[0].feed(demo.encode("utf-8"))
tab.panes[0].setFocus()
wait(lambda: False, 0.5)
w.grab().save(os.path.join(SP, "shot.png"))
tab.panes[2].send_text("exit\r")
print("pane closed on exit:", wait(lambda: len(tab.panes) == 2))
tab.panes[1].send_text("exit\r"); wait(lambda: len(tab.panes) == 1)
tab.panes[0].send_text("exit\r")
print("last exit -> closed:", wait(lambda: tab.state == "closed"))
tab.connect()
print("reconnect:", wait(lambda: tab.state == "connected"))
w.close(); stop_server(srv); print("DONE")
