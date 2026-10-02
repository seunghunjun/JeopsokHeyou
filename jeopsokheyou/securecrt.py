# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Import SSH sessions from SecureCRT session files (the user's own Config/Sessions folder).

Each session is a text file ``<name>.ini`` with lines such as ``S:"Hostname"=host`` (string),
``D:"[SSH2] Port"=00000016`` (hex number) and multi-line ``Z:"…"=<count>`` lists. Sub-folders of the
Sessions folder become groups. Passwords are never read.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .config import GROUP_SEP, Session

GROUP = "SecureCRT"
LINE_RE = re.compile(r'^([SDBZ]):"([^"]+)"=(.*)$')
SKIP_FILES = {"__FolderData__.ini"}


def default_dirs() -> list[Path]:
    out = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "VanDyke" / "Config" / "Sessions")
    out.append(Path.home() / "Library" / "Application Support" / "VanDyke" / "SecureCRT" / "Config" / "Sessions")
    return [p for p in out if p.is_dir()]


def _read(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def parse_session_file(path: Path) -> dict:
    """{key: value} of the S:/D: entries (passwords are dropped); Z: lists become lists of their lines."""
    values: dict = {}
    lines = _read(path).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        typ, key, val = m.groups()
        if typ == "Z":                     # multi-line list: <count> lines follow, each starting with a space
            try:
                count = int(val, 16)
            except ValueError:
                count = 0
            values[key] = [ln.strip() for ln in lines[i:i + count]]
            i += count
            continue
        if "password" in key.lower():
            continue
        if typ == "D":
            try:
                val = str(int(val, 16))
            except ValueError:
                continue
        values[key] = val
    return values


def session_from(values: dict, name: str, group: str) -> Session | None:
    proto = values.get("Protocol Name", "SSH2").upper()
    if not proto.startswith("SSH"):
        return None                       # Telnet, Serial, RDP, local shell … are not SSH
    host = values.get("Hostname", "").strip()
    if not host:
        return None
    try:
        port = int(values.get("[SSH2] Port") or values.get("[SSH1] Port") or 22)
    except ValueError:
        port = 22
    key = values.get("Identity Filename V2", "").strip()
    if key.startswith("${VDS_"):           # e.g. ${VDS_USER_DATA_PATH}\Identity — a SecureCRT-managed key
        key = ""
    forwards = _forwards(values.get("Port Forward Table V3"), "L") + \
        _forwards(values.get("Reverse Forward Table V3"), "R")
    return Session(name=name, host=host, port=port, user=values.get("Username", "").strip(), group=group,
                   auth="key" if key else "password", key_path=key, forwards=forwards)


def _forwards(rows, kind: str) -> list[dict]:
    """Rows like '1|name|15432|1|10.0.0.41|5432||' → forward dicts (listen port, destination host and port)."""
    out = []
    for row in rows or []:
        f = row.split("|")
        if len(f) < 6 or not f[2].strip().isdigit() or not f[5].strip().isdigit() or not f[4].strip():
            continue
        out.append({"kind": kind, "bind_host": "localhost" if kind == "R" else "127.0.0.1",
                    "bind_port": int(f[2]), "dest_host": f[4].strip(), "dest_port": int(f[5])})
    return out


def import_securecrt_sessions(folder: Path) -> tuple[list[Session], int]:
    """SSH sessions under a SecureCRT Sessions folder (or a single session file), and how many were skipped."""
    folder = Path(folder)
    files = [folder] if folder.is_file() else sorted(folder.rglob("*.ini"))
    sessions, skipped = [], 0
    by_path: dict[str, Session] = {}       # "Folder/Name" and "Name" → session (for jump hosts)
    jumps: list[tuple[Session, str]] = []
    for f in files:
        if f.name in SKIP_FILES or (f.parent == folder and f.stem.startswith("Default")):
            continue                      # folder metadata and SecureCRT's default-session templates
        try:
            values = parse_session_file(f)
        except OSError:
            skipped += 1
            continue
        rel = f.parent.relative_to(folder) if folder.is_dir() else Path(".")
        group = GROUP_SEP.join(rel.parts) if rel.parts else GROUP
        s = session_from(values, f.stem, group)
        if s is None:
            skipped += 1
            continue
        sessions.append(s)
        rel_name = "/".join(list(rel.parts) + [f.stem])
        by_path[rel_name.lower()] = s
        by_path.setdefault(f.stem.lower(), s)
        firewall = str(values.get("Firewall Name", ""))
        if firewall.lower().startswith("session:"):     # another session used as the jump host
            jumps.append((s, firewall.split(":", 1)[1].strip()))
    for s, target in jumps:
        key = target.replace("\\", "/").strip("/").lower()
        j = by_path.get(key) or by_path.get(key.rsplit("/", 1)[-1])
        if j is not None and j is not s:
            s.jump = j.id
    return sessions, skipped
