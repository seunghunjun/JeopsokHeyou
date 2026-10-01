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

# MobaSSHTunnel list ([PortForwarding] in the same file), as written by MobaXterm 26.5
from jeopsokheyou.config import SessionStore  # noqa: E402
from jeopsokheyou.tunnels import TunnelStore, import_mobaxterm_tunnels, parse_mobaxterm_tunnels  # noqa: E402
tun_ini = Path(SP) / "tunnels.ini"
BS = chr(92)   # backslash, as in MobaXterm's Windows key paths
tun_ini.write_text((chr(13) + chr(10)).join([
    "[Bookmarks]", "SubRep=", "ImgNum=42",
    "[PortForwarding]",
    "0000.tun-local=Local;user1@192.0.2.1:2201;192.0.2.91:3306;11111;0;No SSH key selected;0.0.0.0;No proxy selected;0",
    "0001.=Remote;user2@192.0.2.2:2202;192.0.2.92:8080;22222;0;No SSH key selected;0.0.0.0;No proxy selected;0",
    f"0002.=Dynamic;user3@192.0.2.3:2203;-:0;33333;0;_ProfileDir_{BS}.ssh{BS}id_ed25519;127.0.0.1;No proxy selected;0",
    "0003.=Telnet;broken",
    "", "[Misc]", "0004.=Local;user9@192.0.2.9:22;192.0.2.9:1;1;0;x;0.0.0.0;y;0",
]), encoding="utf-8")
tuns = parse_mobaxterm_tunnels(tun_ini)
check("three tunnels parsed (others ignored)", len(tuns) == 3, len(tuns))
t0, t1, t2 = tuns
check("local tunnel", t0["name"] == "tun-local" and (t0["user"], t0["host"], t0["port"]) == ("user1", "192.0.2.1", 2201)
      and t0["forward"] == {"kind": "L", "bind_host": "127.0.0.1", "bind_port": 11111, "dest_host": "192.0.2.91", "dest_port": 3306},
      t0)
check("MobaXterm's all-interfaces default becomes this PC only (local/dynamic)",
      t0["forward"]["bind_host"] == "127.0.0.1")
check("remote tunnel keeps the server-side listen address", t1["forward"]["bind_host"] == "0.0.0.0")
check("remote tunnel", t1["forward"]["kind"] == "R" and t1["forward"]["bind_port"] == 22222
      and (t1["forward"]["dest_host"], t1["forward"]["dest_port"]) == ("192.0.2.92", 8080), t1)
check("dynamic tunnel with key and listen address", t2["forward"]["kind"] == "D" and t2["forward"]["bind_host"] == "127.0.0.1"
      and t2["key_path"].endswith("id_ed25519") and "_ProfileDir_" not in t2["key_path"], t2)
st, ts = SessionStore(), TunnelStore()
added, dup, new_sessions = import_mobaxterm_tunnels(tun_ini, st, ts)
check("tunnels and their SSH sessions added", (added, dup, new_sessions) == (3, 0, 3), (added, dup, new_sessions))
check("unnamed tunnels get a readable name", ts.tunnels[1].name.startswith("R "), ts.tunnels[1].name)
check("tunnel points at its session", st.get(ts.tunnels[0].session_id).host == "192.0.2.1")
check("autostart off after import", not any(t.autostart for t in ts.tunnels))
added, dup, new_sessions = import_mobaxterm_tunnels(tun_ini, st, ts)
check("importing again adds nothing", (added, dup, new_sessions) == (0, 3, 0), (added, dup, new_sessions))
check("saved to disk", len(TunnelStore().tunnels) == 3 and len(SessionStore().sessions) == 3)
print("DONE")
