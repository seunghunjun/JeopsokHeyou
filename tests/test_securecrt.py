# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Import of SecureCRT session files (Config/Sessions folder). Fixtures use documentation-only addresses."""
import os
import shutil
import sys
from pathlib import Path

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "securecrt")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
sys.path.insert(0, os.path.dirname(TESTS))
from jeopsokheyou import securecrt  # noqa: E402

NL = "\r\n"


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def session_file(path: Path, host, port_hex, user="", proto="SSH2", key="", fwd=(), rfwd=(), password=True):
    lines = ['S:"Username"=' + user]
    if password:
        lines.append('S:"Password V2"=02:abcdef0123456789')
    lines += ['S:"Identity Filename V2"=' + key, 'S:"Protocol Name"=' + proto, 'S:"Hostname"=' + host,
              'S:"Firewall Name"=None', 'D:"[SSH2] Port"=' + port_hex,
              'Z:"Port Forward Table V3"=%08x' % len(fwd)] + [" " + r for r in fwd] + \
        ['Z:"Reverse Forward Table V3"=%08x' % len(rfwd)] + [" " + r for r in rfwd] + \
        ['Z:"Description"=00000000', 'S:"Emulation"=Xterm']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\ufeff" + NL.join(lines) + NL).encode("utf-8"))


root = Path(SP) / "Sessions"
session_file(root / "web-01.ini", "192.0.2.10", "00000016", "deploy")
session_file(root / "TestGroup" / "db.ini", "192.0.2.31", "000008ae", "user1",
             fwd=["1|db|15432|1|198.51.100.41|5432||"], rfwd=["1|test|18080|1|127.0.0.1|8080||"])
session_file(root / "TestGroup" / "Deep" / "keyed.ini", "203.0.113.5", "00000016", "ops", key=r"C:\keys\id_ed25519")
session_file(root / "TestGroup" / "router.ini", "192.0.2.99", "00000017", proto="Telnet")
session_file(root / "Default.ini", "", "00000016")
session_file(root / "TestGroup" / "inner.ini", "198.51.100.60", "00000016", "app")
session_file(root / "bastion.ini", "192.0.2.1", "00000016", "jump")
for name, target in (("inner.ini", "Session:bastion"), ("db.ini", "Session:TestGroup/inner")):
    p = root / "TestGroup" / name
    p.write_bytes(p.read_bytes().replace(b'S:"Firewall Name"=None', b'S:"Firewall Name"=' + target.encode()))
(root / "__FolderData__.ini").write_text('Z:"Folder List V2"=00000001\r\n TestGroup\r\n', encoding="utf-8")

sessions, skipped = securecrt.import_securecrt_sessions(root)
by = {s.name: s for s in sessions}
check("SSH sessions imported, templates and metadata ignored",
      sorted(by) == ["bastion", "db", "inner", "keyed", "web-01"], sorted(by))
check("jump host (Firewall = Session:name) linked", by["inner"].jump == by["bastion"].id)
check("jump host in a folder (Session:Folder/name) linked", by["db"].jump == by["inner"].id)
check("no jump host when Firewall is None", by["web-01"].jump == "")
check("non-SSH sessions skipped and counted", skipped == 1, skipped)
w = by["web-01"]
check("top-level sessions go to the SecureCRT group", (w.host, w.port, w.user, w.group) == ("192.0.2.10", 22, "deploy",
                                                                                           "SecureCRT"))
db = by["db"]
check("hex port and folder as group", (db.port, db.group) == (2222, "TestGroup"), (db.port, db.group))
check("local and remote forwards", [(f["kind"], f["bind_port"], f["dest_host"], f["dest_port"]) for f in db.forwards]
      == [("L", 15432, "198.51.100.41", 5432), ("R", 18080, "127.0.0.1", 8080)], db.forwards)
k = by["keyed"]
check("nested folders become subgroups", k.group == "TestGroup / Deep", k.group)
check("key file", k.auth == "key" and k.key_path == r"C:\keys\id_ed25519")
check("passwords never read", "Password V2" not in securecrt.parse_session_file(root / "web-01.ini"))
one, _ = securecrt.import_securecrt_sessions(root / "TestGroup" / "db.ini")
check("a single session file can be imported too", len(one) == 1 and one[0].host == "192.0.2.31")
utf16 = Path(SP) / "u16.ini"
utf16.write_bytes(('S:"Hostname"=192.0.2.77' + NL + 'D:"[SSH2] Port"=00000016' + NL).encode("utf-16"))
u, _ = securecrt.import_securecrt_sessions(utf16)
check("UTF-16 files", len(u) == 1 and u[0].host == "192.0.2.77")
print("DONE")
