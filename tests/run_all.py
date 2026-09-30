# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
r"""Run all tests: .venv\Scripts\python tests\run_all.py
Each test runs headless (offscreen) in its own process, against a fake SSH/SFTP server (tests/fake_server.py)."""
import glob
import os
import re
import subprocess
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # printable even on legacy Windows consoles (e.g. cp949)
env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
if sys.platform == "win32":
    env.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))


def kill_leftover_servers():
    """Kill fake servers (port 2299) left behind by a test that died, so the next test is unaffected."""
    if sys.platform == "win32":
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tests*fake_server.py*' } "
              "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
        return
    try:   # macOS / Linux
        subprocess.run(["pkill", "-9", "-f", "tests/fake_server[.]py"], capture_output=True)
    except OSError:
        pass   # no pkill on this system


total_ok = total_ng = 0
failed = []
for path in sorted(glob.glob(os.path.join(TESTS, "test_*.py"))):
    name = os.path.basename(path)
    try:
        r = subprocess.run([sys.executable, path], env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + "\nTIMEOUT"
    ok = len(re.findall(r"(?m)^PASS |: True\b", out)) + (1 if out.strip().endswith("OK") else 0)
    ng = len(re.findall(r"(?m)^FAIL |: False\b|Traceback|TIMEOUT", out))
    done = "DONE" in out or out.strip().endswith("OK")
    total_ok += ok
    total_ng += ng
    status = "PASS" if ng == 0 and done else "FAIL"
    if status == "FAIL":
        failed.append(name)
        print("\n".join(l for l in out.splitlines() if re.search(r"^FAIL|: False|Traceback|Error|TIMEOUT", l))[:2000])
    kill_leftover_servers()
    print(f"[{status}] {name:28} ok={ok} ng={ng}")
print(f"\n{total_ok} passed, {total_ng} failed" + (f" — failed: {', '.join(failed)}" if failed else ""))
sys.exit(1 if failed else 0)
