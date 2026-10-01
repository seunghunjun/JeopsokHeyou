# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Import of OpenSSH client config files (~/.ssh/config, also what Termius exports)."""
import os
import shutil
import sys
from pathlib import Path

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "sshconfig")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(os.path.join(SP, "conf.d"))
os.environ["APPDATA"] = os.path.join(SP, "appdata")
sys.path.insert(0, os.path.dirname(TESTS))
from jeopsokheyou import sshconfig  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


main = Path(SP) / "config"
inc = Path(SP) / "conf.d" / "extra.conf"
inc.write_text("Host staging\n    HostName 198.51.100.20\n    User deploy\n", encoding="utf-8")
main.write_text(f"""# global defaults
Include "{(Path(SP) / 'conf.d' / '*.conf').as_posix()}"

Host bastion
    HostName 192.0.2.1
    User jumper
    Port 2200

Host web01 web02
    HostName %h.example.test
    User=alice
    IdentityFile "~/.ssh/id with space"
    LocalForward 127.0.0.1:8080 localhost:80
    LocalForward 5432 db.internal:5432
    RemoteForward 9000 127.0.0.1:3000
    DynamicForward 1080
    ProxyJump bastion

Host deep
    HostName 203.0.113.9
    ProxyJump ops@192.0.2.50:2222,bastion

Host winkey
    HostName 192.0.2.60
    IdentityFile C:\\Users\\me\\.ssh\\id_ed25519

Host web0* !web02
    Port 2022

Match host foo
    User should-not-apply

Host *
    User fallback
    Port 22
""", encoding="utf-8")

found = sshconfig.import_ssh_config(main)
by = {s.name: s for s in found}
check("concrete hosts only (no wildcards)", {"bastion", "web01", "web02", "deep", "winkey", "staging"} <= set(by)
      and not any("*" in n for n in by), sorted(by))
check("Include was followed", "staging" in by and by["staging"].host == "198.51.100.20")
b = by["bastion"]
check("bastion host/port/user", (b.host, b.port, b.user) == ("192.0.2.1", 2200, "jumper"))
w1, w2 = by["web01"], by["web02"]
check("%h expands to the alias", w1.host == "web01.example.test", w1.host)
check("Keyword=value syntax", w1.user == "alice")
check("first value wins (Host * defaults do not override)", w1.user == "alice" and b.user == "jumper")
check("defaults from Host * fill missing values", by["deep"].user == "fallback", by["deep"].user)
check("wildcard block applies (port 2022)", w1.port == 2022, w1.port)
check("negated pattern excludes web02", w2.port == 22, w2.port)
check("quoted IdentityFile with a space, ~ expanded",
      w1.auth == "key" and Path(w1.key_path) == Path.home() / ".ssh" / "id with space", w1.key_path)
check("Windows path keeps backslashes", by["winkey"].key_path == "C:\\Users\\me\\.ssh\\id_ed25519", by["winkey"].key_path)
kinds = [(f["kind"], f["bind_host"], f["bind_port"], f["dest_host"], f["dest_port"]) for f in w1.forwards]
check("forwards parsed", kinds == [("L", "127.0.0.1", 8080, "localhost", 80), ("L", "127.0.0.1", 5432, "db.internal", 5432),
                                   ("R", "localhost", 9000, "127.0.0.1", 3000), ("D", "127.0.0.1", 1080, "", 0)], kinds)
check("ProxyJump links to the bastion session", w1.jump == b.id)
hop = next((s for s in found if s.host == "192.0.2.50"), None)
check("multi-hop: first hop created and chained", hop is not None and hop.user == "ops" and hop.port == 2222
      and by["deep"].jump == b.id and b.jump == hop.id, hop and (hop.user, hop.port))
check("Match block skipped", all(s.user != "should-not-apply" for s in found))
check("group is 'SSH config'", all(s.group == "SSH config" for s in found))
check("missing file returns nothing", sshconfig.import_ssh_config(Path(SP) / "nope") == [])

# Loops in Include must not hang
loop = Path(SP) / "loop"
loop.write_text(f"Include {loop.as_posix()}\nHost x\n  HostName 192.0.2.99\n", encoding="utf-8")
check("Include loop is ignored", [s.host for s in sshconfig.import_ssh_config(loop)] == ["192.0.2.99"])

# parse_forward edge cases
pf = sshconfig.parse_forward
check("IPv6 bind address", pf("L", ["[::1]:8080", "[2001:db8::1]:80"]) ==
      {"kind": "L", "bind_host": "::1", "bind_port": 8080, "dest_host": "2001:db8::1", "dest_port": 80})
check("'*' binds all interfaces", pf("D", ["*:1080"])["bind_host"] == "0.0.0.0")
check("slash syntax", pf("L", ["8080", "db/5432"])["dest_host"] == "db")
check("unix socket forward skipped", pf("L", ["/tmp/sock", "db:1"]) is None)
check("remote SOCKS (no destination) skipped", pf("R", ["1080"]) is None)
print("DONE")
