# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Session edit and settings dialogs."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFontComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QWidget)

from . import paths, vault
from .config import Session
from .i18n import tr

# Labels are English source strings; translated with tr() when displayed.
IDLE_CHOICES = ((0, "Off"), (10, "10 min"), (30, "30 min"), (60, "1 hour"), (120, "2 hours"), (240, "4 hours"))


class SessionDialog(QDialog):
    def __init__(self, session: Session | None = None, groups: list[str] | None = None, parent=None,
                 sessions: list[Session] | None = None):
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
        if vault.enabled():
            self.save_pw = QCheckBox(tr("Save password (encrypted with your master password)"))
        else:
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
        # Jump host (ProxyJump): any other saved session
        self.jump = QComboBox()
        self.jump.addItem(tr("None (connect directly)"), "")
        for o in sorted(sessions or [], key=lambda x: (x.group.lower(), x.title().lower())):
            if o.id != s.id:
                self.jump.addItem((f"{o.group} / " if o.group else "") + o.title(), o.id)
        if s.jump and self.jump.findData(s.jump) < 0:
            self.jump.addItem(tr("(deleted session)"), s.jump)
        self.jump.setCurrentIndex(max(0, self.jump.findData(s.jump)))
        from .tunnels import ForwardListEditor
        self.forwards = ForwardListEditor(s.forwards)

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
        form.addRow(tr("Jump host"), self.jump)
        form.addRow(tr("Port forwarding"), self.forwards)
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
        s.jump = self.jump.currentData() or ""
        s.forwards = self.forwards.values()
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
        # Terminal colors: built-in or an imported iTerm2 color scheme (.itermcolors)
        self._settings = settings
        self.scheme = QComboBox()
        self._fill_schemes(settings.get("terminal_scheme", ""))
        scheme_import = QPushButton(tr("Import iTerm2 color scheme…"))
        scheme_import.clicked.connect(self._import_scheme)
        scheme_row = QWidget()
        sl = QHBoxLayout(scheme_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.scheme, 1)
        sl.addWidget(scheme_import)
        form.addRow(tr("Terminal colors"), scheme_row)
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
        self.reflow = QCheckBox(tr("Re-wrap long lines when the terminal width changes"))
        self.reflow.setChecked(bool(settings.get("terminal_reflow", True)))
        form.addRow("", self.reflow)
        # keyword highlighting
        from .highlights import DEFAULT_RULES
        self._hl_enabled = bool(settings.get("highlight_enabled", True))
        self._hl_rules = [dict(r) for r in settings.get("highlight_rules", DEFAULT_RULES)]
        hl_btn = QPushButton(tr("Keyword highlighting…"))
        hl_btn.clicked.connect(self._edit_highlights)
        form.addRow(tr("Highlighting"), hl_btn)
        # session log
        from . import sessionlog
        self.log_all = QCheckBox(tr("Log every session to a file"))
        self.log_all.setChecked(bool(settings.get("log_sessions", False)))
        self.log_stamp = QCheckBox(tr("Add the time to every logged line"))
        self.log_stamp.setChecked(bool(settings.get("log_timestamps", True)))
        self.log_dir = QLineEdit(settings.get("log_dir") or str(sessionlog.default_dir()))
        pick = QPushButton(tr("Browse…"))
        pick.clicked.connect(self._pick_log_dir)
        log_row = QWidget()
        lr = QHBoxLayout(log_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.addWidget(self.log_dir, 1)
        lr.addWidget(pick)
        form.addRow(tr("Session log"), self.log_all)
        form.addRow("", self.log_stamp)
        form.addRow(tr("Log folder"), log_row)
        # server disk space (read from numbers the server already keeps; nothing is scanned)
        self.disk_show = QCheckBox(tr("Show server disk space in the file explorer"))
        self.disk_show.setChecked(bool(settings.get("disk_show", True)))
        self.disk_banner = QCheckBox(tr("Warn at the top of the session when space is low"))
        self.disk_banner.setChecked(bool(settings.get("disk_banner", True)))
        self.disk_card = QCheckBox(tr("Show the last checked value on host cards"))
        self.disk_card.setChecked(bool(settings.get("disk_card", True)))
        self.disk_card.setToolTip(tr("Kept on this PC from your last connection; the server is not asked again."))
        self.disk_warn = QSpinBox()
        self.disk_warn.setRange(1, 50)
        self.disk_warn.setSuffix(" %")
        self.disk_crit = QSpinBox()
        self.disk_crit.setRange(0, 50)
        self.disk_crit.setSuffix(" %")
        from .diskui import thresholds
        warn, crit = thresholds(settings)
        self.disk_warn.setValue(max(1, int(round(warn))))
        self.disk_crit.setValue(int(round(crit)))
        self.disk_warn.valueChanged.connect(lambda w: self.disk_crit.setMaximum(w))
        self.disk_crit.setMaximum(self.disk_warn.value())
        level_row = QWidget()
        lv = QHBoxLayout(level_row)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel(tr("Warning below")))
        lv.addWidget(self.disk_warn)
        lv.addSpacing(10)
        lv.addWidget(QLabel(tr("Critical below")))
        lv.addWidget(self.disk_crit)
        lv.addStretch(1)
        level_row.setToolTip(tr("Free space left on a disk. Orange below the warning level, red below the critical level."))
        self.disk_show.toggled.connect(level_row.setEnabled)
        self.disk_show.toggled.connect(self.disk_banner.setEnabled)
        self.disk_show.toggled.connect(self.disk_card.setEnabled)
        level_row.setEnabled(self.disk_show.isChecked())
        self.disk_banner.setEnabled(self.disk_show.isChecked())
        self.disk_card.setEnabled(self.disk_show.isChecked())
        # large downloads: ask first above this size / file count (0 = never ask)
        from .explorer import confirm_limits
        max_bytes, max_files = confirm_limits(settings)
        self.dl_gb = QSpinBox()
        self.dl_gb.setRange(0, 100000)
        self.dl_gb.setSuffix(" GB")
        self.dl_gb.setValue(round(max_bytes / (1 << 30)))
        self.dl_files = QSpinBox()
        self.dl_files.setRange(0, 10000000)
        self.dl_files.setSingleStep(1000)
        self.dl_files.setGroupSeparatorShown(True)
        self.dl_files.setValue(max_files)
        dl_row = QWidget()
        dr = QHBoxLayout(dl_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.addWidget(self.dl_gb)
        dr.addWidget(QLabel(tr("or")))
        dr.addWidget(self.dl_files)
        dr.addWidget(QLabel(tr("files")))
        dr.addStretch(1)
        dl_row.setToolTip(tr("Folder downloads bigger than this ask before going on. 0 = never ask."))
        form.addRow(tr("Ask before downloading over"), dl_row)
        self.card_last = QCheckBox(tr("Show when each host was last connected on its card"))
        self.card_last.setChecked(bool(settings.get("card_last_connected", True)))
        form.addRow(tr("Host cards"), self.card_last)
        form.addRow(tr("Disk space"), self.disk_show)
        form.addRow("", level_row)
        form.addRow("", self.disk_banner)
        form.addRow("", self.disk_card)
        if parent is not None and hasattr(parent, "open_vault_settings"):
            mp = QPushButton(tr("Master password…"))
            mp.clicked.connect(parent.open_vault_settings)
            form.addRow(tr("Security"), mp)
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

    def _edit_highlights(self):
        from .highlights import HighlightDialog
        d = HighlightDialog(self._hl_enabled, self._hl_rules, self)
        if d.exec():
            self._hl_enabled = d.enabled.isChecked()
            self._hl_rules = d.rules()

    def _pick_log_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Log folder"), self.log_dir.text())
        if d:
            self.log_dir.setText(d)

    def _fill_schemes(self, current: str):
        self.scheme.clear()
        self.scheme.addItem(tr("Default"), "")
        for name in sorted(self._settings.get("color_schemes") or {}, key=str.lower):
            self.scheme.addItem(name, name)
        self.scheme.setCurrentIndex(max(0, self.scheme.findData(current)))

    def _import_scheme(self):
        from . import itermimport
        path, _ = QFileDialog.getOpenFileName(self, tr("Select an iTerm2 color scheme"), "",
                                              tr("iTerm2 color schemes (*.itermcolors)") + ";;" + tr("All files (*)"))
        if not path:
            return
        scheme = itermimport.load_itermcolors(path)
        if scheme is None:
            QMessageBox.warning(self, tr("Terminal colors"), tr("This is not an iTerm2 color scheme."))
            return
        self._settings.setdefault("color_schemes", {})[scheme["name"]] = scheme
        self._fill_schemes(scheme["name"])

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
            "terminal_reflow": self.reflow.isChecked(),
            "terminal_scheme": self.scheme.currentData() or "",
            "highlight_enabled": self._hl_enabled,
            "highlight_rules": self._hl_rules,
            "disk_show": self.disk_show.isChecked(),
            "disk_banner": self.disk_banner.isChecked(),
            "disk_card": self.disk_card.isChecked(),
            "card_last_connected": self.card_last.isChecked(),
            "download_confirm_gb": self.dl_gb.value(),
            "download_confirm_files": self.dl_files.value(),
            "disk_warn_pct": self.disk_warn.value(),
            "disk_crit_pct": min(self.disk_crit.value(), self.disk_warn.value()),
            "log_sessions": self.log_all.isChecked(),
            "log_timestamps": self.log_stamp.isChecked(),
            "log_dir": self.log_dir.text().strip(),
        }
