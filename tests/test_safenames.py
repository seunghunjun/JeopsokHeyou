# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""File names sent by a malicious SFTP server must never write files outside the local folder (path traversal)."""
import os, sys, shutil, stat
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work"); os.makedirs(SP, exist_ok=True)
sys.path.insert(0, os.path.dirname(TESTS))
from jeopsokheyou.safenames import UnsafeName, local_name, safe_join
from jeopsokheyou.explorer import job_download
from jeopsokheyou import dragout

def check(n, ok, x=""): print(("PASS " if ok else "FAIL ") + n, x)

EVIL = [r"..\..\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\evil.bat",
        r"C:\Windows\Temp\evil.dll", "..", ".", "...", "a/../../b", r"sub\..\..\x"]
base = os.path.join(SP, "dl"); shutil.rmtree(base, ignore_errors=True); os.makedirs(base)
for n in EVIL:
    try:
        p = safe_join(base, n)
        inside = os.path.commonpath([os.path.abspath(base), os.path.abspath(p)]) == os.path.abspath(base)
        check(f"stays inside folder: {n[:30]!r}", inside and os.path.dirname(os.path.abspath(p)) == os.path.abspath(base), p)
    except UnsafeName:
        check(f"rejected: {n[:30]!r}", True)
check("normal names unchanged", local_name("web.xml") == "web.xml" and local_name("日本語 ファイル.txt") == "日本語 ファイル.txt")
check("Windows-forbidden characters replaced", local_name('a:b*c?.txt') == "a_b_c_.txt")
check("device names avoided", local_name("CON") == "_CON" and local_name("nul.txt") == "_nul.txt")
check("trailing dots/spaces removed", local_name("name. ") == "name")

# Fake SFTP: folder download when malicious names are mixed into the folder
class A:
    def __init__(self, name, is_dir=False, size=3):
        self.filename, self.st_mode, self.st_size = name, (stat.S_IFDIR if is_dir else stat.S_IFREG) | 0o644, size
class FakeSftp:
    tree = {"/srv/pkg": [A("ok.txt"), A(r"..\..\evil.bat"), A(r"C:\Windows\evil.dll"), A("..", True)]}
    def stat(self, p):
        if p in self.tree: return A(p, True)
        return A(p)
    def listdir_attr(self, p): return self.tree.get(p, [])
    def normalize(self, p): return p
    def get(self, rp, lp, callback=None):
        open(lp, "w", encoding="utf-8").write("x")
class W:
    cancel = False
    def cb(self, *a): return None
    class note:
        emit = staticmethod(lambda *a: None)
res = job_download(["/srv/pkg"], base)(FakeSftp(), W())
written = sorted(os.path.relpath(os.path.join(r, f), base) for r, _d, fs in os.walk(base) for f in fs)
# Names with backslashes/drives are saved inside the folder under safe names; ".." is skipped
expected = sorted(os.path.join("pkg", n) for n in ("ok.txt", ".._.._evil.bat", "C__Windows_evil.dll"))
check("folder download: everything inside the target folder under safe names", written == expected, written)
check("'..' entry skipped and reported", "unsafe names skipped" in res, res)
outside = [p for p in (os.path.join(SP, "evil.bat"), os.path.join(os.path.dirname(SP), "evil.bat"),
                       r"C:\Windows\evil.dll") if os.path.exists(p)]
check("nothing created outside the target folder", not outside, outside)
staging, paths, _m = dragout.make_placeholders([(r"..\..\evil.bat", False)])
check("drag placeholders stay inside the staging folder", all(os.path.dirname(p) == staging for p in paths), paths)
dragout.cleanup_staging(staging)
try:
    dragout.make_placeholders([("..", True)]); check("drag placeholder: '..' rejected", False)
except UnsafeName:
    check("drag placeholder: '..' rejected", True)
print("DONE")
