# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Dialogs for the optional master password: turn on/off, unlock, recovery key, change, reset."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from . import config, vault
from .config import SessionStore
from .i18n import tr

# Auto-lock choices in minutes (0 = never); labels are English source strings
LOCK_CHOICES = ((5, "5 min"), (15, "15 min"), (30, "30 min"), (60, "1 hour"), (0, "Never"))
DEFAULT_LOCK_MINUTES = 15


def _password_field(placeholder: str = "") -> QLineEdit:
    e = QLineEdit()
    e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setPlaceholderText(placeholder)
    return e


def _note(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setObjectName("Muted")
    return lb


class UnlockDialog(QDialog):
    """Ask for the master password (or the recovery key). Offers a reset when both are lost."""

    def __init__(self, store: SessionStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.recovery_mode = False
        self.setWindowTitle(tr("Unlock"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        self.intro = QLabel(tr("Enter your master password to use saved passwords and keys."))
        self.intro.setWordWrap(True)
        lay.addWidget(self.intro)
        self.field = _password_field(tr("Master password"))
        lay.addWidget(self.field)
        self.error = QLabel()
        self.error.setStyleSheet("color: #FF3B30;")
        self.error.hide()
        lay.addWidget(self.error)
        links = QHBoxLayout()
        self.switch = QPushButton(tr("Use recovery key instead"))
        self.switch.setFlat(True)
        self.switch.clicked.connect(self._toggle_mode)
        forgot = QPushButton(tr("Lost both?"))
        forgot.setFlat(True)
        forgot.clicked.connect(self._reset)
        links.addWidget(self.switch)
        links.addStretch(1)
        links.addWidget(forgot)
        lay.addLayout(links)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Unlock"))
        bb.accepted.connect(self._try)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _toggle_mode(self):
        self.recovery_mode = not self.recovery_mode
        self.field.clear()
        self.error.hide()
        if self.recovery_mode:
            self.field.setEchoMode(QLineEdit.EchoMode.Normal)
            self.field.setPlaceholderText("XXXX-XXXX-XXXX-XXXX-XXXX-XXXX")
            self.intro.setText(tr("Enter the recovery key you saved when you turned on the master password."))
            self.switch.setText(tr("Use master password instead"))
        else:
            self.field.setEchoMode(QLineEdit.EchoMode.Password)
            self.field.setPlaceholderText(tr("Master password"))
            self.intro.setText(tr("Enter your master password to use saved passwords and keys."))
            self.switch.setText(tr("Use recovery key instead"))
        self.field.setFocus()

    def _try(self):
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok = (vault.unlock_with_recovery if self.recovery_mode else vault.unlock)(self.field.text())
        finally:
            QGuiApplication.restoreOverrideCursor()
        if ok:
            if self.recovery_mode:
                QMessageBox.information(self, tr("Unlocked with recovery key"),
                                        tr("Consider setting a new master password in Settings → Master password."))
            self.accept()
        else:
            self.error.setText(tr("Wrong recovery key.") if self.recovery_mode else tr("Wrong password."))
            self.error.show()
            self.field.selectAll()
            self.field.setFocus()

    def _reset(self):
        r = QMessageBox.warning(
            self, tr("Reset master password"),
            tr("Without the master password or the recovery key, the saved passwords and key passphrases "
               "cannot be recovered — by anyone.\n\n"
               "Resetting deletes only those saved secrets and turns the master password off. "
               "Your sessions, groups and settings are kept; you will enter passwords again when you connect.\n\n"
               "Reset now?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Yes:
            n = self.store.drop_vault_secrets()
            vault.remove()
            QMessageBox.information(self, tr("Reset master password"),
                                    tr("Reset done. {n} saved secrets were deleted.", n=n))
            self.accept()


class RecoveryKeyDialog(QDialog):
    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Your recovery key"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Write this key down or store it in a safe place. It is shown only once.\n"
                                "If you forget the master password, it is the only way to unlock your saved passwords.")))
        lb = QLabel(key)
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSize(15)
        lb.setFont(f)
        lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lb.setObjectName("RecoveryKey")
        lb.setMinimumHeight(56)
        lay.addWidget(lb)
        copy = QPushButton(tr("Copy"))
        copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(key), copy.setText(tr("Copied ✓"))))
        lay.addWidget(copy, 0, Qt.AlignmentFlag.AlignHCenter)
        self.saved = QCheckBox(tr("I have saved my recovery key"))
        lay.addWidget(self.saved)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.done_btn = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.done_btn.setText(tr("Done"))
        self.done_btn.setEnabled(False)
        self.saved.toggled.connect(self.done_btn.setEnabled)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)

    def reject(self):
        if self.saved.isChecked():     # Esc only after confirming
            super().reject()


class NewPasswordDialog(QDialog):
    """Choose a master password (turning on, or changing it)."""

    def __init__(self, parent=None, change: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("Change master password") if change else tr("Turn on master password"))
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        if not change:
            form.addRow(_note(tr(
                "Saved passwords and key passphrases will be encrypted with this password, and you will enter it "
                "when JeopsokHeyou starts or after it locks itself. Your session list stays visible without it.\n\n"
                "If you forget it, you can unlock with the recovery key shown next. If you lose both, the saved "
                "passwords are gone (the sessions stay) — nobody, including the developer, can recover them.")))
        self.pw = _password_field(tr("At least {n} characters", n=vault.MIN_PASSWORD))
        self.pw2 = _password_field()
        form.addRow(tr("New master password") if change else tr("Master password"), self.pw)
        form.addRow(tr("Confirm"), self.pw2)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _accept(self):
        if len(self.pw.text()) < vault.MIN_PASSWORD:
            QMessageBox.warning(self, tr("Check Input"), tr("Use at least {n} characters.", n=vault.MIN_PASSWORD))
        elif self.pw.text() != self.pw2.text():
            QMessageBox.warning(self, tr("Check Input"), tr("The passwords do not match."))
        else:
            self.accept()


def ask_unlock(store: SessionStore, parent=None) -> bool:
    if vault.unlocked() or not vault.enabled():
        return True
    return UnlockDialog(store, parent).exec() == QDialog.DialogCode.Accepted and (vault.unlocked() or not vault.enabled())


def install_unlock_hook(store: SessionStore, parent) -> None:
    """Show the unlock dialog whenever a saved secret is needed while locked."""
    busy = []

    def hook() -> bool:
        if busy:
            return False
        busy.append(1)
        try:
            return ask_unlock(store, parent)
        finally:
            busy.clear()
    vault.request_unlock = hook


class VaultDialog(QDialog):
    """Settings → Master password."""

    def __init__(self, store: SessionStore, settings: dict, parent=None):
        super().__init__(parent)
        self.store = store
        self.settings = settings
        self.setWindowTitle(tr("Master password"))
        self.setMinimumWidth(480)
        self.lay = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.lay.addWidget(self.status)
        form = QFormLayout()
        self.lock_after = QComboBox()
        for mins, label in LOCK_CHOICES:
            self.lock_after.addItem(tr(label), mins)
        cur = int(settings.get("vault_lock_minutes", DEFAULT_LOCK_MINUTES))
        self.lock_after.setCurrentIndex(max(0, self.lock_after.findData(cur)))
        self.lock_after.currentIndexChanged.connect(self._save_lock)
        form.addRow(tr("Lock after inactivity"), self.lock_after)
        self.lay.addLayout(form)
        row = QHBoxLayout()
        self.on_btn = QPushButton(tr("Turn on…"))
        self.on_btn.clicked.connect(self.turn_on)
        self.change_btn = QPushButton(tr("Change password…"))
        self.change_btn.clicked.connect(self.change)
        self.lock_btn = QPushButton(tr("Lock now"))
        self.lock_btn.clicked.connect(self.lock_now)
        self.off_btn = QPushButton(tr("Turn off…"))
        self.off_btn.clicked.connect(self.turn_off)
        for b in (self.on_btn, self.change_btn, self.lock_btn, self.off_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        self.lay.addWidget(bb)
        self._sync()

    def _sync(self):
        on = vault.enabled()
        if not on:
            self.status.setText(tr("Off — saved passwords are protected by your {os} account.", os=config.paths.OS_NAME))
        elif vault.unlocked():
            self.status.setText(tr("On — unlocked."))
        else:
            self.status.setText(tr("On — locked."))
        self.on_btn.setVisible(not on)
        for b in (self.change_btn, self.lock_btn, self.off_btn):
            b.setVisible(on)
        self.lock_btn.setEnabled(vault.unlocked())
        self.lock_after.setEnabled(on)

    def _save_lock(self):
        self.settings["vault_lock_minutes"] = int(self.lock_after.currentData())
        config.save_settings(self.settings)

    def turn_on(self):
        d = NewPasswordDialog(self)
        if not d.exec():
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            key = vault.create(d.pw.text())
            self.store.move_secrets_to_vault()
        finally:
            QGuiApplication.restoreOverrideCursor()
        RecoveryKeyDialog(key, self).exec()
        self._sync()

    def change(self):
        if not ask_unlock(self.store, self):
            return
        d = NewPasswordDialog(self, change=True)
        if d.exec():
            vault.change_password(d.pw.text())
            QMessageBox.information(self, tr("Master password"), tr("The master password was changed. "
                                                                    "Your recovery key still works."))
        self._sync()

    def lock_now(self):
        vault.lock()
        self._sync()

    def turn_off(self):
        if not ask_unlock(self.store, self) or not vault.enabled():
            self._sync()
            return
        r = QMessageBox.question(self, tr("Turn off master password"),
                                 tr("Saved passwords will be protected by your {os} account again. Continue?",
                                    os=config.paths.OS_NAME))
        if r == QMessageBox.StandardButton.Yes:
            self.store.move_secrets_out_of_vault()
            vault.remove()
        self._sync()
