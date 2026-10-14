# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""ssh run inside a local terminal: the explorer never types into the other computer's shell, and that
computer can be opened as a server tab (host from the typed command or ~/.ssh/config).
Also: one Home button (the Home tab) in the main window, a distinct "home folder" button in the explorer."""
import os
import shutil
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "local_ssh")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(os.path.join(SP, "home", ".ssh"))
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ["HOME"] = os.environ["USERPROFILE"] = os.path.join(SP, "home")    # ~/.ssh/config of this test
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))
open(os.path.join(SP, "home", ".ssh", "config"), "w", encoding="utf-8").write(
    "Host web\n    HostName 192.0.2.30\n    User deploy\n    Port 2201\n")

from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou import localshell  # noqa: E402
from jeopsokheyou.localshell import parse_ssh_command, ssh_session  # noqa: E402
import jeopsokheyou.dialogs as dialogs_mod  # noqa: E402
asked, answer = [], [None]          # the password box: what it was asked, what the user gives (None = Cancel)
dialogs_mod.ask_password_saving = lambda parent, label, s, store=None: (asked.append(label), answer[0])[1]


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def wait(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


# ---- reading the typed ssh command
check("ssh user@host", parse_ssh_command("$ ssh root@192.0.2.10") == {"user": "root", "host": "192.0.2.10",
                                                                     "port": 0, "identity": ""})
check("options with values", parse_ssh_command("ssh -p 2222 -i ~/.ssh/k -o X=y me@h.example ls")
      == {"user": "me", "host": "h.example", "port": 2222, "identity": "~/.ssh/k"})
check("-l user and host:port", parse_ssh_command("C:\\>ssh -l bob host:2200")["user"] == "bob"
      and parse_ssh_command("C:\\>ssh -l bob host:2200")["port"] == 2200)
check("not ssh", parse_ssh_command("ls ssh") is None and parse_ssh_command("ssh") is None
      and parse_ssh_command("sshd -t") is None)

# ---- the host for a server tab
s = ssh_session({"user": "", "host": "web", "port": 0, "identity": ""})
check("an alias from ~/.ssh/config", (s.host, s.user, s.port) == ("192.0.2.30", "deploy", 2201), (s.host, s.user, s.port))
s = ssh_session({"user": "root", "host": "192.0.2.10", "port": 0, "identity": "~/.ssh/id_x"})
check("a plain host; -i means a key", s.host == "192.0.2.10" and s.user == "root" and s.port == 22
      and s.auth == "key" and s.key_path.endswith("id_x"))

# ---- a local terminal whose shell went on to another computer
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1300, 700)
w.show()
w.open_local(localshell.default_profile({}))
tab = w.current_tab()
pane, ex = tab.panes[0], tab.explorer
check("local shell ready", wait(lambda: pane.cwd != "" and ex.cwd == pane.cwd, 20), pane.cwd)
here = pane.cwd

# the user types an ssh command and presses Enter (not run here: only the screen line is read)
pane.at_prompt = True
pane.feed(b"\r\n$ ssh root@192.0.2.10")
pane._note_user_input("\r")
check("the typed ssh target is remembered", pane.ssh_target == {"user": "root", "host": "192.0.2.10", "port": 0,
                                                                "identity": ""}, pane.ssh_target)
check("from the moment ssh runs: banner shown, no cd typed (even if that server never reports)",
      tab.remote_banner.isVisible() and pane.sync_cd(here) == "remote")
# the remote shell reports its folder with its own host name (as RHEL's vte.sh does)
pane._on_osc7("file://order-req/root")
check("a report from another computer is not taken as this computer's folder",
      pane.remote_host == "order-req" and pane.cwd == here and ex.cwd == here, (pane.remote_host, pane.cwd))
wait(lambda: False, 0.3)
check("the banner is one slim line, the terminal keeps the room", tab.remote_banner.height() < 80
      and pane.height() > 300, (tab.remote_banner.height(), pane.height()))
check("... and the banner says where the terminal is", tab.remote_banner.isVisible()
      and "root@192.0.2.10" in tab.remote_label.text(), tab.remote_label.text())
check("nothing is typed into the other computer's shell", pane.sync_cd(here + "/x") == "remote"
      and pane.cd_command(here) is None)
# back on this computer
pane._on_osc7(pane.reported or "C:\\")
check("back here: banner gone, sync again", pane.remote_host == "" and not tab.remote_banner.isVisible())

# ---- the explorer follows the terminal onto a server (fake server: its own SFTP login)
import subprocess  # noqa: E402
sys.path.insert(0, TESTS)
from _util import stop_server  # noqa: E402
srv_root = os.path.join(SP, "srv")
os.makedirs(os.path.join(srv_root, "home", "tester", "app"))
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", srv_root], stdout=subprocess.PIPE)
srv.stdout.readline()
asked.clear()
answer[0] = "pw"
try:
    pane.at_prompt = True
    pane.feed(b"\r\n$ ssh -p 2299 tester@127.0.0.1")
    pane._note_user_input("\r")
    check("a new host: no password box while the terminal's own login runs", not asked and tab._remote is not None
          and tab._remote["waiting"])
    pane._on_osc7("file://fakehost/home/tester")        # the server's prompt: its login is done
    check("... then it asks once", len(asked) == 1, asked)
    check("the explorer shows the server's files", wait(lambda: ex.conn is not None and not ex.is_local
                                                        and ex.cwd == "/home/tester" and ex.item_count() >= 1, 15),
          (ex.cwd, ex.is_local))
    check("... the path bar says which server", "tester@127.0.0.1" in ex.path_edit.root_label, ex.path_edit.root_label)
    check("the host that worked is saved", any(x.host == "127.0.0.1" and x.port == 2299 and x.user == "tester"
                                               for x in w.store.sessions))
    pane._on_osc7("file://fakehost/home/tester/app")
    check("cd on the server: the explorer follows", wait(lambda: ex.cwd == "/home/tester/app", 10),
          ex.cwd)
    check("the terminal (on the server) is not typed into", pane.sync_cd("/home/tester") == "remote")
    pane._on_osc7(pane.reported or "C:\\")                # exit: this computer's prompt again
    check("leaving the server: the explorer shows this computer again", wait(lambda: ex.is_local and ex.cwd == here, 10)
          and tab._remote is None, (ex.cwd, ex.is_local))
    # the next time: saved, so no question
    asked.clear()
    pane.at_prompt = True
    pane.feed(b"\r\n$ ssh -p 2299 tester@127.0.0.1")
    pane._note_user_input("\r")
    check("a saved host opens by itself", wait(lambda: ex.conn is not None and not ex.is_local
                                                and ex.cwd == "/home/tester", 15) and not asked, (ex.cwd, asked))
    pane._on_osc7(pane.reported or "C:\\")
    wait(lambda: ex.is_local, 10)
finally:
    stop_server(srv)

# ---- Home buttons
tb_buttons = [b.toolTip() for b in w.main_toolbar.findChildren(QToolButton)]
check("main toolbar: no Home button (the Home tab is there)", not any(t.startswith("Home") for t in tb_buttons),
      tb_buttons)
win_tb = w.window_toolbar()
check("a separate window's toolbar keeps its Home button",
      any(b.toolTip().startswith("Home") for b in win_tb.findChildren(QToolButton)))
check("explorer: the home-folder button says so", any(b.toolTip() == "Home folder (~)"
                                                      for b in ex.findChildren(QToolButton)))
w.settings["confirm_quit"] = False
w.close()
print("DONE")
