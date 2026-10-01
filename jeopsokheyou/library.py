# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Small stores behind the home screen: snippets, connection history, known hosts and SSH keys (no Qt here)."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import paramiko

from . import config

SNIPPETS_FILE = config.app_dir() / "snippets.json"
HISTORY_FILE = config.app_dir() / "history.json"
HISTORY_LIMIT = 300


def _load_list(path: Path, key: str) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get(key, [])
        return [x for x in items if isinstance(x, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def _save_list(path: Path, key: str, items: list) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({key: items}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------------ snippets
@dataclass
class Snippet:
    name: str = ""
    command: str = ""
    run: bool = False          # press Enter after pasting
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def from_dict(cls, d: dict) -> "Snippet":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def text_to_send(self) -> str:
        """Terminal input: line breaks become Enter; a final Enter only when ``run`` is set."""
        body = self.command.replace("\r\n", "\n").rstrip("\n").replace("\n", "\r")
        return body + ("\r" if self.run else "")


class SnippetStore:
    def __init__(self, path: Path = SNIPPETS_FILE):
        self.path = path
        self.snippets = [Snippet.from_dict(d) for d in _load_list(path, "snippets")]

    def save(self) -> None:
        _save_list(self.path, "snippets", [asdict(s) for s in self.snippets])

    def upsert(self, s: Snippet) -> None:
        for i, cur in enumerate(self.snippets):
            if cur.id == s.id:
                self.snippets[i] = s
                break
        else:
            self.snippets.append(s)
        self.save()

    def remove(self, sid: str) -> None:
        self.snippets = [s for s in self.snippets if s.id != sid]
        self.save()


# ------------------------------------------------------------------ history
def load_history(path: Path = HISTORY_FILE) -> list[dict]:
    """Newest first."""
    return _load_list(path, "history")


def add_history(s: config.Session, path: Path = HISTORY_FILE) -> None:
    items = load_history(path)
    items.insert(0, {"time": time.time(), "session_id": s.id, "title": s.title(),
                     "user": s.user, "host": s.host, "port": int(s.port or 22)})
    _save_list(path, "history", items[:HISTORY_LIMIT])


def clear_history(path: Path = HISTORY_FILE) -> None:
    _save_list(path, "history", [])


# ------------------------------------------------------------------ known hosts
def known_hosts(path: Path | None = None) -> list[dict]:
    path = path or config.KNOWN_HOSTS_FILE
    if not path.exists():
        return []
    hk = paramiko.HostKeys()
    try:
        hk.load(str(path))
    except Exception:
        return []
    out = []
    for host in hk.keys():
        for ktype, key in hk[host].items():
            out.append({"host": host, "type": ktype, "fingerprint": key.fingerprint,
                        "hashed": host.startswith("|1|")})
    return sorted(out, key=lambda x: x["host"].lower())


def forget_known_host(host: str, ktype: str, path: Path | None = None) -> bool:
    path = path or config.KNOWN_HOSTS_FILE
    hk = paramiko.HostKeys()
    try:
        hk.load(str(path))
        sub = hk[host]
        del sub[ktype]
        if not len(sub):
            del hk[host]
        hk.save(str(path))
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ SSH keys
SSH_DIR = Path.home() / ".ssh"
KEY_NAMES = ("id_ed25519", "id_ecdsa", "id_rsa", "id_dsa")


def key_files(sessions: list[config.Session]) -> list[dict]:
    """Private keys in ~/.ssh plus any key file a session uses."""
    paths: dict[str, Path] = {}
    if SSH_DIR.is_dir():
        for f in sorted(SSH_DIR.iterdir()):
            if f.is_file() and not f.suffix and (f.name.startswith("id_") or (f.with_suffix(".pub")).exists()) \
                    and f.name not in ("config", "known_hosts", "authorized_keys"):
                paths[str(f).lower()] = f
    for s in sessions:
        if s.key_path:
            paths.setdefault(str(Path(s.key_path)).lower(), Path(s.key_path))
    out = []
    for p in paths.values():
        used = [s.title() for s in sessions if s.key_path and Path(s.key_path) == p]
        out.append({"path": p, "name": p.name, "exists": p.exists(), "type": key_type(p), "used_by": used})
    return out


def key_type(p: Path) -> str:
    pub = Path(str(p) + ".pub")
    try:
        if pub.exists():
            return pub.read_text(encoding="utf-8", errors="replace").split()[0]
        head = p.read_text(encoding="utf-8", errors="replace")[:80]
    except (OSError, IndexError):
        return ""
    if "OPENSSH PRIVATE KEY" in head:
        return "openssh"
    if "RSA PRIVATE KEY" in head:
        return "ssh-rsa"
    if "PuTTY-User-Key-File" in head:
        return "ppk"
    return ""


def public_key(p: Path, passphrase: str = "") -> str:
    """OpenSSH public key line for a private key (from the .pub file when present)."""
    pub = Path(str(p) + ".pub")
    if pub.exists():
        return pub.read_text(encoding="utf-8").strip()
    key = paramiko.PKey.from_path(str(p), password=passphrase.encode("utf-8") if passphrase else None)
    return f"{key.get_name()} {key.get_base64()}"


def generate_ed25519(path: Path, passphrase: str = "", comment: str = "") -> str:
    """Write a new ed25519 key pair (OpenSSH format) to path / path.pub. Returns the public key line.
    Never overwrites an existing file."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    pub_path = Path(str(path) + ".pub")
    if path.exists() or pub_path.exists():
        raise FileExistsError(str(path))
    key = Ed25519PrivateKey.generate()
    enc = serialization.BestAvailableEncryption(passphrase.encode("utf-8")) if passphrase \
        else serialization.NoEncryption()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, enc)
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    line = public.decode("ascii") + (f" {comment}" if comment else "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(private)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    pub_path.write_text(line + "\n", encoding="utf-8")
    return line
