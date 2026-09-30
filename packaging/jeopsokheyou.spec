# PyInstaller spec for JeopsokHeyou — built by tools/build_release.py.
# "onedir" layout on purpose: the LGPL libraries (Qt/PySide6, paramiko, pyte) stay as
# separate, replaceable files next to the program (on macOS: inside the .app bundle).
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (SPECPATH is provided by PyInstaller)
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

with open(os.path.join(ROOT, "jeopsokheyou", "__init__.py"), encoding="utf-8") as _fh:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _fh.read()).group(1)

datas = [
    (os.path.join(ROOT, "assets", "app.ico"), "assets"),
    (os.path.join(ROOT, "assets", "app.png"), "assets"),
    (os.path.join(ROOT, "assets", "fonts"), os.path.join("assets", "fonts")),
    (os.path.join(ROOT, "jeopsokheyou", "locales"), os.path.join("jeopsokheyou", "locales")),
]

# Qt modules the app never uses — keeps the download small.
excludes = [
    "tkinter", "unittest", "pydoc",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtSql",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest",
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=["yaml"],
    excludes=excludes,
    noarchive=False,
)
# Drop Qt pieces pulled in by plugins the app never uses (the app is plain QtWidgets):
# software OpenGL fallback, QML/Quick (virtual keyboard), PDF image plugin, network/TLS.
# These are Windows DLL names; on macOS Qt ships as frameworks and nothing is dropped here.
DROP_BINARIES = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6network", "qt6opengl",
                 "qt6virtualkeyboard", "qtvirtualkeyboardplugin", "qpdf", "qtuiotouchplugin",
                 "qdirect2d", "qminimal")


def _keep_binary(entry):
    if not WINDOWS:
        return True
    name = os.path.basename(entry[0]).lower()
    return not any(name.startswith(d) or d in name for d in DROP_BINARIES)


def _keep_data(entry):
    # Qt translations: keep only the languages the app ships (en needs none).
    # Windows: PySide6/translations/*.qm, macOS: PySide6/Qt/translations/*.qm
    dest = entry[0].replace("\\", "/").lower()
    if "/translations/" in dest and dest.endswith(".qm"):
        return dest.rsplit("/", 1)[-1].startswith(("qtbase_ko", "qtbase_ja", "qt_ko", "qt_ja"))
    if dest.endswith("gaegu-light.ttf"):   # not shipped any more; kept as a safety net
        return False   # only Regular and Bold are used
    return True


a.binaries = [b for b in a.binaries if _keep_binary(b)]
a.datas = [d for d in a.datas if _keep_data(d)]

if WINDOWS:
    # Written by tools/build_release.py before PyInstaller runs.
    platform_exe_options = dict(icon=os.path.join(ROOT, "assets", "app.ico"),
                                version=os.path.join(ROOT, "build", "version_info.txt"))
elif MACOS:
    # build/app.icns is generated from assets/app.png by tools/build_release.py (no binary in git).
    platform_exe_options = dict(icon=os.path.join(ROOT, "build", "app.icns"))
else:
    platform_exe_options = {}

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JeopsokHeyou",
    console=False,
    upx=False,
    **platform_exe_options,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="JeopsokHeyou",
    upx=False,
)

if MACOS:
    app = BUNDLE(  # noqa: F821
        coll,
        name="JeopsokHeyou.app",
        icon=os.path.join(ROOT, "build", "app.icns"),
        bundle_identifier="com.seunghunjun.jeopsokheyou",
        version=VERSION,
        info_plist={
            "CFBundleName": "JeopsokHeyou",
            "CFBundleDisplayName": "JeopsokHeyou",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            # Qt 6.11 (PySide6 6.11 wheels are tagged macosx_13_0) needs macOS 13 Ventura or later.
            "LSMinimumSystemVersion": "13.0",
            "NSAppleEventsUsageDescription":
                "JeopsokHeyou asks Finder where you dropped a file so it can download it there.",
            "NSHumanReadableCopyright": "© 2026 Seunghun Jun. GPL-3.0-or-later.",
        },
    )
