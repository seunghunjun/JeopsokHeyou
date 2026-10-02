# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Find in the terminal, iTerm2 profile import and iTerm2 color schemes."""
import json
import os
import plistlib
import shutil
import sys
from pathlib import Path

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "iterm")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
sys.path.insert(0, os.path.dirname(TESTS))
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou import itermimport  # noqa: E402
from jeopsokheyou.terminal import TerminalWidget, pick_font  # noqa: E402
from jeopsokheyou.termsearch import find_hits  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


# ---------------------------------------------------------------- find in terminal
t = TerminalWidget(pick_font("", 11), scrollback=500)
t.resize(800, 300)
t.show()
app.processEvents()
for i in range(120):
    t.feed(f"line {i:03d} ok\r\n".encode())
KOREAN = "".join(map(chr, (0xC624, 0xB958)))   # a Korean word for "error", kept out of the source text
t.feed(("ERROR: disk full\r\n" + KOREAN + " message\r\nerror again\r\n$ ").encode())
app.processEvents()
n = t.search("error")
check("finds matches in screen and scrollback, ignoring case", n == 2, n)
check("starts at the newest match", t.search_hits[t.search_index][0] == max(h[0] for h in t.search_hits))
t.search("line 005")
row = t.search_hits[t.search_index][0]
top = t._top_abs()
check("scrolls an old match into view", top <= row < top + t.screen.lines and t.scroll_offset > 0, (top, row))
n = t.search(KOREAN)
hit = t.search_hits[0] if t.search_hits else None
check("wide characters: the match covers both cells", n == 1 and hit[2] - hit[1] == 3, hit)
t.search("ok")
total = len(t.search_hits)
start = t.search_index
t.search_step(1)
check("Enter goes to the previous (older) match", t.search_index == start - 1)
t.search_step(-1)
check("Shift+Enter goes back to the newer match", t.search_index == start)
t.search_step(-1)
check("wraps around past the newest match", t.search_index == 0)
t.open_search()
check("search bar opens", t._search_bar is not None and t._search_bar.isVisible())
t._search_bar.edit.setText("disk")
check("typing searches", len(t.search_hits) == 1 and t._search_bar.count.text() == "1/1", t._search_bar.count.text())
t._search_bar.edit.setText("zzz-not-there")
check("no matches shown", t.search_hits == [] and t._search_bar.count.text() != "")
t.close_search()
check("Esc/close clears highlights", not t._search_bar.isVisible() and t.search_hits == [])
check("empty query finds nothing", find_hits([], 80, "") == [])

# ---------------------------------------------------------------- iTerm2 profiles
bookmarks = [
    {"Name": "Prod web", "Guid": "1", "Custom Command": "Yes", "Command": "ssh -p 2222 deploy@192.0.2.10",
     "Tags": ["Production"]},
    {"Name": "DB via bastion", "Guid": "2", "Custom Command": "Yes",
     "Command": "/usr/bin/ssh -i ~/.ssh/id_ed25519 -J jump@192.0.2.1:2200 -L 15432:localhost:5432 root@198.51.100.5",
     "Tags": ["Production", "db"]},
    {"Name": "Local zsh", "Guid": "3", "Custom Command": "No", "Command": ""},
    {"Name": "New style", "Guid": "4", "Custom Command": "SSH", "Command": "-o Port=2022 ops@203.0.113.7"},
    {"Name": "URL form", "Guid": "5", "Custom Command": "Yes", "Command": "ssh ssh://alice@192.0.2.30:2200 uptime"},
    {"Name": "Mosh", "Guid": "6", "Custom Command": "Yes", "Command": "mosh me@192.0.2.40"},
]
pl = Path(SP) / "com.googlecode.iterm2.plist"
pl.write_bytes(plistlib.dumps({"New Bookmarks": bookmarks, "Default Bookmark Guid": "3"}, fmt=plistlib.FMT_BINARY))
sessions, skipped = itermimport.import_iterm_sessions(pl)
by = {s.name: s for s in sessions}
check("ssh profiles imported, local shells and other commands skipped",
      {"Prod web", "DB via bastion", "New style", "URL form"} <= set(by) and skipped == 2, (sorted(by), skipped))
pw = by["Prod web"]
check("port, user and first tag as group", (pw.host, pw.port, pw.user, pw.group) == ("192.0.2.10", 2222, "deploy", "Production"))
db = by["DB via bastion"]
check("key file (~ expanded)", db.auth == "key" and Path(db.key_path) == Path.home() / ".ssh" / "id_ed25519", db.key_path)
check("local forward", db.forwards and db.forwards[0]["bind_port"] == 15432 and db.forwards[0]["dest_port"] == 5432,
      db.forwards)
jump = next((s for s in sessions if s.host == "192.0.2.1"), None)
check("jump host created and linked", jump is not None and jump.port == 2200 and jump.user == "jump" and db.jump == jump.id)
check("iTerm2 3.5 SSH-mode profile with -o Port=", (by["New style"].host, by["New style"].port, by["New style"].user)
      == ("203.0.113.7", 2022, "ops"))
check("ssh:// URL form; remote command ignored", (by["URL form"].host, by["URL form"].port, by["URL form"].user)
      == ("192.0.2.30", 2200, "alice"))
check("profiles without tags go to the iTerm2 group", by["New style"].group == "iTerm2")
dyn = Path(SP) / "dynamic.json"
dyn.write_text(json.dumps({"Profiles": [{"Name": "Dyn", "Guid": "d1", "Custom Command": "Yes",
                                         "Command": "ssh -l bob 192.0.2.77"}]}), encoding="utf-8")
ds, _ = itermimport.import_iterm_sessions(dyn)
check("Dynamic Profiles / exported JSON", len(ds) == 1 and (ds[0].host, ds[0].user) == ("192.0.2.77", "bob"))
junk = Path(SP) / "junk.plist"
junk.write_bytes(b"not a plist")
check("unreadable file returns nothing", itermimport.import_iterm_sessions(junk) == ([], 0))

# ---------------------------------------------------------------- color schemes
def comp(r, g, b):
    return {"Red Component": r, "Green Component": g, "Blue Component": b, "Color Space": "sRGB"}


colors = {f"Ansi {i} Color": comp(i / 15, 0.5, 1 - i / 15) for i in range(16)}
colors.update({"Background Color": comp(0, 0.168, 0.212), "Foreground Color": comp(0.513, 0.58, 0.588),
               "Cursor Color": comp(1, 0, 0), "Selection Color": comp(0, 0, 1)})
ic = Path(SP) / "Solarized Dark.itermcolors"
ic.write_bytes(plistlib.dumps(colors))
scheme = itermimport.load_itermcolors(ic)
check("itermcolors parsed", scheme and scheme["name"] == "Solarized Dark" and len(scheme["ansi"]) == 16
      and scheme["bg"] == "#002b36" and scheme["cursor"] == "#ff0000", scheme and scheme["bg"])
check("not a color scheme is rejected", itermimport.load_itermcolors(pl) is None)
t.apply_scheme(scheme)
check("scheme applied to the terminal", t.bg_default.name() == "#002b36" and t._color("red", True).name() == scheme["ansi"][1]
      and t.cursor_color.name() == "#ff0000")
t.apply_scheme(None)
check("back to the built-in colors", t.bg_default.name().lower() == "#1c1c1e")

# Settings dialog keeps the choice
from jeopsokheyou.dialogs import SettingsDialog  # noqa: E402
settings = {"color_schemes": {"Solarized Dark": scheme}, "terminal_scheme": "Solarized Dark"}
d = SettingsDialog(settings, pick_font("", 11))
check("Settings lists imported schemes and keeps the selection", d.values()["terminal_scheme"] == "Solarized Dark")
print("DONE")
