# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Import from iTerm2: SSH profiles (preferences plist, Dynamic Profiles or an exported JSON) and
color schemes (.itermcolors).

iTerm2 has no "host" concept — an SSH profile is a profile whose command runs ssh, e.g.
``ssh -p 2222 deploy@192.0.2.10`` ("Custom Command: Yes"), or, since iTerm2 3.5, a profile in SSH mode
("Custom Command: SSH") whose command holds only the ssh arguments. Tags become groups.
"""
from __future__ import annotations

import json
import os
import plistlib
import shlex
from pathlib import Path

from .config import Session
from .sshconfig import parse_forward

GROUP = "iTerm2"
SSH_NAMES = {"ssh", "ssh.exe", "it2ssh"}
OPTS_WITH_ARG = set("BbcDEeFIiJLlmOoPpQRSWw")


def default_files() -> list[Path]:
    home = Path.home()
    out = [home / "Library" / "Preferences" / "com.googlecode.iterm2.plist"]
    dyn = home / "Library" / "Application Support" / "iTerm2" / "DynamicProfiles"
    if dyn.is_dir():
        out += sorted(p for p in dyn.iterdir() if p.is_file())
    return [p for p in out if p.is_file()]


def load_profiles(path: Path) -> list[dict]:
    """Profiles from iTerm2's preferences plist ("New Bookmarks"), a Dynamic Profiles file or an exported JSON."""
    raw = Path(path).read_bytes()
    data = None
    if raw[:6] == b"bplist" or raw.lstrip()[:5] == b"<?xml" or b"<plist" in raw[:200]:
        try:
            data = plistlib.loads(raw)
        except Exception:
            data = None
    if data is None:
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            return []
    if isinstance(data, dict):
        profiles = data.get("New Bookmarks") or data.get("Profiles") or []
        if not profiles and "Name" in data:
            profiles = [data]      # a single exported profile
    elif isinstance(data, list):
        profiles = data
    else:
        profiles = []
    return [p for p in profiles if isinstance(p, dict)]


def ssh_command(profile: dict) -> list[str] | None:
    """The ssh argument list of a profile (without the 'ssh' word), or None when it isn't an SSH profile."""
    mode = str(profile.get("Custom Command", "No"))
    cmd = str(profile.get("Command", "") or "").strip()
    if not cmd:
        return None
    try:
        words = shlex.split(cmd)
    except ValueError:
        return None
    if mode == "SSH":                         # iTerm2 3.5+ SSH profile: the command holds ssh arguments
        return words
    if mode not in ("Yes", "True", "1"):
        return None
    for i, w in enumerate(words):
        if os.path.basename(w) in SSH_NAMES:
            return words[i + 1:]
    return None


def parse_ssh_args(args: list[str]) -> dict | None:
    """ssh arguments → {host, port, user, key_path, jump, forwards}. None when no destination is found."""
    opts = {"port": None, "user": "", "key_path": "", "jump": "", "forwards": []}
    host = ""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            if i < len(args) and not host:
                host = args[i]
            break
        if a.startswith("-") and len(a) > 1:
            flag = a[1]
            if flag in OPTS_WITH_ARG:
                val = a[2:] if len(a) > 2 else (args[i + 1] if i + 1 < len(args) else "")
                i += 1 if len(a) > 2 else 2
                if flag == "p" and val.isdigit():
                    opts["port"] = int(val)
                elif flag == "l":
                    opts["user"] = val
                elif flag == "i":
                    opts["key_path"] = os.path.expanduser(val)
                elif flag == "J":
                    opts["jump"] = val
                elif flag in "LRD":
                    fwd = parse_forward(flag, [val] if flag == "D" else _forward_parts(val))
                    if fwd:
                        opts["forwards"].append(fwd)
                elif flag == "o" and "=" in val:
                    k, v = val.split("=", 1)
                    k = k.strip().lower()
                    if k == "port" and v.strip().isdigit():
                        opts["port"] = int(v)
                    elif k == "user":
                        opts["user"] = v.strip()
                    elif k == "identityfile":
                        opts["key_path"] = os.path.expanduser(v.strip())
                    elif k == "proxyjump":
                        opts["jump"] = v.strip()
                continue
            i += 1            # a flag without a value (-A, -v, -4 ...)
            continue
        if not host:
            host = a
        else:
            break             # the remote command follows — ignored
        i += 1
    if not host:
        return None
    if host.startswith("ssh://"):
        host = host[6:]
    if "@" in host:
        u, host = host.rsplit("@", 1)
        opts["user"] = opts["user"] or u
    if host.count(":") == 1 and host.split(":")[1].isdigit() and opts["port"] is None:
        host, p = host.split(":")
        opts["port"] = int(p)
    opts["host"] = host.strip("[]")
    opts["port"] = opts["port"] or 22
    return opts


def _forward_parts(val: str) -> list[str]:
    """'8080:db:5432' / '127.0.0.1:8080:db:5432' / '[::1]:8080:db:5432' → ssh-config style [listen, dest]."""
    parts, cur, depth = [], "", 0
    for ch in val:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == ":" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    if len(parts) == 3:
        return [parts[0], f"{parts[1]}:{parts[2]}"]
    if len(parts) == 4:
        return [f"{parts[0]}:{parts[1]}", f"{parts[2]}:{parts[3]}"]
    return [val]


def import_iterm_sessions(path: Path) -> tuple[list[Session], int]:
    """SSH sessions from an iTerm2 profile file, and how many profiles were skipped (local shells etc.)."""
    sessions: list[Session] = []
    skipped = 0
    by_alias: dict[str, Session] = {}
    jumps: list[tuple[Session, str]] = []
    for prof in load_profiles(path):
        args = ssh_command(prof)
        info = parse_ssh_args(args) if args is not None else None
        if info is None:
            skipped += 1
            continue
        tags = prof.get("Tags") or []
        group = str(tags[0]) if isinstance(tags, list) and tags else GROUP
        s = Session(name=str(prof.get("Name") or info["host"]), host=info["host"], port=info["port"],
                    user=info["user"], group=group, auth="key" if info["key_path"] else "password",
                    key_path=info["key_path"], forwards=info["forwards"])
        sessions.append(s)
        by_alias[s.host] = s
        by_alias[s.name] = s
        if info["jump"]:
            jumps.append((s, info["jump"]))
    for s, spec in jumps:      # link ProxyJump to an imported session, or add one for the jump host
        hop = spec.split(",")[-1].strip()
        info = parse_ssh_args([hop]) or {}
        target = by_alias.get(hop) or by_alias.get(info.get("host", ""))
        if target is None and info:
            target = Session(name=hop, host=info["host"], port=info["port"], user=info["user"], group=s.group)
            sessions.append(target)
            by_alias[hop] = target
        if target is not None and target is not s:
            s.jump = target.id
    return sessions, skipped


# ------------------------------------------------------------------ color schemes
ANSI_KEYS = [f"Ansi {i} Color" for i in range(16)]


def _hex(d) -> str | None:
    if not isinstance(d, dict):
        return None
    try:
        r, g, b = (float(d.get(k, 0)) for k in ("Red Component", "Green Component", "Blue Component"))
    except (TypeError, ValueError):
        return None
    clamp = lambda v: max(0, min(255, round(v * 255)))   # noqa: E731
    return "#{:02x}{:02x}{:02x}".format(clamp(r), clamp(g), clamp(b))


def load_itermcolors(path: Path) -> dict | None:
    """A .itermcolors file → {"name", "ansi": [16 hex], "fg", "bg", "cursor", "selection"}."""
    try:
        data = plistlib.loads(Path(path).read_bytes())
    except Exception:
        return None
    if not isinstance(data, dict) or not any(k in data for k in ANSI_KEYS):
        return None
    return {
        "name": Path(path).stem,
        "ansi": [_hex(data.get(k)) for k in ANSI_KEYS],
        "fg": _hex(data.get("Foreground Color")),
        "bg": _hex(data.get("Background Color")),
        "cursor": _hex(data.get("Cursor Color")),
        "selection": _hex(data.get("Selection Color")),
    }
