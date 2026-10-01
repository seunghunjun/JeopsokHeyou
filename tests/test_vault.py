# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Optional master password (local vault): on/off, lock/unlock, recovery key, change, reset."""
import json
import os
import shutil
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
os.environ["APPDATA"] = os.path.join(TESTS, ".work", "appdata-vault")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(TESTS))
from jeopsokheyou import vault  # noqa: E402
from jeopsokheyou.config import Session, SessionStore  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


os_store = sys.platform in ("win32", "darwin")
store = SessionStore()
a = Session(host="192.0.2.1", user="alice", name="a")
a.password = "alpha-secret"
b = Session(host="192.0.2.2", user="bob", name="b", auth="key")
b.passphrase = "bravo-phrase"
store.upsert(a)
store.upsert(b)
check("off by default", not vault.enabled())

# ---------------------------------------------------------------- turn on
try:
    vault.create("short")
    check("too-short password rejected", False)
except vault.VaultError as e:
    check("too-short password rejected", str(e) == "too-short")
recovery = vault.create("correct horse battery")
check("recovery key format", len(recovery) == 29 and recovery.count("-") == 5, recovery)
moved = store.move_secrets_to_vault()
check("existing secrets moved into the vault", moved == (2 if os_store else 0), moved)
raw = open(store.path, encoding="utf-8").read()
check("sessions.json holds only vault tokens", "alpha-secret" not in raw and
      all(s["password_enc"] in ("",) or s["password_enc"].startswith("vault:") for s in json.loads(raw)["sessions"]))
if os_store:
    check("secrets still readable while unlocked", store.get(a.id).password == "alpha-secret"
          and store.get(b.id).passphrase == "bravo-phrase")
vf = open(vault.vault_file(), encoding="utf-8").read()
check("vault file has no plain key material", "correct horse" not in vf and recovery.replace("-", "") not in vf)

# new secrets while on
c = Session(host="192.0.2.3", user="carol", name="c")
c.password = "charlie"
store.upsert(c)
check("new secret stored in the vault", c.password_enc.startswith("vault:") and c.password == "charlie")

# ---------------------------------------------------------------- lock / unlock
vault.lock()
asked = []
vault.request_unlock = lambda: asked.append(1) or False      # the UI would show the unlock dialog here
check("locked: secret not readable", SessionStore().get(c.id).password == "")
check("locked: the UI is asked to unlock", len(asked) >= 1)
check("wrong password refused", not vault.unlock("wrong password!"))
check("master password unlocks", vault.unlock("correct horse battery") and SessionStore().get(c.id).password == "charlie")
vault.lock()
check("recovery key unlocks (any case, dashes optional)", vault.unlock_with_recovery(recovery.lower().replace("-", " ")))
check("tampered token is rejected", vault.decrypt(f"{c.id}.password", c.password_enc[:-4] + "AAAA") == "")
check("token bound to its session (cannot be copied to another)", vault.decrypt(f"{a.id}.password", c.password_enc) == "")

# ---------------------------------------------------------------- change password
vault.change_password("new master password")
vault.lock()
check("old password no longer works", not vault.unlock("correct horse battery"))
check("new password works", vault.unlock("new master password"))
vault.lock()
check("recovery key still works after a change", vault.unlock_with_recovery(recovery))

# ---------------------------------------------------------------- turn off
store = SessionStore()
store.move_secrets_out_of_vault()
vault.remove()
check("turned off", not vault.enabled() and not vault.unlocked())
store = SessionStore()
if os_store:
    check("secrets back with the OS and readable", store.get(c.id).password == "charlie"
          and not store.get(c.id).password_enc.startswith("vault:"))

# ---------------------------------------------------------------- reset (both lost)
vault.create("another password 1")
store.move_secrets_to_vault()
vault.lock()
vault.request_unlock = None
store.drop_vault_secrets()
vault.remove()
store = SessionStore()
check("reset keeps the sessions", len(store.sessions) == 3)
check("reset forgets only the locked secrets", all(not s.password_enc and not s.passphrase_enc for s in store.sessions))
check("after reset secrets use the OS again", not vault.enabled())
print("DONE")
