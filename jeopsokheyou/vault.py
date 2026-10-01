# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Optional master password ("local vault") for saved passwords and key passphrases.

Off by default: secrets are then protected by the OS (Windows DPAPI / macOS Keychain) as before.
When turned on, every secret is encrypted with a random data key (AES-256-GCM). That data key is
stored twice in vault.json: wrapped with a key derived from the master password, and wrapped with a
key derived from a one-time recovery key (both with scrypt). Only secrets are locked — the session
list stays readable, so losing both the password and the recovery key only costs the saved passwords.

There is no other way in: without the master password or the recovery key the secrets cannot be decrypted.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
from typing import Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import paths

TOKEN_PREFIX = "vault:"
VERSION = 1
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
MIN_PASSWORD = 8
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I
RECOVERY_LEN = 24


def vault_file():
    return paths.app_data_dir() / "vault.json"


_dek: bytes | None = None
_unlocked_at = 0.0
# Set by the UI: called when a secret is needed while locked; returns True once unlocked.
request_unlock: Callable[[], bool] | None = None


class VaultError(Exception):
    pass


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _derive(secret: str, salt: bytes, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(secret.encode("utf-8"))


def _wrap(kek: bytes, dek: bytes) -> str:
    nonce = os.urandom(12)
    return _b64(nonce + AESGCM(kek).encrypt(nonce, dek, b"jeopsokheyou-vault-key"))


def _unwrap(kek: bytes, blob: str) -> bytes:
    raw = _unb64(blob)
    return AESGCM(kek).decrypt(raw[:12], raw[12:], b"jeopsokheyou-vault-key")


def normalize_recovery(text: str) -> str:
    return "".join(c for c in text.upper() if c.isalnum())


def format_recovery(key: str) -> str:
    return "-".join(key[i:i + 4] for i in range(0, len(key), 4))


def _read() -> dict | None:
    try:
        data = json.loads(vault_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("version") == VERSION else None
    except (OSError, ValueError):
        return None


def _write(data: dict) -> None:
    f = vault_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(f)


# ------------------------------------------------------------------ state
def enabled() -> bool:
    return _read() is not None


def unlocked() -> bool:
    return _dek is not None


def lock() -> None:
    global _dek
    _dek = None


def unlocked_for() -> float:
    return time.monotonic() - _unlocked_at if _dek else 0.0


def _set_dek(dek: bytes) -> None:
    global _dek, _unlocked_at
    _dek = dek
    _unlocked_at = time.monotonic()


def create(password: str) -> str:
    """Turn the vault on (unlocked). Returns the recovery key to show the user once.
    The caller re-encrypts the existing secrets afterwards."""
    if len(password) < MIN_PASSWORD:
        raise VaultError("too-short")
    dek = os.urandom(32)
    recovery = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LEN))
    salt_pw, salt_rec = os.urandom(16), os.urandom(16)
    _write({
        "version": VERSION,
        "kdf": {"name": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P},
        "password": {"salt": _b64(salt_pw), "key": _wrap(_derive(password, salt_pw), dek)},
        "recovery": {"salt": _b64(salt_rec), "key": _wrap(_derive(recovery, salt_rec), dek)},
    })
    _set_dek(dek)
    return format_recovery(recovery)


def _try(data: dict, slot: str, secret: str) -> bytes | None:
    k = data.get("kdf", {})
    try:
        kek = _derive(secret, _unb64(data[slot]["salt"]), k.get("n", SCRYPT_N), k.get("r", SCRYPT_R), k.get("p", SCRYPT_P))
        return _unwrap(kek, data[slot]["key"])
    except (InvalidTag, KeyError, ValueError, TypeError):
        return None


def unlock(password: str) -> bool:
    """Unlock with the master password."""
    data = _read()
    dek = _try(data, "password", password) if data and password else None
    if dek:
        _set_dek(dek)
    return dek is not None


def unlock_with_recovery(recovery: str) -> bool:
    data = _read()
    key = normalize_recovery(recovery)
    dek = _try(data, "recovery", key) if data and key else None
    if dek:
        _set_dek(dek)
    return dek is not None


def change_password(new_password: str) -> None:
    """Set a new master password (must be unlocked). The recovery key keeps working."""
    if _dek is None:
        raise VaultError("locked")
    if len(new_password) < MIN_PASSWORD:
        raise VaultError("too-short")
    data = _read()
    salt = os.urandom(16)
    data["password"] = {"salt": _b64(salt), "key": _wrap(_derive(new_password, salt), _dek)}
    _write(data)


def remove() -> None:
    """Delete vault.json and forget the key (turning the vault off or resetting it)."""
    lock()
    try:
        vault_file().unlink()
    except FileNotFoundError:
        pass


# ------------------------------------------------------------------ secrets
def _ensure_unlocked() -> bool:
    if _dek is None and request_unlock is not None:
        try:
            request_unlock()
        except Exception:
            pass
    return _dek is not None


def encrypt(name: str, value: str) -> str:
    """Token for sessions.json ("" when the vault is locked and stays locked)."""
    if not value:
        return ""
    if not _ensure_unlocked():
        return ""
    nonce = os.urandom(12)
    return TOKEN_PREFIX + _b64(nonce + AESGCM(_dek).encrypt(nonce, value.encode("utf-8"), name.encode("utf-8")))


def decrypt(name: str, token: str) -> str:
    if not token.startswith(TOKEN_PREFIX) or not _ensure_unlocked():
        return ""
    try:
        raw = _unb64(token[len(TOKEN_PREFIX):])
        return AESGCM(_dek).decrypt(raw[:12], raw[12:], name.encode("utf-8")).decode("utf-8")
    except (InvalidTag, ValueError):
        return ""
