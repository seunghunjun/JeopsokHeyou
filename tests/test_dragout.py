# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys, time, shutil, subprocess
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")   # test work folder (git-ignored)
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from _util import stop_server  # noqa: E402
from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])
from jeopsokheyou import dragout
from jeopsokheyou.explorer import job_download_drop, SftpWorker
from jeopsokheyou.ssh import SshConnection, trust_host_key, UnknownHostKey
from jeopsokheyou.config import Session

def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)

def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
        if cond(): return True
    return False

# 1) Create placeholders
items = [("hello.txt", False), ("docs", True)]
staging, paths, marker = dragout.make_placeholders(items)
check("placeholder file", dragout.is_placeholder(paths[0], False, marker))
check("placeholder folder", dragout.is_placeholder(paths[1], True, marker))

# 2) List Explorer windows (PowerShell Shell.Application)
t0 = time.time(); folders = dragout.explorer_folders()
check("Explorer/desktop paths listed", len(folders) >= 1, f"{folders[:3]} ({time.time()-t0:.1f}s)")

# 3) Find the drop location: the window folder itself / onto a subfolder icon
target = os.path.join(SP, "drop_target"); shutil.rmtree(target, ignore_errors=True)
os.makedirs(os.path.join(target, "sub"))
loc = dragout.DropLocator("hello.txt", False, marker)
shutil.copy(paths[0], os.path.join(target, "hello.txt"))
check("locate (window folder)", loc._search([target]) == target)
os.remove(os.path.join(target, "hello.txt"))
shutil.copy(paths[0], os.path.join(target, "sub", "hello.txt"))
check("locate (dropped onto subfolder)", loc._search([target]) == os.path.join(target, "sub"))
check("other files ignored", dragout.DropLocator("x.txt", False, marker)._search([target]) is None)
# Threaded path: still found when copied late
found = []
class L(dragout.DropLocator):
    def run(self):
        folders = [target]
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            h = self._search(folders)
            if h: self.found.emit(h); return
            time.sleep(0.2)
        self.not_found.emit()
os.makedirs(os.path.join(target, "late"))
l2 = L("docs", True, marker, timeout=3); l2.found.connect(found.append); l2.start()
time.sleep(0.6); shutil.copytree(paths[1], os.path.join(target, "late", "docs"))
check("late copy detected (folder)", wait(lambda: bool(found), 5), found)

# 4) Real download -> overwrites placeholders + removes marker
root = os.path.join(SP, "srvroot")
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
os.makedirs(os.path.join(root, "home/tester/docs"), exist_ok=True)
open(os.path.join(root, "home/tester/docs/a.txt"), "w", encoding="utf-8").write("A content")
conn = SshConnection(Session(host="127.0.0.1", port=2299, user="tester"), "pw")
try:
    conn.connect()
except UnknownHostKey as e:
    trust_host_key(e.hostname, e.key); conn.connect()
w = SftpWorker(conn); res = []
w.result.connect(lambda t, p: res.append(("ok", t))); w.error.connect(lambda t, m: res.append(("err", m)))
w.start()
dest = os.path.join(target, "late")  # where the docs placeholder was copied above
shutil.copy(paths[0], os.path.join(dest, "hello.txt"))
w.submit("download", job_download_drop(["/home/tester/hello.txt", "/home/tester/docs"], dest, items, marker))
check("download finished", wait(lambda: bool(res), 10), res)
check("file overwritten with real content", open(os.path.join(dest, "hello.txt"), encoding="utf-8").read().startswith("hello"))
check("folder content received", os.path.exists(os.path.join(dest, "docs", "a.txt")))
check("folder marker removed", not os.path.exists(os.path.join(dest, "docs", dragout.MARK_FILE)))

# 5) Placeholders cleaned up on failure
res.clear(); fail_dir = os.path.join(target, "fail"); os.makedirs(fail_dir)
bad = [("nope.txt", False)]
shutil.copy(paths[0], os.path.join(fail_dir, "nope.txt"))
w.submit("download", job_download_drop(["/home/tester/nope.txt"], fail_dir, bad, marker))
check("missing file -> error", wait(lambda: bool(res), 10) and res[0][0] == "err", res)
check("placeholder deleted on failure", not os.path.exists(os.path.join(fail_dir, "nope.txt")))

dragout.cleanup_staging(staging); check("staging folder cleaned up", not os.path.exists(staging))
os.remove(os.path.join(root, "home/tester/docs/a.txt"))  # clean up so other tests are unaffected
w.stop(); w.wait(2000); conn.close()
stop_server(srv)
print("DONE")
