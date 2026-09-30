# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Import of MobaXterm sessions (MobaXterm.ini / *.mxtsessions): SSH only, folders become groups."""
import os
import shutil
import sys
from pathlib import Path

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "mobaxterm")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
sys.path.insert(0, os.path.dirname(TESTS))
from jeopsokheyou import config  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


TAIL = "%%-1%-1%%%22%%0%0%Interactive shell%%%-1%0%0%0%%1080#MobaFont%10%0%0%0%0%236,236,236%0,0,0%180,180,192%0%-1%0%%xterm%-1#0"
# Korean session name written with escapes so this source file stays ASCII-only for Korean
KOREAN_NAME = "".join(map(chr, (0xAC1C, 0xBC1C, 0xC11C, 0xBC84)))   # a Korean word, kept out of the source text
ini = "\r\n".join([
    "[Misc]",
    "notabookmark=#109#0%should.not.import%22%x%",
    "[Bookmarks]",
    "SubRep=",
    "ImgNum=42",
    "root-ssh=#109#0%192.0.2.10%22%alice" + TAIL,
    "rdp-box=#91#4%192.0.2.11%3389%bob%0%-1%%%%%0%0%%%%-1%0%0%%%%#MobaFont%10#0",
    "telnet-box=#98#1%192.0.2.12%23%%%2%%%%%0%0%%1080#MobaFont%10#0",
    "[Bookmarks_1]",
    "SubRep=Azure\\PRE",
    "ImgNum=41",
    "prod-web=#109#0%198.51.100.5%2222%deploy%%-1%-1%%%22%%0%0%Interactive shell%_ProfileDir_\\.ssh\\id_ed25519%%-1%0%0%0%%1080#MobaFont%10#0",
    KOREAN_NAME + "=#109#0%198.51.100.6%22%root" + TAIL,
    "",
])
ini_path = Path(SP) / "MobaXterm.ini"
ini_path.write_bytes(ini.encode("cp949"))            # MobaXterm writes the system ANSI code page
sessions = config.import_mobaxterm_sessions(ini_path)
by_name = {s.name: s for s in sessions}
check("only SSH sessions are imported", sorted(by_name) == sorted(["root-ssh", "prod-web", KOREAN_NAME]), sorted(by_name))
check("sections other than Bookmarks are ignored", "notabookmark" not in by_name)
root = by_name.get("root-ssh")
check("host / port / user", root and (root.host, root.port, root.user) == ("192.0.2.10", 22, "alice"))
check("top-level sessions go to the 'MobaXterm' group", root and root.group == "MobaXterm")
web = by_name.get("prod-web")
check("folder becomes the group", web and web.group == "Azure / PRE", web and web.group)
check("custom port", web and web.port == 2222)
expected_key = str(Path.home() / ".ssh" / "id_ed25519")
check("private key path found and _ProfileDir_ expanded",
      web and web.auth == "key" and Path(web.key_path) == Path(expected_key), web and web.key_path)
check("ANSI (cp949) session names decode", KOREAN_NAME in by_name)
check("no passwords are imported", all(not s.password_enc for s in sessions))

# Exported .mxtsessions files may be UTF-8
export = "\n".join(["[Bookmarks]", "SubRep=Lab", "ImgNum=41",
                    "日本サーバ=#109#0%192.0.2.30%22%taro" + TAIL, ""])
exp_path = Path(SP) / "export.mxtsessions"
exp_path.write_text(export, encoding="utf-8")
exp = config.import_mobaxterm_sessions(exp_path)
check("UTF-8 export", len(exp) == 1 and exp[0].name == "日本サーバ" and exp[0].group == "Lab",
      [(s.name, s.group) for s in exp])
check("missing file returns nothing", config.import_mobaxterm_sessions(Path(SP) / "nope.ini") == [])

# A file saved on Korean Windows must also decode on a PC with a Western code page (e.g. CI runners)
import locale  # noqa: E402
real_pref = locale.getpreferredencoding
locale.getpreferredencoding = lambda do_setlocale=True: "cp1252"
try:
    names = [s.name for s in config.import_mobaxterm_sessions(ini_path)]
    check("Korean file decodes on a Western-code-page PC", KOREAN_NAME in names, names)
    western = Path(SP) / "western.ini"
    western_lines = ["[Bookmarks]", "SubRep=", "ImgNum=41", "café-server=#109#0%192.0.2.40%22%zoë%%", ""]
    western.write_bytes("\r\n".join(western_lines).encode("cp1252"))
    w = config.import_mobaxterm_sessions(western)
    check("Western accented names still decode", [(x.name, x.user) for x in w] == [("café-server", "zoë")],
          [(x.name, x.user) for x in w])
finally:
    locale.getpreferredencoding = real_pref

# On macOS, Windows-style key paths are converted to POSIX separators
real_win = config.paths.IS_WINDOWS
config.paths.IS_WINDOWS = False
try:
    mac_web = {x.name: x for x in config.import_mobaxterm_sessions(ini_path)}["prod-web"]
    check("key path uses '/' on macOS", "\\" not in mac_web.key_path and mac_web.key_path.endswith("/.ssh/id_ed25519"),
          mac_web.key_path)
finally:
    config.paths.IS_WINDOWS = real_win
print("DONE")
