# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""This computer's files for the explorer of a local terminal.

LocalSftp answers the few SFTP calls the explorer makes (list, stat, mkdir, rename, remove, copy in and out) with
the local file system, on the explorer's POSIX-style paths ("/C:/Users/me" on Windows; "/" lists the drives).
So the explorer, its tree, transfers and drag & drop work the same for this computer as for a server.
"""
from __future__ import annotations

import os
import shutil
import stat
import string
import sys

import paramiko

from . import diskusage
from .localshell import IS_WIN, to_native, to_virtual

CHUNK = 1 << 20


def _attrs(st, name: str) -> paramiko.SFTPAttributes:
    a = paramiko.SFTPAttributes.from_stat(st, name)
    return a


def drives() -> list[str]:
    """Drive letters in use ("C:", "D:", …)."""
    if not IS_WIN:
        return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{c}:" for i, c in enumerate(string.ascii_uppercase) if mask & (1 << i)]


class LocalSftp:
    """The SFTP client calls the explorer uses, on this computer's files."""

    def __init__(self):
        self.home = to_virtual(os.path.expanduser("~"))

    # paths
    def _n(self, path: str) -> str:
        native = to_native(path)
        if not native:
            raise IOError(2, "No such file", path)
        return native

    def normalize(self, path: str) -> str:
        if path in (".", ""):
            return self.home
        if IS_WIN and path == "/":
            return "/"
        native = os.path.realpath(self._n(path)) if not IS_WIN else os.path.abspath(self._n(path))
        if not os.path.exists(native):
            raise IOError(2, "No such file", path)
        return to_virtual(native)

    # listing
    def listdir_attr(self, path: str = ".") -> list:
        if IS_WIN and path in ("/", ""):
            out = []
            for d in drives():
                try:
                    st = os.stat(d + "\\")
                except OSError:
                    continue
                a = _attrs(st, d)
                a.st_mode = stat.S_IFDIR | 0o755
                out.append(a)
            return out
        native = self._n(path)
        out = []
        with os.scandir(native) as it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                out.append(_attrs(st, e.name))
        return out

    def stat(self, path: str):
        if IS_WIN and path in ("/", ""):
            a = paramiko.SFTPAttributes()
            a.st_mode = stat.S_IFDIR | 0o755
            return a
        return _attrs(os.stat(self._n(path)), os.path.basename(path))

    def lstat(self, path: str):
        if IS_WIN and path in ("/", ""):
            return self.stat(path)
        return _attrs(os.lstat(self._n(path)), os.path.basename(path))

    # changes
    def mkdir(self, path: str, mode: int = 0o777) -> None:
        os.mkdir(self._n(path))

    def rmdir(self, path: str) -> None:
        os.rmdir(self._n(path))

    def remove(self, path: str) -> None:
        os.remove(self._n(path))

    def rename(self, old: str, new: str) -> None:
        dst = self._n(new)
        if os.path.exists(dst):
            raise IOError(17, "File exists", new)
        os.rename(self._n(old), dst)

    # copies (the explorer's download / upload)
    def get(self, remotepath: str, localpath: str, callback=None) -> None:
        self._copy(self._n(remotepath), localpath, callback)

    def put(self, localpath: str, remotepath: str, callback=None, confirm: bool = True):
        self._copy(localpath, self._n(remotepath), callback)
        return self.stat(remotepath)

    @staticmethod
    def _copy(src: str, dst: str, callback=None) -> None:
        if os.path.abspath(src) == os.path.abspath(dst):
            return
        size = os.path.getsize(src)
        done = 0
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            while True:
                buf = fi.read(CHUNK)
                if not buf:
                    break
                fo.write(buf)
                done += len(buf)
                if callback:
                    callback(done, size)
        try:
            shutil.copystat(src, dst)
        except OSError:
            pass

    def local_copy(self, src: str, dst: str) -> None:
        """job_copy on this computer: a plain file copy (keeps the dates)."""
        shutil.copy2(self._n(src), self._n(dst))

    # disk space of this computer (diskusage.query asks for it)
    def local_disk_summary(self) -> diskusage.Summary | None:
        disks = []
        for root in ([d + "\\" for d in drives()] if IS_WIN else ["/"] + ([os.path.expanduser("~")] if sys.platform != "win32" else [])):
            try:
                u = shutil.disk_usage(root)
            except OSError:
                continue
            if IS_WIN:
                import ctypes
                kind = ctypes.windll.kernel32.GetDriveTypeW(root)
                if kind not in (3,):                  # fixed disks only (no network, CD, USB sticks)
                    continue
            if any(d.total == u.total and d.used + d.avail == u.used + u.free for d in disks):
                continue
            disks.append(diskusage.Disk(root.rstrip("\\") or root, total=u.total, used=u.used, avail=u.free))
        if not disks:
            return None
        return diskusage.Summary(disks, sum(d.total for d in disks), sum(d.used for d in disks),
                                 sum(d.avail for d in disks))

    def close(self) -> None:
        pass


class LocalConnection:
    """Stands in for an SSH connection where the explorer opens its file access."""
    is_local = True

    def open_sftp(self) -> LocalSftp:
        return LocalSftp()

    def close(self) -> None:
        pass
