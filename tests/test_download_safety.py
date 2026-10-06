# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Folder downloads never open special files (a FIFO blocks the server's SFTP process for good) and
never loop through folder links; folder links are followed, and past the size/file limit the user is
asked (all / skip linked folders / cancel) while counting stops early; the app log is written."""
import os
import posixpath
import shutil
import stat
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "dlsafety")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from paramiko import SFTPAttributes  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

app = QCoreApplication([])
from jeopsokheyou import applog, explorer  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


# remote tree: path -> (kind, payload)
TREE = {
    "/srv": ("dir", None),
    "/srv/app": ("dir", None),
    "/srv/app/a.txt": ("file", b"hello"),
    "/srv/app/run.fifo": ("fifo", None),         # named pipe: opening it would block forever
    "/srv/app/agent.sock": ("sock", None),
    "/srv/app/sub": ("dir", None),
    "/srv/app/sub/b.log": ("file", b"x" * 300),
    "/srv/app/sub/empty": ("dir", None),
    "/srv/app/sub/up": ("link", "/srv/app"),      # loop: a folder link back to its parent
    "/srv/app/cfg.lnk": ("link", "/srv/app/a.txt"),   # link to a regular file: downloaded
    "/srv/app/broken": ("link", "/nowhere"),
    "/srv/app/dev": ("chr", None),
    "/srv/app/shared": ("link", "/data/shared"),  # link to a big folder elsewhere
    "/srv/app/procfs": ("link", "/proc"),
    "/srv/applink": ("link", "/srv/app"),
    "/data": ("dir", None),
    "/data/shared": ("dir", None),
    "/proc": ("dir", None),
    "/proc/kmsg": ("file", b""),                   # regular-looking, but reading it blocks
}
for i in range(40):
    TREE[f"/data/shared/s{i:02d}.bin"] = ("file", b"y" * 100)
MODES = {"dir": stat.S_IFDIR | 0o755, "file": stat.S_IFREG | 0o644, "fifo": stat.S_IFIFO | 0o644,
         "sock": stat.S_IFSOCK | 0o755, "chr": stat.S_IFCHR | 0o600, "link": stat.S_IFLNK | 0o777}


class FakeSftp:
    def __init__(self, tree, follow_in_readdir=False):
        self.tree = tree
        self.follow_in_readdir = follow_in_readdir    # some servers report the link target in readdir
        self.opened: list[str] = []
        self.requests = 0

    def _resolve(self, p, depth=0):
        parent = posixpath.dirname(p)
        if parent not in ("/", p) and parent not in self.tree or \
                (parent in self.tree and self.tree[parent][0] == "link"):
            p = posixpath.join(self._resolve(parent, depth + 1), posixpath.basename(p))
        kind, payload = self.tree.get(p, (None, None))
        if kind is None:
            raise IOError(2, "No such file")
        if kind == "link":
            if depth > 20:
                raise IOError(40, "Too many links")
            return self._resolve(payload, depth + 1)
        return p

    def _attr(self, p, name):
        kind, payload = self.tree[p]
        a = SFTPAttributes()
        a.filename = name
        a.st_mode = MODES[kind]
        a.st_size = len(payload) if kind == "file" else 0
        return a

    def stat(self, p):
        self.requests += 1
        real = self._resolve(p)
        return self._attr(real, posixpath.basename(p))

    def lstat(self, p):
        self.requests += 1
        return self._attr(p, posixpath.basename(p))

    def normalize(self, p):
        self.requests += 1
        return self._resolve(p)

    def listdir_attr(self, p):
        self.requests += 1
        real = self._resolve(p)
        out = []
        for path in sorted(self.tree):
            if posixpath.dirname(path) == real and path != real:
                name = posixpath.basename(path)
                if self.follow_in_readdir:
                    try:
                        out.append(self._attr(self._resolve(path), name))
                    except IOError:
                        out.append(self._attr(path, name))
                else:
                    out.append(self._attr(path, name))
        return out

    def get(self, rpath, lpath, callback=None):
        self.opened.append(rpath)
        real = self._resolve(rpath)
        kind, payload = self.tree[real]
        if kind != "file":
            raise AssertionError("opened a non-regular file: " + rpath)   # a real server would hang here
        with open(lpath, "wb") as f:
            f.write(payload)
        if callback:
            callback(len(payload), len(payload))


class FakeWorker:
    def __init__(self, answer="all"):
        self.cancel = False
        self.answer = answer
        self.asked: list[dict] = []
        self.notes: list[str] = []
        self.note = self
        self.progress = self

    def emit(self, *a):
        if len(a) == 1:
            self.notes.append(a[0])

    def cb(self, label, base, total):
        return lambda done, size: None

    def ask_user(self, info):
        self.asked.append(info)
        return self.answer


def files_in(out):
    return sorted(os.path.relpath(os.path.join(d, f), out).replace(os.sep, "/")
                  for d, _s, fs in os.walk(out) for f in fs)


SHARED = [f"app/shared/s{i:02d}.bin" for i in range(40)]


for follow in (False, True):
    tag = " (server follows links in readdir)" if follow else ""
    out = os.path.join(SP, f"out{int(follow)}")
    os.makedirs(out)
    sftp = FakeSftp(TREE, follow)
    w = FakeWorker()
    try:
        msg = explorer.job_download(["/srv/app"], out)(sftp, w)
        ok = True
    except Exception as e:
        msg, ok = repr(e), False
    check("folder download finishes" + tag, ok, msg)
    check("special files never opened" + tag,
          not any(p.endswith((".fifo", ".sock", "/dev")) for p in sftp.opened), sftp.opened)
    got = files_in(out)
    check("regular files, file links and linked folders downloaded (under the limit)" + tag,
          got == sorted(["app/a.txt", "app/cfg.lnk", "app/sub/b.log"] + SHARED), got)
    check("no question under the limit" + tag, w.asked == [])
    check("/proc not walked through a link" + tag, "/proc/kmsg" not in sftp.opened)
    check("empty folders kept" + tag, os.path.isdir(os.path.join(out, "app", "sub", "empty")))
    check("no loop through the folder link" + tag, not os.path.exists(os.path.join(out, "app", "sub", "up"))
          and sftp.requests < 200, sftp.requests)
    check("skipped items reported" + tag, "skipped" in msg, msg)
    check("scan progress shown" + tag, any("Checking folders" in n for n in w.notes), w.notes[-1:])

# the user picked a link to a folder directly: followed once
out = os.path.join(SP, "outlink")
os.makedirs(out)
sftp = FakeSftp(TREE)
explorer.job_download(["/srv/applink"], out)(sftp, FakeWorker())
check("a folder link picked by the user is followed", os.path.isfile(os.path.join(out, "applink", "a.txt")))

# past the limit: counting stops early and the user is asked
LIMIT = (0, 10)                                    # ask above 10 files
for answer, expect in (("all", sorted(["app/a.txt", "app/cfg.lnk", "app/sub/b.log"] + SHARED)),
                       ("no_links", ["app/a.txt", "app/cfg.lnk", "app/sub/b.log"]),
                       ("cancel", None)):
    out = os.path.join(SP, "lim_" + answer)
    os.makedirs(out)
    sftp = FakeSftp(TREE)
    w = FakeWorker(answer)
    try:
        msg = explorer.job_download(["/srv/app"], out, LIMIT)(sftp, w)
    except explorer.Cancelled:
        msg = None
    asked = w.asked[0] if w.asked else {}
    check(f"limit passed -> asked once ({answer})", len(w.asked) == 1 and asked.get("files") == 11, w.asked)
    if answer == "all":
        check("question lists the linked folder", asked.get("linked") == ["shared"], asked.get("linked"))
        check("counting stopped at the limit (not the whole tree first)", sftp.requests < 40, sftp.requests)
    if expect is None:
        check("cancel downloads nothing", msg is None and sftp.opened == [], sftp.opened)
    else:
        check(f"files after '{answer}'", files_in(out) == expect, files_in(out))
    if answer == "no_links":
        check("linked folder not created and reported", not os.path.exists(os.path.join(out, "app", "shared"))
              and "skipped" in (msg or ""), msg)
check("limit 0 = never ask", FakeWorker().asked == [] and
      explorer.confirm_limits({"download_confirm_gb": 0, "download_confirm_files": 0}) == (0, 0))
check("default limits 1 GB / 10,000 files", explorer.confirm_limits({}) == (1 << 30, 10000))

# cancel while scanning
w = FakeWorker()
w.cancel = True
try:
    explorer.job_download(["/srv/app"], os.path.join(SP, "outc"))(FakeSftp(TREE), w)
    check("cancel during the scan", False)
except explorer.Cancelled:
    check("cancel during the scan", True)

# opening a FIFO by double-click is refused instead of hanging
sftp = FakeSftp(TREE)
try:
    explorer.job_get_file("/srv/app/run.fifo", os.path.join(SP, "tmp", "run.fifo"))(sftp, FakeWorker())
    check("double-click on a FIFO refused", False)
except IOError as e:
    check("double-click on a FIFO refused", sftp.opened == [] and "not a regular file" in str(e), str(e))
os.makedirs(os.path.join(SP, "tmp"), exist_ok=True)
explorer.job_get_file("/srv/app/a.txt", os.path.join(SP, "tmp", "a.txt"))(FakeSftp(TREE), FakeWorker())
check("regular file still opens", open(os.path.join(SP, "tmp", "a.txt"), "rb").read() == b"hello")

# ---------------------------------------------------------------- app log
path = applog.setup()
check("log file under the app folder", path is not None and str(path).startswith(os.environ["APPDATA"]), path)
explorer.log.info("download: /srv/app/sub/b.log")
applog.get("session").info("connected: web (deploy@192.0.2.10:22)")
applog.setup()   # second call is harmless
applog.shutdown()
text = open(path, encoding="utf-8").read()
check("log lines written", "started" in text and "/srv/app/sub/b.log" in text and "connected: web" in text
      and text.count(" started (") == 1, text[-300:])
print("DONE")
