# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Server disk space, read without putting any load on the server.

Only the SFTP channel the explorer already has open is used — no extra channel, no shell command,
no new process on the server:
- the mount list comes from reading /proc/self/mounts (a small virtual file; skipped if missing)
- each local disk is asked once with the "statvfs@openssh.com" extension (the server asks the OS for
  the numbers it already keeps; nothing is scanned)
- network file systems (NFS, SMB, sshfs, ...) are never asked, since a stuck share could hang the call
If the server doesn't support the extension, nothing is shown.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import time
from dataclasses import dataclass

from paramiko.sftp import CMD_EXTENDED, CMD_EXTENDED_REPLY

# File systems that live on a local disk. Everything else is either virtual (proc, tmpfs, overlay, ...)
# or remote and is left alone.
LOCAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "jfs", "reiserfs", "f2fs", "bcachefs",
            "vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "hfs", "hfsplus", "apfs", "ufs", "ffs"}
NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "ncpfs", "afs", "ceph", "glusterfs", "9p",
              "davfs", "lustre", "gpfs", "beegfs", "ocfs2", "gfs2"}
MAX_DISKS = 32
_OCTAL = re.compile(r"\\([0-7]{3})")


@dataclass
class Disk:
    mount: str
    device: str = ""
    fstype: str = ""
    total: int = 0
    used: int = 0
    avail: int = 0
    network: bool = False        # listed but deliberately not asked

    @property
    def free_pct(self) -> float:
        """Free share the way df counts it (space reserved for root is not counted as free)."""
        room = self.used + self.avail
        return self.avail * 100.0 / room if room else 100.0


@dataclass
class Summary:
    disks: list            # every Disk, network ones included
    total: int
    used: int
    avail: int

    @property
    def measured(self) -> list:
        return [d for d in self.disks if not d.network]

    @property
    def free_pct(self) -> float:
        room = self.used + self.avail
        return self.avail * 100.0 / room if room else 100.0

    def worst(self) -> Disk | None:
        m = self.measured
        return min(m, key=lambda d: d.free_pct) if m else None


def level(free_pct: float, warn: float, crit: float) -> str:
    """"ok" | "warn" | "crit" for a free percentage and the user's thresholds."""
    if free_pct < crit:
        return "crit"
    if free_pct < warn:
        return "warn"
    return "ok"


def _unescape(s: str) -> str:
    return _OCTAL.sub(lambda m: chr(int(m.group(1), 8)), s)


def is_network(fstype: str, device: str) -> bool:
    t = fstype.lower()
    return (t in NETWORK_FS or t.startswith("fuse.") or t.startswith("nfs")
            or device.startswith("//") or (":" in device and not device.startswith("/")))


def parse_mounts(text: str) -> list[Disk]:
    """Local disks and network shares from /proc/mounts text; virtual file systems are dropped and
    a device mounted several times (bind mounts) is kept once, at its shortest mount point."""
    by_dev: dict[str, Disk] = {}
    order: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount, fstype = _unescape(parts[0]), _unescape(parts[1]), parts[2].lower()
        network = is_network(fstype, device)
        if not network and fstype not in LOCAL_FS:
            continue
        if not network and fstype != "zfs" and not device.startswith("/dev/"):
            continue
        key = device + "|" + fstype
        old = by_dev.get(key)
        if old is None:
            by_dev[key] = Disk(mount, device, fstype, network=network)
            order.append(key)
        elif len(mount) < len(old.mount):
            old.mount = mount
    disks = [by_dev[k] for k in order]
    disks.sort(key=lambda d: (d.network, d.mount != "/", d.mount))
    return disks[:MAX_DISKS]


def statvfs(sftp, path: str) -> tuple[int, int, int] | None:
    """(total, used, avail) bytes of the file system holding `path`, or None if not supported."""
    try:
        t, msg = sftp._request(CMD_EXTENDED, "statvfs@openssh.com", path)
    except Exception:
        return None
    if t != CMD_EXTENDED_REPLY:
        return None
    try:
        _bsize = msg.get_int64()
        frsize = msg.get_int64()
        blocks = msg.get_int64()
        bfree = msg.get_int64()
        bavail = msg.get_int64()
    except Exception:
        return None
    frsize = frsize or _bsize or 1
    total = blocks * frsize
    used = max(0, (blocks - bfree) * frsize)
    return total, used, bavail * frsize


def read_mounts(sftp) -> str:
    for p in ("/proc/self/mounts", "/proc/mounts"):
        try:
            with sftp.open(p, "r") as f:
                chunks = []
                size = 0
                while size < 1 << 20:
                    b = f.read(32768)
                    if not b:
                        break
                    chunks.append(b)
                    size += len(b)
            return b"".join(chunks).decode("utf-8", "replace")
        except Exception:
            continue
    return ""


# ---------------------------------------------------------------- last values seen (kept on this PC only)
def cache_file():
    from . import config
    return config.app_dir() / "disk_cache.json"


def load_last(path=None) -> dict:
    """{session_id: {"time", "mount", "free_pct", "avail", "total_avail", "total", "total_free_pct"}}"""
    path = path or cache_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_last(session_id: str, summary: Summary, path=None, now: float | None = None) -> None:
    """Remember the latest numbers for the host card. Written locally; nothing goes to the server."""
    worst = summary.worst()
    if not session_id or worst is None:
        return
    path = path or cache_file()
    data = load_last(path)
    data[session_id] = {"time": now if now is not None else time.time(), "mount": worst.mount,
                        "free_pct": round(worst.free_pct, 2), "avail": worst.avail,
                        "total_avail": summary.avail, "total": summary.total,
                        "total_free_pct": round(summary.free_pct, 2)}
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def forget_last(session_ids, path=None) -> None:
    path = path or cache_file()
    data = load_last(path)
    if not any(sid in data for sid in session_ids):
        return
    for sid in session_ids:
        data.pop(sid, None)
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def query(sftp, home: str = "") -> Summary | None:
    """Runs in the explorer's SFTP worker thread. None when the server can't tell us."""
    disks = parse_mounts(read_mounts(sftp))
    if not disks:
        # No /proc (macOS, BSD, ...): ask for the root disk and the home folder only
        disks = [Disk("/")]
        if home and home != "/":
            disks.append(Disk(posixpath.normpath(home)))
    seen: set[tuple[int, int]] = set()
    out: list[Disk] = []
    answered = False
    for d in disks:
        if d.network:
            out.append(d)
            continue
        r = statvfs(sftp, d.mount)
        if r is None:
            if not answered:
                return None          # the first ask failed: extension unsupported, stay hidden
            continue
        answered = True
        d.total, d.used, d.avail = r
        if d.total <= 0:
            continue
        sig = (d.total, d.used + d.avail)
        if not d.device and sig in seen:   # fallback mode: home on the same disk as /
            continue
        seen.add(sig)
        out.append(d)
    measured = [d for d in out if not d.network]
    if not measured:
        return None
    return Summary(out, sum(d.total for d in measured), sum(d.used for d in measured),
                   sum(d.avail for d in measured))
