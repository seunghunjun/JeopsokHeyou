# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Small helpers shared by the tests."""
import subprocess
import sys


def stop_server(proc) -> None:
    """Stop the fake SSH server started by a test (on Windows the venv launcher spawns a child, so kill the tree)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except Exception:
        pass
