# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Session edit and settings dialogs."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFontComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QWidget)

from . import paths
from .config import Session
from .i18n import tr

# Labels are English source strings; translated with tr() when displayed.
IDLE_CHOICES = ((0, "Off"), (10, "10 min"), (30, "30 min"), (60, "1 hour"), (120, "2 hours"), (240, "4 hours"))


class SessionDialog(QDialog):
    def __init__(self, session: Session | None = None, groups: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit Session") if session else tr("New Session"))
        self.setMinimumWidth(460)
        self.session = session or Session()
        s = self.session

        form = QFormLayout(self)
        self.name = QLineEdit(s.name)
        self.name.setPlaceholderText(tr("Leave empty for user@host"))
        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.addItems([""] + sorted(g for g in (groups or []) if g))
        self.group.setCurrentText(s.group)
        self.host = QLineEdit(s.host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(s.port or 22))
        self.user = QLineEdit(s.user)

        self.auth = QComboBox()
        self.auth.addItem(tr("Password"), "password")
        self.auth.addItem(tr("Private key (OpenSSH format)"), "key")
        self.auth.setCurrentIndex(0 if s.auth == "password" else 1)
        self.auth.currentIndexChanged.connect(self._sync)

        self.password = QLineEdit(s.password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(tr("Leave empty to be asked when connecting"))
        self.save_pw = QCheckBox(tr("Save password in the macOS Keychain") if paths.IS_MAC
                                 else tr("Save password (encrypted with your Windows account)"))
        self.save_pw.setChecked(bool(s.password_enc))

        self.key_path = QLineEdit(s.key_path)
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self._pick_key)
        key_row = QWidget()
        kl = QHBoxLayout(key_row)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(self.key_path, 1)
        kl.addWidget(browse)
        self.passphrase = QLineEdit(s.passphrase)
        self.passphrase.setEchoMode(QLineEdit.EchoMode.Password)

        self.init_dir = QLineEdit(s.init_dir)
        self.init_dir.setPlaceholderText(tr("Explorer start folder (empty = home)"))
        self.encoding = QComboBox()
        self.encoding.setEditable(True)
        self.encoding.addItems(["utf-8", "euc-kr", "cp949"])
        self.encoding.setCurrentText(s.encoding or "utf-8")
        self.idle = QComboBox()
        self.idle.addItem(tr("Use global setting"), -1)
        for mins, label in IDLE_CHOICES:
            self.idle.addItem(tr(label), mins)
        if self.idle.findData(s.idle_minutes) < 0:
            self.idle.addItem(tr("{n} min", n=s.idle_minutes), s.idle_minutes)
        self.idle.setCurrentIndex(max(0, self.idle.findData(s.idle_minutes)))
        self.follow = QCheckBox(tr("Sync explorer ↔ terminal location (bash/zsh)"))
        self.follow.setChecked(s.follow_cwd)

        form.addRow(tr("Name"), self.name)
        form.addRow(tr("Group"), self.group)
        form.addRow(tr("Host"), self.host)
        form.addRow(tr("Port"), self.port)
        form.addRow(tr("User"), self.user)
        form.addRow(tr("Authentication"), self.auth)
        form.addRow(tr("Password"), self.password)
        form.addRow("", self.save_pw)
        form.addRow(tr("Private key file"), key_row)
        form.addRow(tr("Key passphrase"), self.passphrase)
        form.addRow(tr("Start folder"), self.init_dir)
        form.addRow(tr("Character encoding"), self.encoding)
        form.addRow(tr("Auto disconnect"), self.idle)
        form.addRow("", self.follow)
        self._key_widgets = (key_row, self.passphrase)
        self._form = form

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._sync()

    def _sync(self):
        is_key = self.auth.currentData() == "key"
        for w in self._key_widgets:
            w.setEnabled(is_key)

    def _pick_key(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Select Private Key"), self.key_path.text() or "")
        if f:
            if f.lower().endswith(".ppk"):
                QMessageBox.information(self, tr("PuTTY Key"),
                                        tr("PPK keys cannot be read directly.\n"
                                           "Convert it with PuTTYgen → Conversions → Export OpenSSH key."))
            self.key_path.setText(f)

    def _accept(self):
        if not self.host.text().strip():
            QMessageBox.warning(self, tr("Check Input"), tr("Please enter a host."))
            return
        s = self.session
        s.name = self.name.text().strip()
        s.group = self.group.currentText().strip()
        s.host = self.host.text().strip()
        s.port = self.port.value()
        s.user = self.user.text().strip()
        s.auth = self.auth.currentData()
        s.password = self.password.text() if self.save_pw.isChecked() else ""
        s.key_path = self.key_path.text().strip()
        s.passphrase = self.passphrase.text() if self.save_pw.isChecked() else ""
        s.init_dir = self.init_dir.text().strip()
        s.encoding = self.encoding.currentText().strip() or "utf-8"
        s.follow_cwd = self.follow.isChecked()
        s.idle_minutes = int(self.idle.currentData())
        # Unsaved passwords are kept for this connection only
        self.transient_password = self.password.text()
        self.transient_passphrase = self.passphrase.text()
        self.accept()


class SettingsDialog(QDialog):
    """Appearance, UI font and terminal font settings. Previews instantly (Cancel restores)."""

    def __init__(self, settings: dict, term_font: QFont, parent=None):
        super().__init__(parent)
        from . import theme
        from .mainwindow import DEFAULT_THEME, THEME_CHOICES
        self.setWindowTitle(tr("Settings"))
        self.setMinimumWidth(420)
        self._theme = theme
        self._orig = (settings.get("theme", DEFAULT_THEME), settings.get("ui_font", "default"))

        form = QFormLayout(self)
        form.setVerticalSpacing(12)
        form.setContentsMargins(20, 18, 20, 16)

        self.mode = QComboBox()
        for key, label in THEME_CHOICES:
            self.mode.addItem(tr(label), key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self._orig[0])))

        self.ui_font = QComboBox()
        for key, (label, _f, _px) in theme.UI_FONTS.items():
            self.ui_font.addItem(tr(label), key)
        self.ui_font.setCurrentIndex(max(0, self.ui_font.findData(self._orig[1])))

        self.term_family = QFontComboBox()
        self.term_family.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self.term_family.setCurrentFont(term_font)
        self.term_size = QSpinBox()
        self.term_size.setRange(6, 40)
        self.term_size.setValue(term_font.pointSize())
        term_row = QWidget()
        tl = QHBoxLayout(term_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.term_family, 1)
        tl.addWidget(self.term_size)

        # Language: applied on the next start (every window is built in one language)
        from . import i18n
        self.language = QComboBox()
        self.language.addItem(tr("Same as {os}", os=paths.OS_NAME), "system")
        for code, native in i18n.LANGUAGES.items():
            self.language.addItem(native, code)   # native names are never translated
        self._orig_language = settings.get("language", "system")
        self.language.setCurrentIndex(max(0, self.language.findData(self._orig_language)))
        form.addRow(tr("Language"), self.language)
        form.addRow(tr("Appearance"), self.mode)
        form.addRow(tr("UI font"), self.ui_font)
        form.addRow(tr("Terminal font"), term_row)
        self.idle = QComboBox()
        for mins, label in IDLE_CHOICES:
            self.idle.addItem(tr(label), mins)
        cur = int(settings.get("idle_minutes", 30) or 0)
        if self.idle.findData(cur) < 0:
            self.idle.addItem(tr("{n} min", n=cur), cur)
        self.idle.setCurrentIndex(max(0, self.idle.findData(cur)))
        self.idle.setToolTip(tr("Disconnects when there is no keyboard/mouse activity or file transfer "
                                "(warns 1 minute before).\n"
                                "Each session can override this in Edit Session."))
        form.addRow(tr("Auto disconnect"), self.idle)
        note = QLabel(tr("The UI font applies to menus, lists and buttons. "
                         "The terminal can only use monospaced fonts."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form.addRow(note)

        # Preview immediately on selection
        self.mode.currentIndexChanged.connect(self._preview)
        self.ui_font.currentIndexChanged.connect(self._preview)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _preview(self):
        self._theme.manager.apply(QApplication.instance(), self.mode.currentData(), self.ui_font.currentData())

    def reject(self):
        self._theme.manager.apply(QApplication.instance(), *self._orig)   # restore original
        super().reject()

    def values(self) -> dict:
        return {
            "theme": self.mode.currentData(),
            "ui_font": self.ui_font.currentData(),
            "term_family": self.term_family.currentFont().family(),
            "term_size": self.term_size.value(),
            "idle_minutes": int(self.idle.currentData()),
            "language": self.language.currentData(),
        }
