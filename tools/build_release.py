# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Build a release for the current platform.

Windows: tests → PyInstaller (onedir) → self-test → ZIP → NSIS installer → SHA256SUMS.
macOS:   tests → app icon (.icns) → PyInstaller (.app, onedir inside) → self-test → DMG → SHA256SUMS.

Usage (from the repository root):
    .venv\\Scripts\\python -m pip install pyinstaller      # build-time only (macOS: also pillow)
    .venv\\Scripts\\python tools\\build_release.py [--skip-tests] [--skip-self-test]

Windows: NSIS 3 is found via the MAKENSIS environment variable, build/tools/nsis-*/makensis.exe
(portable copy) or PATH. Outputs go to dist/:
    JeopsokHeyou-<version>-setup.exe
    JeopsokHeyou-<version>-win-x64.zip
    SHA256SUMS.txt
macOS (needs Pillow for the icon; hdiutil/codesign/ditto ship with macOS). Outputs go to dist/:
    JeopsokHeyou-<version>-macos-<arm64|x86_64>.dmg
    SHA256SUMS.txt
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
APP = DIST / "JeopsokHeyou"                        # Windows: the onedir folder
MAC_APP = DIST / "JeopsokHeyou.app"                # macOS: the bundle (onedir layout inside)
if MACOS:
    PROGRAM = MAC_APP / "Contents" / "MacOS" / "JeopsokHeyou"
    LICENSE_DIR = MAC_APP / "Contents" / "Resources"
else:
    PROGRAM = APP / "JeopsokHeyou.exe"
    LICENSE_DIR = APP
ICNS = BUILD / "app.icns"

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v0}, {v1}, {v2}, 0), prodvers=({v0}, {v1}, {v2}, 0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Seunghun Jun'),
      StringStruct('FileDescription', 'JeopsokHeyou - SSH terminal and SFTP explorer'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'JeopsokHeyou'),
      StringStruct('LegalCopyright', '(c) 2026 Seunghun Jun. GPL-3.0-or-later.'),
      StringStruct('OriginalFilename', 'JeopsokHeyou.exe'),
      StringStruct('ProductName', 'JeopsokHeyou'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def step(title: str) -> None:
    print(f"\n=== {title}", flush=True)


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def version() -> str:
    text = (ROOT / "jeopsokheyou" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text)
    if not m:
        sys.exit("jeopsokheyou/__init__.py must define __version__ = \"X.Y.Z\"")
    return ".".join(m.groups())


def find_makensis() -> str | None:
    env = os.environ.get("MAKENSIS")
    if env and Path(env).exists():
        return env
    portable = sorted(glob.glob(str(BUILD / "tools" / "nsis-*" / "makensis.exe")))
    if portable:
        return portable[-1]
    return shutil.which("makensis")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def self_test(lang: str, qpa: str = "offscreen") -> dict:
    """Run the frozen program without showing a window and read its report.
    qpa="" uses the platform's default plugin (catches a missing qwindows.dll / libqcocoa.dylib etc.)."""
    report = Path(tempfile.mkdtemp()) / f"self-test-{lang}.json"
    # Settings go to an empty temp folder so the builder's own settings don't leak into the test.
    env = dict(os.environ, APPDATA=str(report.parent))
    if MACOS:
        env["HOME"] = str(report.parent)
    env.pop("QT_QPA_PLATFORM", None)   # CI may set offscreen globally; the native run must not inherit it
    if qpa:
        env["QT_QPA_PLATFORM"] = qpa
    subprocess.run([str(PROGRAM), "--lang", lang, "--self-test", str(report)],
                   env=env, check=True, timeout=120)
    return json.loads(report.read_text(encoding="utf-8"))


SKIP_SELF_TEST = False


def self_tests(native_qpa: str) -> bool:
    """en/ko/ja headless, then once more with the native platform plugin."""
    if SKIP_SELF_TEST:
        print("  !! skipped (--skip-self-test): the built program was NOT launched")
        return True
    for lang in ("en", "ko", "ja"):
        r = self_test(lang)
        ok = (r["frozen"] and r["language"] == lang and r["icon"] and r["gaegu_font"]
              and (lang == "en" or (r["catalog_entries"] > 100 and r["qt_translators"] >= 1)))
        print(f"  {lang}: {'OK' if ok else 'FAILED'}  {r['menus']}")
        if not ok:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return False
    r = self_test("en", qpa=native_qpa)
    ok = bool(r["icon"] and r["menus"])
    print(f"  native platform plugin: {'OK' if ok else 'FAILED'}")
    return ok


def make_icns() -> None:
    """assets/app.png → build/app.icns (generated at build time so no binary icon is committed)."""
    from PIL import Image   # build-time only dependency (pip install pillow)
    src = Image.open(ROOT / "assets" / "app.png").convert("RGBA")
    frames = [src.resize((s, s), Image.Resampling.LANCZOS) for s in (32, 64, 128, 256, 512, 1024)]
    frames[-1].save(ICNS, format="ICNS", append_images=frames[:-1])


def write_checksums(outputs: list[Path]) -> None:
    step("Checksums")
    sums = DIST / "SHA256SUMS.txt"
    sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in outputs), encoding="utf-8")
    for p in outputs + [sums]:
        print(f"  {p.name:40} {p.stat().st_size / 1_048_576:7.1f} MB")


def pyinstaller(py: str) -> None:
    run([py, "-m", "PyInstaller", ROOT / "packaging" / "jeopsokheyou.spec", "--noconfirm", "--clean",
         "--distpath", DIST, "--workpath", BUILD / "pyinstaller"])


def copy_licenses(dest: Path) -> None:
    shutil.copy(ROOT / "LICENSE", dest / "LICENSE")
    shutil.copy(ROOT / "THIRD-PARTY-NOTICES.md", dest / "THIRD-PARTY-NOTICES.md")
    shutil.copytree(ROOT / "licenses", dest / "licenses", dirs_exist_ok=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Japanese menu names on a cp949 console
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--skip-self-test", action="store_true",
                    help="do not launch the built program (e.g. when an application control policy blocks "
                         "unsigned executables on this PC); CI always runs the self-test")
    args = ap.parse_args()
    global SKIP_SELF_TEST
    SKIP_SELF_TEST = args.skip_self_test
    ver = version()
    py = sys.executable

    if not args.skip_tests:
        step("Tests")
        run([py, ROOT / "tests" / "run_all.py"])

    if MACOS:
        return build_macos(py, ver)
    if not WINDOWS:
        sys.exit("Releases are built on Windows or macOS only.")
    return build_windows(py, ver)


def build_windows(py: str, ver: str) -> int:
    step(f"PyInstaller (JeopsokHeyou {ver})")
    BUILD.mkdir(exist_ok=True)
    v0, v1, v2 = ver.split(".")
    (BUILD / "version_info.txt").write_text(VERSION_INFO.format(v0=v0, v1=v1, v2=v2, version=ver), encoding="utf-8")
    shutil.rmtree(APP, ignore_errors=True)
    pyinstaller(py)

    step("License files next to the program")
    copy_licenses(APP)

    step("Self-test of the built program")
    if not self_tests(native_qpa=""):
        return 1

    step("Portable ZIP")
    zip_path = DIST / f"JeopsokHeyou-{ver}-win-x64.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(APP.rglob("*")):
            if f.is_file():
                z.write(f, Path("JeopsokHeyou") / f.relative_to(APP))

    outputs = [zip_path]
    makensis = find_makensis()
    if makensis:
        step("NSIS installer (English / Korean / Japanese)")
        setup = DIST / f"JeopsokHeyou-{ver}-setup.exe"
        run([makensis, "/INPUTCHARSET", "UTF8", "/V2", f"/DVERSION={ver}", f"/DSRC_DIR={APP}",
             f"/DOUT_FILE={setup}", f"/DROOT={ROOT}", ROOT / "packaging" / "installer.nsi"])
        outputs.insert(0, setup)
    else:
        print("\n!! makensis not found — installer skipped (set MAKENSIS or install NSIS 3)")

    write_checksums(outputs)
    print(f"\nDone. Folder build: {APP}")
    return 0


def build_macos(py: str, ver: str) -> int:
    arch = platform.machine()   # arm64 or x86_64
    step("App icon (assets/app.png → build/app.icns)")
    BUILD.mkdir(exist_ok=True)
    make_icns()
    print(f"  {ICNS}")

    step(f"PyInstaller (JeopsokHeyou {ver}, macOS {arch})")
    shutil.rmtree(MAC_APP, ignore_errors=True)
    shutil.rmtree(APP, ignore_errors=True)
    pyinstaller(py)

    step("License files in JeopsokHeyou.app/Contents/Resources")
    copy_licenses(LICENSE_DIR)
    # Adding files invalidates PyInstaller's ad-hoc signature (arm64 macOS refuses to run
    # code with a broken signature), so re-sign ad hoc. A Developer ID signature would go here.
    run(["codesign", "--force", "--deep", "--sign", "-", MAC_APP])
    run(["codesign", "--verify", "--deep", "--strict", MAC_APP])

    step("Self-test of the built program")
    if not self_tests(native_qpa="cocoa"):
        return 1

    step("Disk image (DMG)")
    staging = BUILD / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    run(["ditto", MAC_APP, staging / "JeopsokHeyou.app"])   # keeps symlinks, modes and the signature
    (staging / "Applications").symlink_to("/Applications")
    shutil.copy(ROOT / "LICENSE", staging / "LICENSE")
    shutil.copy(ROOT / "THIRD-PARTY-NOTICES.md", staging / "THIRD-PARTY-NOTICES.md")
    dmg = DIST / f"JeopsokHeyou-{ver}-macos-{arch}.dmg"
    dmg.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", "JeopsokHeyou", "-srcfolder", staging, "-ov",
         "-format", "UDZO", dmg])

    write_checksums([dmg])
    print(f"\nDone. App bundle: {MAC_APP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
