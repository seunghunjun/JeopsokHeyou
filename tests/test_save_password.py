# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""New hosts and typed-in passwords are saved (encrypted) by default; Settings can turn that off."""
import os
import shutil
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "savepw")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou import config, dialogs  # noqa: E402
from jeopsokheyou.config import Session, SessionStore  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


d = dialogs.SessionDialog(None)
check("new host: Save password checked by default", d.save_pw.isChecked())
existing = Session(host="192.0.2.11", user="ops")
d2 = dialogs.SessionDialog(existing)
check("existing host without a saved password keeps it off", not d2.save_pw.isChecked())

store = SessionStore(config.app_dir() / "sessions.json")
s = Session(host="192.0.2.12", user="root")
store.upsert(s)


class FakeDialog:
    answer = ("pw-123", True, True)

    def __init__(self, label, parent=None, can_save=True):
        text, save, ok = FakeDialog.answer
        self.password = type("E", (), {"text": lambda _self: text})()
        self.save = type("C", (), {"isChecked": lambda _self: save})()
        self._ok = ok

    def exec(self):
        return self._ok


real = dialogs.PasswordDialog
dialogs.PasswordDialog = FakeDialog
pw = dialogs.ask_password_saving(None, "Password", s, store)
check("typed password returned", pw == "pw-123")
check("...and saved encrypted with the host", SessionStore(store.path).get(s.id).password == "pw-123"
      and s.password_enc and "pw-123" not in store.path.read_text(encoding="utf-8"))
s2 = Session(host="192.0.2.13", user="root")
store.upsert(s2)
FakeDialog.answer = ("once", False, True)
check("unticked: used once, not saved", dialogs.ask_password_saving(None, "Password", s2, store) == "once"
      and not SessionStore(store.path).get(s2.id).password)
FakeDialog.answer = ("x", True, False)
check("cancel returns None", dialogs.ask_password_saving(None, "Password", s2, store) is None)
dialogs.PasswordDialog = real

st = config.load_settings()
st["save_passwords"] = False
config.save_settings(st)
d3, p3 = dialogs.SessionDialog(None), dialogs.PasswordDialog("Password")
check("Settings off: new host not checked", not d3.save_pw.isChecked())
check("Settings off: prompt not checked", not p3.save.isChecked())
st["save_passwords"] = True
config.save_settings(st)
p4, p5 = dialogs.PasswordDialog("Password"), dialogs.PasswordDialog("Password", can_save=False)
check("Settings on: prompt checked", p4.save.isChecked())
check("prompt without a saved host hides the option", p5.save.isHidden())
print("DONE")
