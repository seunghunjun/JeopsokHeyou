# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Shells on this computer (local terminals).

- Profiles: the shells found on this computer (PowerShell, Command Prompt, WSL, Git Bash on Windows; the
  login shell on macOS) plus the user's own ones (Settings).
- LocalProcess: a shell in a pseudo terminal — ConPTY on Windows (pywinpty), a pty on macOS/Linux — with the
  small part of a paramiko channel the terminal pane uses (recv / sendall / resize_pty / close).
- Paths: the explorer works with POSIX-style paths ("/C:/Users/me" on Windows, "/" lists the drives); each shell
  reports and takes its own kind of path. The functions here translate between them.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field

from . import applog

log = applog.get("local")
IS_WIN = sys.platform == "win32"

# ---------------------------------------------------------------- profiles
KINDS = ("cmd", "powershell", "wsl", "gitbash", "posix", "other")


@dataclass
class ShellProfile:
    name: str
    kind: str = "other"           # cmd | powershell | wsl | gitbash | posix | other (no folder sync)
    argv: list = field(default_factory=list)
    start_dir: str = ""           # native path; "" = home folder
    distro: str = ""              # WSL distribution
    custom: bool = False          # added by the user in Settings
    id: str = ""

    def key(self) -> str:
        return self.id or f"{self.kind}:{self.distro or self.name}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ShellProfile":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        p = cls(**known)
        if not isinstance(p.argv, list):
            p.argv = split_command(str(p.argv))
        if p.kind not in KINDS:
            p.kind = guess_kind(p.argv)
        return p


def split_command(text: str) -> list[str]:
    """A command line typed by the user -> argv (Windows quoting rules on Windows)."""
    import shlex
    text = (text or "").strip()
    if not text:
        return []
    try:
        parts = shlex.split(text, posix=not IS_WIN)
    except ValueError:
        parts = text.split()
    return [p[1:-1] if IS_WIN and len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]


def join_command(argv: list[str]) -> str:
    if IS_WIN:
        return subprocess.list2cmdline(argv)
    import shlex
    return " ".join(shlex.quote(a) for a in argv)


def guess_kind(argv: list[str]) -> str:
    exe = os.path.basename(argv[0]).lower() if argv else ""
    if exe in ("cmd", "cmd.exe"):
        return "cmd"
    if exe in ("powershell", "powershell.exe", "pwsh", "pwsh.exe"):
        return "powershell"
    if exe in ("wsl", "wsl.exe"):
        return "wsl"
    if IS_WIN and exe in ("bash", "bash.exe") and "git" in argv[0].lower():
        return "gitbash"
    if exe in ("bash", "zsh", "sh", "fish", "bash.exe", "zsh.exe"):
        return "posix"
    return "other"


def _wsl_distros() -> list[str]:
    exe = shutil.which("wsl.exe")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "-l", "-q"], capture_output=True, timeout=3,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    text = out.decode("utf-16-le", errors="ignore") if b"\x00" in out else out.decode("utf-8", errors="ignore")
    names = [n.strip().strip("\x00") for n in text.splitlines()]
    return [n for n in names if n and not n.lower().startswith(("docker-desktop",))]


def git_root() -> str:
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base and os.path.isfile(os.path.join(base, "Git", "bin", "bash.exe")):
            return os.path.join(base, "Git")
    return ""


_detected: list[ShellProfile] | None = None


def detect_shells(refresh: bool = False) -> list[ShellProfile]:
    """The shells found on this computer, the usual one first. Cached (WSL is asked once)."""
    global _detected
    if _detected is not None and not refresh:
        return list(_detected)
    found: list[ShellProfile] = []
    if IS_WIN:
        windir = os.environ.get("SystemRoot", r"C:\Windows")
        pwsh = shutil.which("pwsh.exe") or next(
            (p for p in (os.path.join(os.environ.get("ProgramFiles", ""), "PowerShell", "7", "pwsh.exe"),)
             if os.path.isfile(p)), "")
        if pwsh:
            found.append(ShellProfile("PowerShell 7", "powershell", [pwsh]))
        ps = os.path.join(windir, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if os.path.isfile(ps):
            found.append(ShellProfile("Windows PowerShell", "powershell", [ps]))
        cmd = os.environ.get("COMSPEC") or os.path.join(windir, "System32", "cmd.exe")
        found.append(ShellProfile("Command Prompt", "cmd", [cmd]))
        for d in _wsl_distros():
            found.append(ShellProfile(d, "wsl", ["wsl.exe", "-d", d, "--cd", "~"], distro=d))
        g = git_root()
        if g:
            found.append(ShellProfile("Git Bash", "gitbash", [os.path.join(g, "bin", "bash.exe"), "--login", "-i"]))
    else:
        shells = []
        login = os.environ.get("SHELL", "")
        for sh in [login, "/bin/zsh", "/bin/bash"]:
            if sh and os.path.isfile(sh) and sh not in shells:
                shells.append(sh)
        for sh in shells:
            found.append(ShellProfile(os.path.basename(sh), guess_kind([sh]), [sh, "-l"]))
    _detected = found
    return list(found)


def detected_if_ready() -> list[ShellProfile] | None:
    """The shells found so far without waiting (None until detect_shells has run once)."""
    return list(_detected) if _detected is not None else None


def profiles(settings: dict, wait: bool = True) -> list[ShellProfile]:
    """Shells found on this computer, then the user's own (Settings › Local terminals)."""
    out = detect_shells() if wait else (detected_if_ready() or [])
    for d in settings.get("local_shells") or []:
        try:
            p = ShellProfile.from_dict(d)
        except TypeError:
            continue
        if p.argv:
            p.custom = True
            out.append(p)
    return out


def default_profile(settings: dict) -> ShellProfile | None:
    ps = profiles(settings)
    want = settings.get("local_shell_default", "")
    return next((p for p in ps if p.key() == want), ps[0] if ps else None)


# ---------------------------------------------------------------- folder sync hooks
# PowerShell: wrap the prompt so it reports the folder (OSC 7) before drawing itself (any custom prompt keeps working)
PS_HOOK = ("$global:__jh_prompt = $function:prompt; "
           "function global:prompt { $p = (Get-Location).ProviderPath; "
           "[Console]::Write([char]27 + ']7;' + $p + [char]27 + [char]92); & $global:__jh_prompt }")


def launch(profile: ShellProfile) -> tuple[list[str], dict]:
    """argv and environment for a profile, with the folder report hook where the shell allows it at start."""
    argv = list(profile.argv)
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env.setdefault("COLORTERM", "truecolor")
    if profile.kind == "cmd":
        env["PROMPT"] = "$e]7;$P$e\\" + (os.environ.get("PROMPT") or "$P$G")
    elif profile.kind == "powershell" and not any(a.lower() in ("-command", "-c", "-encodedcommand", "-file")
                                                  for a in argv[1:]):
        enc = base64.b64encode(PS_HOOK.encode("utf-16-le")).decode("ascii")
        argv += ["-NoLogo", "-NoExit", "-EncodedCommand", enc]
    return argv, env


def hooked_at_start(profile: ShellProfile) -> bool:
    """cmd and PowerShell report their folder from the start; bash/zsh get the same hook as SSH (typed in)."""
    return profile.kind in ("cmd", "powershell")


def injectable(profile: ShellProfile) -> bool:
    return profile.kind in ("wsl", "gitbash", "posix")


# ---------------------------------------------------------------- paths
def to_virtual(native: str) -> str:
    """A path of this computer as the explorer writes it: "C:\\Users\\me" -> "/C:/Users/me"."""
    if not IS_WIN:
        return native or "/"
    p = native.replace("/", "\\")
    if p.startswith("\\\\?\\"):
        p = p[4:]
    if p.startswith("\\\\"):
        rest = p[2:].strip("\\")
        return "/UNC/" + rest.replace("\\", "/") if rest else "/"
    if len(p) >= 2 and p[1] == ":":
        tail = p[2:].strip("\\").replace("\\", "/")
        return f"/{p[0].upper()}:" + ("/" + tail if tail else "")
    return "/"


def to_native(virtual: str) -> str:
    """"/C:/Users/me" -> "C:\\Users\\me" ("" for "/", the list of drives)."""
    if not IS_WIN:
        return virtual or "/"
    parts = [p for p in (virtual or "").split("/") if p]
    if not parts:
        return ""
    if parts[0] == "UNC":
        return "\\\\" + "\\".join(parts[1:]) if len(parts) > 1 else ""
    drive = parts[0]
    if len(drive) == 2 and drive[1] == ":":
        return drive.upper() + "\\" + "\\".join(parts[1:])
    return ""


def reported_to_virtual(profile: ShellProfile, path: str) -> str | None:
    """The folder a shell reported -> explorer path (None when it has no place on this computer)."""
    if not path:
        return None
    if profile.kind in ("cmd", "powershell"):
        return to_virtual(path) if (len(path) >= 2 and path[1] == ":") or path.startswith("\\\\") else None
    if not IS_WIN:
        return path
    if profile.kind == "wsl":
        if path.startswith("/mnt/") and len(path) >= 6 and (len(path) == 6 or path[6] == "/"):
            return f"/{path[5].upper()}:" + path[6:]
        if profile.distro:
            return "/UNC/wsl.localhost/" + profile.distro + (path if path != "/" else "")
        return None
    if profile.kind == "gitbash":
        if len(path) >= 2 and path[0] == "/" and path[1].isalpha() and (len(path) == 2 or path[2] == "/"):
            return f"/{path[1].upper()}:" + path[2:]
        g = git_root()
        return to_virtual(os.path.join(g, path.lstrip("/"))) if g else None
    return None


def cd_line(profile: ShellProfile, virtual: str) -> str | None:
    """The command that moves the shell to an explorer folder (None when this shell can't go there)."""
    if profile.kind == "cmd":
        native = to_native(virtual)
        return f" cd /d \"{native}\"\r" if native and '"' not in native else None
    if profile.kind == "powershell":
        native = to_native(virtual)
        return " Set-Location -LiteralPath '" + native.replace("'", "''") + "'\r" if native else None
    if profile.kind in ("posix", "wsl", "gitbash"):
        target = virtual
        if IS_WIN:
            parts = [p for p in virtual.split("/") if p]
            if not parts:
                return None
            if profile.kind == "wsl" and parts[0] == "UNC" and len(parts) >= 3 \
                    and parts[1].lower() in ("wsl.localhost", "wsl$") and parts[2] == profile.distro:
                target = "/" + "/".join(parts[3:])
            elif len(parts[0]) == 2 and parts[0][1] == ":":
                letter = parts[0][0].lower()
                rest = "/".join(parts[1:])
                target = (f"/mnt/{letter}" if profile.kind == "wsl" else f"/{letter}") + ("/" + rest if rest else "")
            else:
                return None
        return " cd -- '" + target.replace("'", "'\\''") + "'\r"
    return None


def display_path(profile: ShellProfile, reported: str) -> str:
    return reported


# ---------------------------------------------------------------- the shell process
class LocalProcess:
    """A shell in a pseudo terminal, used by the terminal pane like an SSH channel."""

    def __init__(self, profile: ShellProfile, cols: int, rows: int):
        self.profile = profile
        argv, env = launch(profile)
        cwd = profile.start_dir if profile.start_dir and os.path.isdir(profile.start_dir) else os.path.expanduser("~")
        self.closed = False
        self._lock = threading.Lock()
        if IS_WIN:
            from winpty import PTY
            exe = shutil.which(argv[0]) or argv[0]
            self._pty = PTY(max(2, cols), max(2, rows))
            env_block = "\0".join(f"{k}={v}" for k, v in env.items()) + "\0"
            cmdline = (" " + subprocess.list2cmdline(argv[1:])) if len(argv) > 1 else None
            if cmdline:
                self._pty.spawn(exe, cmdline=cmdline, cwd=cwd, env=env_block)
            else:
                self._pty.spawn(exe, cwd=cwd, env=env_block)
            self._pending = b""
        else:
            import fcntl
            import pty
            import struct
            import termios
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            self._proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
                                          start_new_session=True, close_fds=True)
            os.close(slave)
            self._fd = master
        log.info("local shell started: %s (%s)", profile.name, profile.kind)

    # -- the part of a paramiko channel the terminal uses
    def recv(self, n: int) -> bytes:
        if IS_WIN:
            while not self.closed:
                try:
                    s = self._pty.read(blocking=True)
                except Exception:
                    return b""
                if s:
                    return s.encode("utf-8", errors="replace")
                if self._pty.iseof() or not self._pty.isalive():
                    return b""
                time.sleep(0.005)
            return b""
        try:
            return os.read(self._fd, n)
        except OSError:
            return b""

    def sendall(self, data: bytes) -> None:
        if self.closed:
            return                      # keys typed (or terminal replies) after the shell ended: nowhere to go
        if IS_WIN:
            with self._lock:
                self._pty.write(data.decode("utf-8", errors="replace"))
        else:
            view = memoryview(data)
            while view:
                n = os.write(self._fd, view)
                view = view[n:]

    def resize_pty(self, width: int, height: int) -> None:
        if self.closed:
            return
        if IS_WIN:
            self._pty.set_size(max(2, width), max(2, height))
        else:
            import fcntl
            import struct
            import termios
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if IS_WIN:
            try:
                self._pty.cancel_io()
            except Exception:
                pass
            pid = self._pty.pid
            if pid and self._pty.isalive():
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except (OSError, subprocess.SubprocessError):
                    pass
            self._pty = _Closed()
        else:
            try:
                self._proc.terminate()
                self._proc.wait(2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            try:
                os.close(self._fd)
            except OSError:
                pass
        log.info("local shell closed: %s", self.profile.name)


class _Closed:
    pid = None

    def read(self, blocking=False):
        return ""

    def iseof(self):
        return True

    def isalive(self):
        return False

    def write(self, s):
        raise OSError("closed")

    def set_size(self, *a):
        pass

    def cancel_io(self):
        return True
