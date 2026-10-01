# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Master password in the UI: turn on, recovery key, unlock prompt on connect, auto-lock, reset, turn off."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata-vault-ui")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
root = os.path.join(SP, "srvroot-vault")
os.makedirs(root, exist_ok=True)
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, os.path.dirname(TESTS))
from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
from jeopsokheyou import vault, vaultui  # noqa: E402
from jeopsokheyou.config import Session, SessionStore  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow, apply_dark_theme  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def wait(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


# Scripted answers for the modal dialogs
shown = {"recovery": None, "unlock_prompts": 0}
script = {"new_password": "master pass 123", "unlock_with": "master pass 123", "recovery_mode": False, "reset": False}


def new_pw_exec(self):
    self.pw.setText(script["new_password"])
    self.pw2.setText(script["new_password"])
    self._accept()
    return self.result()


def recovery_exec(self):
    shown["recovery"] = [lb.text() for lb in self.findChildren(vaultui.QLabel) if lb.objectName() == "RecoveryKey"][0]
    check("Done stays disabled until the key is confirmed", not self.done_btn.isEnabled())
    self.saved.setChecked(True)
    self.accept()
    return QDialog.DialogCode.Accepted


def unlock_exec(self):
    shown["unlock_prompts"] += 1
    if script["reset"]:
        self._reset()
        return self.result()
    if script["recovery_mode"]:
        self._toggle_mode()
    self.field.setText(script["unlock_with"])
    self._try()
    return self.result() or QDialog.DialogCode.Rejected


vaultui.NewPasswordDialog.exec = new_pw_exec
vaultui.RecoveryKeyDialog.exec = recovery_exec
vaultui.UnlockDialog.exec = unlock_exec

apply_dark_theme(app)
w = MainWindow()
w.show()
wait(lambda: w._started, 2)
s = Session(host="127.0.0.1", port=2299, user="tester", name="srv")
s.password = "pw"
w.store.upsert(s)
w.reload_sessions()

# ---------------------------------------------------------------- turn on
d = vaultui.VaultDialog(w.store, w.settings, w)
check("dialog offers to turn on", d.on_btn.isVisibleTo(d) and not d.off_btn.isVisibleTo(d))
d.turn_on()
check("vault on and unlocked", vault.enabled() and vault.unlocked())
check("recovery key was shown", bool(shown["recovery"]) and len(shown["recovery"]) == 29, shown["recovery"])
check("saved password moved into the vault", SessionStore().get(s.id).password_enc.startswith("vault:"))
check("dialog now offers change / lock / turn off", d.off_btn.isVisibleTo(d) and d.lock_btn.isEnabled())

# ---------------------------------------------------------------- locked → unlock prompt when connecting
w.lock_vault()
check("locked", not vault.unlocked())
w.open_session(w.store.get(s.id))
tab = w.current_tab()
check("unlock asked when a saved password is needed", shown["unlock_prompts"] == 1)
check("connects with the saved password after unlocking", wait(lambda: tab.state == "connected"), tab.state)

# ---------------------------------------------------------------- wrong password keeps it locked
vault.lock()
script["unlock_with"] = "nope nope"
check("wrong password does not unlock", not vaultui.ask_unlock(w.store, w) and not vault.unlocked())

# ---------------------------------------------------------------- recovery key
script.update(recovery_mode=True, unlock_with=shown["recovery"])
check("recovery key unlocks from the dialog", vaultui.ask_unlock(w.store, w) and vault.unlocked())
script.update(recovery_mode=False, unlock_with="master pass 123")

# ---------------------------------------------------------------- auto-lock
w.settings["vault_lock_minutes"] = 5
w._last_input = time.monotonic() - 6 * 60
w._auto_lock()
check("auto-locks after inactivity", not vault.unlocked())
vaultui.ask_unlock(w.store, w)
w._last_input = time.monotonic()
w._auto_lock()
check("stays unlocked while in use", vault.unlocked())
w.settings["vault_lock_minutes"] = 0
w._last_input = time.monotonic() - 99 * 60
w._auto_lock()
check("'Never' does not auto-lock", vault.unlocked())

# ---------------------------------------------------------------- change password
script["new_password"] = "second password 9"
d.change()
vault.lock()
check("changed password works", vault.unlock("second password 9"))

# ---------------------------------------------------------------- turn off
d.turn_off()
check("turned off", not vault.enabled())
check("password readable again without a vault", SessionStore().get(s.id).password == "pw")

# ---------------------------------------------------------------- reset when both are lost
script["new_password"] = "third password 7"
d.turn_on()
vault.lock()
script["reset"] = True
ok = vaultui.ask_unlock(w.store, w)
check("reset turns the vault off", ok and not vault.enabled())
st = SessionStore()
check("reset keeps the session but forgets its password", st.get(s.id) is not None and st.get(s.id).password_enc == "")

w.close()
stop_server(srv)
print("DONE")
