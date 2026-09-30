# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Saved passwords: encrypted with DPAPI on Windows, stored in the Keychain on macOS.
sessions.json must never contain the plain password."""
import json
import os
import shutil
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata-secrets")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(TESTS))
from jeopsokheyou.config import Session, SessionStore  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


if sys.platform not in ("win32", "darwin"):
    print("SKIP: passwords are only saved on Windows and macOS")
    print("DONE")
    sys.exit(0)

secret = "Pa$$ w0rd 'quote' \"dq\" " + chr(92) + " 日本語 ✓"   # quotes, a backslash, CJK
s = Session(host="example.com", user="alice")
s.password = secret
s.passphrase = "key-phrase"
check("password round trip", s.password == secret)
check("passphrase round trip", s.passphrase == "key-phrase")
store = SessionStore()
store.upsert(s)
raw = open(store.path, encoding="utf-8").read()
check("plain password not in sessions.json", secret not in raw and "key-phrase" not in raw)
check("reload keeps the password", SessionStore().get(s.id).password == secret)
if sys.platform == "darwin":
    check("macOS: only a marker is written to disk", json.loads(raw)["sessions"][0]["password_enc"] == "keychain")
s.password = ""
check("clearing the password", s.password == "" and s.password_enc == "")
s.password = secret
store.upsert(s)
store.remove(s.id)
saved = open(store.path, encoding="utf-8").read()
check("deleting the session removes it from sessions.json", s.id not in saved)
if sys.platform == "darwin":
    check("macOS: deleting the session removes the Keychain item",
          Session(id=s.id, password_enc="keychain").password == "")
print("DONE")
