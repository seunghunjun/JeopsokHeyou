# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Import hosts from an OpenSSH client config file (~/.ssh/config).

This is also how Termius hosts are imported: Termius keeps its data in an encrypted database,
but can write it out in this format (``termius export-ssh-config``).

Supported: Host blocks (several aliases per line, wildcards and ``!`` negations for defaults),
Include, HostName (with %h), Port, User, IdentityFile, ProxyJump, LocalForward, RemoteForward and
DynamicForward. Match blocks are skipped. Like ssh itself, the first value found for an option wins.
"""
from __future__ import annotations

import fnmatch
import glob
import os
import re
from pathlib import Path

from .config import Session

GROUP = "SSH config"
MAX_INCLUDE_DEPTH = 16


def default_file() -> Path:
    return Path.home() / ".ssh" / "config"


def _expand(path: str) -> str:
    home = str(Path.home())
    path = path.replace("%d", home).replace("%%", "%")
    return os.path.expanduser(path)


def _tokens(line: str) -> tuple[str, list[str]] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # "Keyword value", "Keyword=value" and "Keyword = value" are all valid
    m = re.match(r"([^\s=]+)(?:\s*=\s*|\s+)?(.*)$", line)
    if not m:
        return None
    key, rest = m.group(1), m.group(2).strip()
    return key.lower(), _split_args(rest)


def _split_args(text: str) -> list[str]:
    """Split like OpenSSH: quotes group words; a backslash only escapes a quote, space or backslash
    (so Windows paths written with backslashes stay intact)."""
    args: list[str] = []
    cur, quote, has = [], "", False
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text) and text[i + 1] in "\"' \\":
            cur.append(text[i + 1])
            has = True
            i += 2
            continue
        if quote:
            if c == quote:
                quote = ""
            else:
                cur.append(c)
        elif c in "\"'":
            quote, has = c, True
        elif c.isspace():
            if has or cur:
                args.append("".join(cur))
            cur, has = [], False
        elif c == "#" and not cur and not has:
            break                      # trailing comment
        else:
            cur.append(c)
        i += 1
    if has or cur:
        args.append("".join(cur))
    return args


def _read_lines(path: Path, depth: int = 0, seen: set | None = None) -> list[tuple[str, list[str]]]:
    """Read a config file with Include directives expanded in place."""
    seen = seen if seen is not None else set()
    try:
        real = path.resolve()
    except OSError:
        return []
    if depth > MAX_INCLUDE_DEPTH or real in seen:
        return []
    seen.add(real)
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    out: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        tok = _tokens(raw)
        if not tok:
            continue
        key, args = tok
        if key == "include":
            for pattern in args:
                p = _expand(pattern)
                if not os.path.isabs(p):
                    p = str(Path.home() / ".ssh" / p)   # relative includes are relative to ~/.ssh
                for f in sorted(glob.glob(p)):
                    out.extend(_read_lines(Path(f), depth + 1, seen))
            continue
        out.append((key, args))
    return out


def _is_concrete(pattern: str) -> bool:
    return not any(c in pattern for c in "*?!")


def _matches(patterns: list[str], alias: str) -> bool:
    hit = False
    for p in patterns:
        if p.startswith("!"):
            if fnmatch.fnmatchcase(alias.lower(), p[1:].lower()):
                return False
        elif fnmatch.fnmatchcase(alias.lower(), p.lower()):
            hit = True
    return hit


def _split_hostport(text: str) -> tuple[str, int] | None:
    """'host:port', 'host/port' or '[v6]:port' → (host, port)."""
    text = text.strip()
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = rest.lstrip(":/")
    elif "/" in text:
        host, _, port = text.rpartition("/")
    else:
        host, _, port = text.rpartition(":")
    if not port.isdigit():
        return None
    return host, int(port)


def parse_forward(kind: str, args: list[str]) -> dict | None:
    """Turn LocalForward/RemoteForward/DynamicForward arguments into a forward dict."""
    if not args:
        return None
    listen = args[0]
    if listen.isdigit():
        bind_host, bind_port = "", int(listen)
    else:
        hp = _split_hostport(listen)
        if not hp:
            return None      # e.g. a Unix socket path
        bind_host, bind_port = hp
        if bind_host == "*":
            bind_host = "0.0.0.0"
    fwd = {"kind": kind, "bind_host": bind_host or ("localhost" if kind == "R" else "127.0.0.1"),
           "bind_port": bind_port, "dest_host": "", "dest_port": 0}
    if kind == "D":
        return fwd
    if len(args) < 2:
        return None          # "RemoteForward port" alone (remote SOCKS) is not supported
    dest = _split_hostport(args[1])
    if not dest:
        return None
    fwd["dest_host"], fwd["dest_port"] = dest
    return fwd


def _parse_jump_hop(text: str) -> tuple[str, str, int]:
    """'user@host:port' → (user, host, port)."""
    user = ""
    if "@" in text:
        user, text = text.rsplit("@", 1)
    hp = _split_hostport(text) if (":" in text or text.startswith("[")) else None
    host, port = hp if hp else (text.strip("[]"), 22)
    return user, host, port


def import_ssh_config(path: Path | None = None) -> list[Session]:
    """Read concrete hosts from an ssh config file. Jump hosts are linked through Session.jump."""
    path = path or default_file()
    blocks: list[tuple[list[str] | None, list[tuple[str, list[str]]]]] = [(["*"], [])]   # lines before any Host
    aliases: list[str] = []
    for key, args in _read_lines(path):
        if key == "host":
            blocks.append((args, []))
            aliases.extend(a for a in args if _is_concrete(a) and a not in aliases)
        elif key == "match":
            blocks.append((None, []))     # conditions are not evaluated — skip the whole block
        else:
            blocks[-1][1].append((key, args))

    def options(alias: str) -> dict:
        opts: dict = {"forwards": [], "identityfile": []}
        for patterns, lines in blocks:
            if patterns is None or not _matches(patterns, alias):
                continue
            for key, args in lines:
                if not args:
                    continue
                if key in ("localforward", "remoteforward", "dynamicforward"):
                    fwd = parse_forward({"localforward": "L", "remoteforward": "R", "dynamicforward": "D"}[key], args)
                    if fwd:
                        opts["forwards"].append(fwd)
                elif key == "identityfile":
                    opts["identityfile"].append(args[0])
                elif key not in opts:
                    opts[key] = args[0]
        return opts

    sessions: dict[str, Session] = {}
    jumps: dict[str, str] = {}
    for alias in aliases:
        o = options(alias)
        host = o.get("hostname", alias).replace("%h", alias)
        try:
            port = int(o.get("port", 22))
        except ValueError:
            port = 22
        key_path = _expand(o["identityfile"][0]) if o["identityfile"] else ""
        s = Session(name=alias, host=host, port=port, user=o.get("user", ""), group=GROUP,
                    auth="key" if key_path else "password", key_path=key_path,
                    forwards=o["forwards"])
        sessions[alias] = s
        if o.get("proxyjump", "none").lower() != "none":
            jumps[alias] = o["proxyjump"]

    extra: list[Session] = []

    def hop_session(hop: str) -> Session:
        if hop in sessions:
            return sessions[hop]
        user, host, port = _parse_jump_hop(hop)
        for s in list(sessions.values()) + extra:
            if (s.name == host or s.host == host) and s.port == port and (not user or s.user == user):
                return s
        s = Session(name=hop, host=host, port=port, user=user, group=GROUP)
        extra.append(s)
        return s

    for alias, spec in jumps.items():
        prev: Session | None = None
        for hop in [h.strip() for h in spec.split(",") if h.strip()]:   # multi-hop: first hop is outermost
            hs = hop_session(hop)
            if prev is not None and hs is not prev and not hs.jump:
                hs.jump = prev.id
            prev = hs
        if prev is not None and prev is not sessions[alias]:
            sessions[alias].jump = prev.id
    return list(sessions.values()) + extra
