# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""App settings / session store.

- Session list: %APPDATA%/JeopsokHeyou/sessions.json
- Passwords/passphrases: stored encrypted with Windows DPAPI (current user account only) or the macOS
  Keychain — or, when the optional master password is on, with the local vault (vault.py)
- known_hosts: %APPDATA%/JeopsokHeyou/known_hosts
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths, vault


def app_dir() -> Path:
    return paths.app_data_dir()


SESSIONS_FILE = app_dir() / "sessions.json"
SETTINGS_FILE = app_dir() / "settings.json"
KNOWN_HOSTS_FILE = app_dir() / "known_hosts"


# ---------------------------------------------------------------- DPAPI
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def protect(text: str) -> str:
    """Encrypt a string with DPAPI and return it as base64. Not stored on non-Windows."""
    if not text:
        return ""
    if sys.platform != "win32":
        return ""
    out = _Blob()
    src = _blob(text.encode("utf-8"))
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)
    ):
        return ""
    try:
        return base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def unprotect(token: str) -> str:
    if not token or sys.platform != "win32":
        return ""
    try:
        raw = base64.b64decode(token)
    except Exception:
        return ""
    out = _Blob()
    src = _blob(raw)
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)
    ):
        return ""
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# ---------------------------------------------------------------- Keychain (macOS)
KEYCHAIN_SERVICE = "JeopsokHeyou"
KEYCHAIN_TOKEN = "keychain"   # stored in *_enc when the secret lives in the macOS Keychain


def _keychain_set(account: str, value: str) -> bool:
    # The secret is hex-encoded and sent through stdin of `security -i`, so it never
    # appears in a process's command line and needs no shell quoting.
    command = (f"add-generic-password -U -a {account} -s {KEYCHAIN_SERVICE} "
               f"-l {KEYCHAIN_SERVICE} -w {value.encode('utf-8').hex()}\n")
    try:
        r = subprocess.run(["security", "-i"], input=command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and "error" not in (r.stdout + r.stderr).lower()


def _keychain_get(account: str) -> str:
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", account, "-s", KEYCHAIN_SERVICE, "-w"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return ""
        return bytes.fromhex(r.stdout.strip()).decode("utf-8")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""


def _keychain_delete(account: str) -> None:
    try:
        subprocess.run(["security", "delete-generic-password", "-a", account, "-s", KEYCHAIN_SERVICE],
                       capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass


def store_secret(key: str, value: str) -> str:
    """Store a secret and return the token to keep in sessions.json ("" = not stored).
    With the master password on: a vault token. Otherwise Windows: the DPAPI-encrypted value itself;
    macOS: a marker, the value goes to the Keychain."""
    if vault.enabled():
        if paths.IS_MAC:
            _keychain_delete(key)       # never leave an old copy behind in the Keychain
        return vault.encrypt(key, value)
    return _os_store_secret(key, value)


def _os_store_secret(key: str, value: str) -> str:
    if paths.IS_MAC:
        if not value:
            _keychain_delete(key)
            return ""
        return KEYCHAIN_TOKEN if _keychain_set(key, value) else ""
    return protect(value)


def load_secret(key: str, token: str) -> str:
    if not token:
        return ""
    if token.startswith(vault.TOKEN_PREFIX):
        return vault.decrypt(key, token)
    if token == KEYCHAIN_TOKEN:
        return _keychain_get(key) if paths.IS_MAC else ""
    return unprotect(token)


def delete_secret(key: str, token: str) -> None:
    if token == KEYCHAIN_TOKEN and paths.IS_MAC:
        _keychain_delete(key)


# ---------------------------------------------------------------- Session
@dataclass
class Session:
    name: str = ""
    host: str = ""
    port: int = 22
    user: str = ""
    group: str = ""
    auth: str = "password"  # password | key
    password_enc: str = ""
    key_path: str = ""
    passphrase_enc: str = ""
    init_dir: str = ""
    follow_cwd: bool = True
    encoding: str = "utf-8"
    idle_minutes: int = -1   # auto disconnect: -1 use global setting, 0 disabled, N minutes
    jump: str = ""            # id of the session to connect through (ProxyJump)
    forwards: list = field(default_factory=list)   # port forwards opened with the session (forwarding.Forward dicts)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def password(self) -> str:
        return load_secret(f"{self.id}.password", self.password_enc)

    @password.setter
    def password(self, value: str) -> None:
        self.password_enc = store_secret(f"{self.id}.password", value)

    @property
    def passphrase(self) -> str:
        return load_secret(f"{self.id}.passphrase", self.passphrase_enc)

    @passphrase.setter
    def passphrase(self, value: str) -> None:
        self.passphrase_enc = store_secret(f"{self.id}.passphrase", value)

    def forget_secrets(self) -> None:
        """Remove secrets kept outside sessions.json (macOS Keychain)."""
        delete_secret(f"{self.id}.password", self.password_enc)
        delete_secret(f"{self.id}.passphrase", self.passphrase_enc)

    def title(self) -> str:
        return self.name or f"{self.user}@{self.host}"

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if isinstance(known.get("forwards"), list):
            known["forwards"] = [dict(f) for f in known["forwards"] if isinstance(f, dict)]   # never share with the source
        else:
            known.pop("forwards", None)
        return cls(**known)

    @classmethod
    def parse_quick(cls, text: str) -> "Session | None":
        """Parse a quick-connect string of the form 'user@host:port'."""
        text = text.strip()
        if not text:
            return None
        user = ""
        if "@" in text:
            user, text = text.rsplit("@", 1)
        port = 22
        if text.count(":") == 1:
            host, p = text.split(":")
            if p.isdigit():
                port = int(p)
            text = host
        return cls(name="", host=text, port=port, user=user)


GROUP_SEP = " / "   # subgroups are stored as paths, e.g. "Production / DB" (also how MobaXterm folders import)


def group_parent(name: str) -> str:
    return name.rsplit(GROUP_SEP, 1)[0] if GROUP_SEP in name else ""


def group_leaf(name: str) -> str:
    return name.rsplit(GROUP_SEP, 1)[-1]


def in_group(group: str, ancestor: str) -> bool:
    """True when ``group`` is ``ancestor`` or one of its subgroups."""
    return group == ancestor or group.startswith(ancestor + GROUP_SEP)


class SessionStore:
    def __init__(self, path: Path = SESSIONS_FILE):
        self.path = path
        self.sessions: list[Session] = []
        self._groups: list[str] = []   # groups kept even when empty
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.sessions, self._groups = [], []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.sessions = [Session.from_dict(d) for d in data.get("sessions", [])]
            self._groups = [g for g in data.get("groups", []) if isinstance(g, str) and g]
        except Exception:
            self.sessions, self._groups = [], []

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"groups": self.groups(), "sessions": [asdict(s) for s in self.sessions]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # --- groups
    def groups(self) -> list[str]:
        names = list(self._groups)
        for s in self.sessions:
            if s.group and s.group not in names:
                names.append(s.group)
        return sorted(names, key=str.lower)

    def add_group(self, name: str) -> bool:
        name = name.strip()
        if not name or name in self.groups():
            return False
        self._groups.append(name)
        self.save()
        return True

    def rename_group(self, old: str, new: str) -> bool:
        new = new.strip()
        if not new or new == old or new in self.groups():
            return False
        def renamed(g: str) -> str:   # the group itself and its subgroups
            return new + g[len(old):] if in_group(g, old) else g
        self._groups = list(dict.fromkeys(renamed(g) for g in self._groups))
        if new not in self._groups:
            self._groups.append(new)
        for s in self.sessions:
            s.group = renamed(s.group)
        self.save()
        return True

    def remove_group(self, name: str) -> int:
        """Delete a group and its subgroups. Their sessions are not deleted but moved up to the parent group
        (the top level for a top-level group). Returns the number moved."""
        parent = group_parent(name)
        self._groups = [g for g in self._groups if not in_group(g, name)]
        moved = 0
        for s in self.sessions:
            if in_group(s.group, name):
                s.group = parent
                moved += 1
        self.save()
        return moved

    def move_sessions(self, ids: list[str], group: str) -> int:
        """Move sessions into a group (group="" means no group). Emptied source groups stay in the list."""
        n = 0
        for s in self.sessions:
            if s.id in ids and s.group != group:
                if s.group and s.group not in self._groups:
                    self._groups.append(s.group)
                s.group = group
                n += 1
        if group and group not in self._groups:
            self._groups.append(group)
        self.save()
        return n

    def upsert(self, s: Session) -> None:
        for i, cur in enumerate(self.sessions):
            if cur.id == s.id:
                self.sessions[i] = s
                break
        else:
            self.sessions.append(s)
        self.save()

    def remove(self, sid: str) -> None:
        for s in self.sessions:
            if s.id == sid:
                s.forget_secrets()
        self.sessions = [s for s in self.sessions if s.id != sid]
        for s in self.sessions:
            if s.jump == sid:
                s.jump = ""
        self.save()

    def get(self, sid: str) -> Session | None:
        return next((s for s in self.sessions if s.id == sid), None)

    # --- master password (vault.py): move secrets between the OS store and the vault
    SECRET_FIELDS = ("password", "passphrase")

    def move_secrets_to_vault(self) -> int:
        """After turning the vault on: re-encrypt every saved secret with it. Returns the number moved."""
        n = 0
        for s in self.sessions:
            for f in self.SECRET_FIELDS:
                token, key = getattr(s, f + "_enc"), f"{s.id}.{f}"
                if token and not token.startswith(vault.TOKEN_PREFIX):
                    plain = load_secret(key, token)
                    delete_secret(key, token)
                    setattr(s, f + "_enc", vault.encrypt(key, plain) if plain else "")
                    n += 1
        self.save()
        return n

    def move_secrets_out_of_vault(self) -> int:
        """Before turning the vault off (unlocked): store every secret with the OS again."""
        n = 0
        for s in self.sessions:
            for f in self.SECRET_FIELDS:
                token, key = getattr(s, f + "_enc"), f"{s.id}.{f}"
                if token.startswith(vault.TOKEN_PREFIX):
                    plain = vault.decrypt(key, token)
                    setattr(s, f + "_enc", _os_store_secret(key, plain) if plain else "")
                    n += 1
        self.save()
        return n

    def drop_vault_secrets(self) -> int:
        """Vault reset (password and recovery key lost): forget the secrets it held; sessions stay."""
        n = 0
        for s in self.sessions:
            for f in self.SECRET_FIELDS:
                if getattr(s, f + "_enc").startswith(vault.TOKEN_PREFIX):
                    setattr(s, f + "_enc", "")
                    n += 1
        self.save()
        return n

    def jump_chain(self, s: Session) -> list[Session]:
        """Jump hosts to go through for a session, outermost first. Stops at loops and missing sessions."""
        chain: list[Session] = []
        seen = {s.id}
        cur = s
        while cur.jump:
            j = self.get(cur.jump)
            if j is None or j.id in seen:
                break
            seen.add(j.id)
            chain.insert(0, j)
            cur = j
        return chain


def _putty_session(name: str, values: dict) -> Session | None:
    if str(values.get("Protocol", "ssh")).lower() != "ssh":
        return None
    host = str(values.get("HostName") or "")
    if not host:
        return None
    user = str(values.get("UserName") or "")
    if "@" in host:
        user, host = host.rsplit("@", 1)
    key_file = str(values.get("PublicKeyFile") or "")
    try:
        port = int(values.get("PortNumber") or 22)
    except ValueError:
        port = 22
    return Session(name=name, host=host, port=port, user=user, group="PuTTY",
                   auth="key" if key_file else "password", key_path=key_file)


def _import_putty_files() -> list[Session]:
    """PuTTY for macOS/Linux: one file per session, lines of the form 'Key\\Value\\'."""
    from urllib.parse import unquote
    folder = Path.home() / ".putty" / "sessions"
    result: list[Session] = []
    if not folder.is_dir():
        return result
    for f in sorted(folder.iterdir()):
        values = {}
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if "\\" in line:
                    k, v = line.split("\\", 1)
                    values[k] = v[:-1] if v.endswith("\\") else v
        except OSError:
            continue
        s = _putty_session(unquote(f.name), values)
        if s:
            result.append(s)
    return result


def import_putty_sessions() -> list[Session]:
    """Read PuTTY sessions (Windows registry, or ~/.putty/sessions elsewhere); SSH only."""
    if sys.platform != "win32":
        return _import_putty_files()
    import winreg
    from urllib.parse import unquote

    result: list[Session] = []
    root = r"Software\SimonTatham\PuTTY\Sessions"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, root)
    except OSError:
        return result
    with key:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(key, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(key, sub) as sk:
                    def val(name, default=""):
                        try:
                            return winreg.QueryValueEx(sk, name)[0]
                        except OSError:
                            return default
                    if str(val("Protocol", "ssh")).lower() != "ssh":
                        continue
                    host = str(val("HostName"))
                    if not host:
                        continue
                    user = str(val("UserName"))
                    if "@" in host:
                        user, host = host.rsplit("@", 1)
                    key_file = str(val("PublicKeyFile"))
                    result.append(Session(
                        name=unquote(sub),
                        host=host,
                        port=int(val("PortNumber", 22) or 22),
                        user=user,
                        group="PuTTY",
                        auth="key" if key_file else "password",
                        key_path=key_file,
                    ))
            except Exception:
                continue
    return result


TABBY_CONFIG = paths.tabby_config()


def import_tabby_sessions(path: Path = TABBY_CONFIG) -> list[Session]:
    """Convert SSH profiles in Tabby's config.yaml to a Session list.

    - Profiles without a user default to root (like Tabby); missing port defaults to 22
    - Groups are converted from id → name
    - Passwords live in Tabby's vault/OS credentials and are not imported
    """
    if not path.exists():
        return []
    import yaml  # optional dependency: only used for Tabby import

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    groups = {g.get("id"): g.get("name", "") for g in (data.get("groups") or []) if isinstance(g, dict)}
    result: list[Session] = []
    for p in data.get("profiles") or []:
        if not isinstance(p, dict) or p.get("type") != "ssh":
            continue
        opt = p.get("options") or {}
        host = str(opt.get("host") or "").strip()
        if not host:
            continue
        keys = [str(k) for k in (opt.get("privateKeys") or []) if k]
        key_path = keys[0].removeprefix("file://") if keys else ""
        gid = str(p.get("group") or "")
        result.append(Session(
            name=str(p.get("name") or host),
            host=host,
            port=int(opt.get("port") or 22),
            user=str(opt.get("user") or "root"),
            group=groups.get(gid) or ("" if len(gid) == 36 else gid) or "Tabby",
            auth="key" if key_path else "password",
            key_path=key_path,
        ))
    return result


# ---------------------------------------------------------------- MobaXterm
def mobaxterm_default_files() -> list[Path]:
    """Where MobaXterm (installer edition) usually keeps its settings; the portable edition keeps
    MobaXterm.ini next to its .exe, and exports are *.mxtsessions — those are picked by the user."""
    home = Path.home()
    candidates = [home / "Documents" / "MobaXterm" / "MobaXterm.ini",
                  home / "OneDrive" / "Documents" / "MobaXterm" / "MobaXterm.ini"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "MobaXterm" / "MobaXterm.ini")
    return [p for p in candidates if p.is_file()]


CJK_CODEPAGES = ("cp949", "cp932", "cp936", "cp950")


def _read_text_any(path: Path) -> str:
    """MobaXterm writes its .ini in the ANSI code page of the PC that saved it; exports may be UTF-8.

    The file may come from a PC with another language than this one, so after UTF-8 the Korean,
    Japanese and Chinese code pages are tried (strictly — Western text with accents does not decode
    in them) before falling back to the Western code page.
    """
    import locale
    raw = path.read_bytes()
    system = (locale.getpreferredencoding(False) or "").lower()
    order = ["utf-8-sig"] + ([system] if system in CJK_CODEPAGES else []) + list(CJK_CODEPAGES) + ["cp1252"]
    for enc in dict.fromkeys(order):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")


def _moba_key_path(fields: list[str]) -> str:
    """Pick the private-key path out of a session's %-separated fields (position varies by version)."""
    for f in fields:
        low = f.lower()
        if not f or ("\\" not in f and "/" not in f):
            continue
        if low.endswith((".ppk", ".pem", ".key")) or "id_rsa" in low or "id_ed25519" in low or "id_ecdsa" in low:
            f = f.replace("_ProfileDir_", str(Path.home())).replace("_CurrentDrive_", Path.home().anchor.rstrip("\\/"))
            if not paths.IS_WINDOWS:
                f = f.replace("\\", "/")   # MobaXterm stores Windows-style separators
            return f
    return ""


def import_mobaxterm_sessions(path: Path) -> list[Session]:
    r"""Read SSH sessions from MobaXterm.ini or an exported .mxtsessions file.

    Bookmarks sections look like::

        [Bookmarks_2]
        SubRep=Azure\PRE
        ImgNum=41
        web01=#109#0%web01.example.com%22%admin%%-1%-1%...#MobaFont%10%...#0

    ``#<icon>#<type>%<host>%<port>%<user>%...``; type 0 is SSH. SubRep is the folder, which becomes
    the group. Passwords live in MobaXterm's own encrypted store and are not imported.
    """
    result: list[Session] = []
    try:
        text = _read_text_any(path)
    except OSError:
        return result
    in_bookmarks = False
    group = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_bookmarks = line[1:-1].lower().startswith("bookmarks")
            group = ""
            continue
        if not in_bookmarks or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key == "SubRep":
            group = value.strip().replace("\\", " / ")
            continue
        if key == "ImgNum" or not value.startswith("#"):
            continue
        parts = value.split("#")
        if len(parts) < 3:
            continue
        fields = parts[2].split("%")
        if len(fields) < 4 or fields[0] != "0":      # 0 = SSH; RDP, Telnet, … are skipped
            continue
        host = fields[1].strip()
        if not host:
            continue
        try:
            port = int(fields[2] or 22)
        except ValueError:
            port = 22
        key_path = _moba_key_path(fields[4:])
        result.append(Session(name=key, host=host, port=port, user=fields[3].strip(),
                              group=group or "MobaXterm",
                              auth="key" if key_path else "password", key_path=key_path))
    return result


# ---------------------------------------------------------------- Settings
DEFAULT_SETTINGS = {
    "font_family": "",
    "font_size": 11,
    "scrollback": 5000,
    "download_dir": str(Path.home() / "Downloads"),
    "idle_minutes": 30,      # auto disconnect when idle (0 = disabled)
}


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return s


def save_settings(s: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
