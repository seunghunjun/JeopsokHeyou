# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Local terminals: shells of this computer in a tab, this computer's files in the explorer next to it,
the explorer and the shell following each other, files dragged between this computer and a server."""
import os
import shutil
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "local")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from jeopsokheyou import localshell  # noqa: E402
from jeopsokheyou.localfs import LocalConnection, LocalSftp  # noqa: E402
from jeopsokheyou.localshell import ShellProfile, cd_line, reported_to_virtual, to_native, to_virtual  # noqa: E402

WIN = sys.platform == "win32"


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def wait(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


# ---- paths: the explorer's POSIX-style paths <-> each shell's own
if WIN:
    check("Windows path -> explorer path", to_virtual("C:\\Users\\me") == "/C:/Users/me" and to_virtual("d:\\") == "/D:")
    check("explorer path -> Windows path", to_native("/C:/Users/me") == "C:\\Users\\me" and to_native("/D:") == "D:\\"
          and to_native("/") == "")
    check("network paths", to_virtual("\\\\srv\\share\\x") == "/UNC/srv/share/x"
          and to_native("/UNC/srv/share/x") == "\\\\srv\\share\\x")
    cmd, ps = ShellProfile("cmd", "cmd", ["cmd.exe"]), ShellProfile("ps", "powershell", ["powershell.exe"])
    wsl = ShellProfile("Ubuntu", "wsl", ["wsl.exe"], distro="Ubuntu")
    git = ShellProfile("Git Bash", "gitbash", ["bash.exe"])
    check("folders reported by each shell", reported_to_virtual(cmd, "C:\\Windows") == "/C:/Windows"
          and reported_to_virtual(ps, "C:\\Windows") == "/C:/Windows"
          and reported_to_virtual(wsl, "/mnt/c/Users") == "/C:/Users"
          and reported_to_virtual(wsl, "/home/me") == "/UNC/wsl.localhost/Ubuntu/home/me"
          and reported_to_virtual(git, "/c/Users") == "/C:/Users")
    check("the command each shell gets to move", cd_line(cmd, "/C:/Users") == ' cd /d "C:\\Users"\r'
          and cd_line(ps, "/C:/it's") == " Set-Location -LiteralPath 'C:\\it''s'\r"
          and cd_line(wsl, "/C:/Users") == " cd -- '/mnt/c/Users'\r"
          and cd_line(wsl, "/UNC/wsl.localhost/Ubuntu/home/me") == " cd -- '/home/me'\r"
          and cd_line(git, "/D:/x") == " cd -- '/d/x'\r")
    check("no command where a shell can't go", cd_line(cmd, "/") is None and cd_line(git, "/UNC/srv/s") is None)
else:
    check("paths are the same on macOS/Linux", to_virtual("/Users/me") == "/Users/me" and to_native("/tmp") == "/tmp")
    sh = ShellProfile("zsh", "posix", ["/bin/zsh"])
    check("the shell's folder as reported", reported_to_virtual(sh, "/tmp") == "/tmp"
          and cd_line(sh, "/tmp/a'b") == " cd -- '/tmp/a'\\''b'\r")

found = localshell.detect_shells()
check("shells found on this computer", bool(found) and all(p.argv for p in found), [p.name for p in found])
if WIN:
    check("... Command Prompt among them", any(p.kind == "cmd" for p in found))
check("a typed command line is split like the system does", localshell.split_command(
    '"C:\\Program Files\\x.exe" -a' if WIN else "/bin/zsh -l") == (["C:\\Program Files\\x.exe", "-a"] if WIN
                                                                 else ["/bin/zsh", "-l"]))

# ---- this computer's files, the way the explorer asks for them
root = os.path.join(SP, "files")
os.makedirs(os.path.join(root, "sub"))
open(os.path.join(root, "a.txt"), "w", encoding="utf-8").write("hello")
fs = LocalSftp()
vroot = to_virtual(root)
check("normalize", fs.normalize(vroot) == vroot and fs.normalize(".") == to_virtual(os.path.expanduser("~")))
names = sorted(a.filename for a in fs.listdir_attr(vroot))
check("list a folder", names == ["a.txt", "sub"], names)
import stat as _stat  # noqa: E402
check("folders and files told apart", _stat.S_ISDIR(fs.stat(vroot + "/sub").st_mode)
      and _stat.S_ISREG(fs.stat(vroot + "/a.txt").st_mode) and fs.stat(vroot + "/a.txt").st_size == 5)
fs.mkdir(vroot + "/new")
fs.rename(vroot + "/new", vroot + "/renamed")
check("new folder and rename", os.path.isdir(os.path.join(root, "renamed")))
progress = []
fs.get(vroot + "/a.txt", os.path.join(SP, "copy.txt"), callback=lambda d, t: progress.append((d, t)))
fs.put(os.path.join(SP, "copy.txt"), vroot + "/sub/b.txt")
check("copies out and in (with progress)", open(os.path.join(root, "sub", "b.txt"), encoding="utf-8").read() == "hello"
      and progress[-1] == (5, 5))
if WIN:
    drives = [a.filename for a in fs.listdir_attr("/")]
    check("'This PC' lists the drives", any(d.upper().startswith("C:") for d in drives), drives)
summary = fs.local_disk_summary()
check("disk space of this computer", summary is not None and summary.total > 0)

# ---- a local terminal tab
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1300, 700)
w.show()
prof = next((p for p in found if p.kind == "cmd"), None) if WIN else found[0]
prof.start_dir = root
w.open_local(prof)
tab = w.current_tab()
pane, ex = tab.panes[0], tab.explorer
check("local tab opens with the shell", tab.state == "connected" and getattr(tab, "profile", None) is prof)
check("the shell reports its folder", wait(lambda: pane.cwd == vroot, 20), (pane.cwd, vroot))
check("the explorer shows this computer's files there", wait(lambda: ex.cwd == vroot and ex.item_count() >= 3, 15)
      and ex.is_local, (ex.cwd, ex.item_count()))
check("no upload/download buttons for this computer", ex.upload_btn.isHidden() and ex.download_btn.isHidden())
pane.send_text(("cd sub" if WIN else "cd sub") + "\r")
check("cd in the shell moves the explorer", wait(lambda: ex.cwd == vroot + "/sub", 15), ex.cwd)
ex.navigate(vroot + "/renamed")
check("opening a folder in the explorer moves the shell", wait(lambda: pane.cwd == vroot + "/renamed", 15), pane.cwd)
check("the title bar shows the shell's own path", (to_native(vroot + "/renamed") if WIN else vroot + "/renamed")
      in pane.frame.bar._full, pane.frame.bar._full)

# split: another shell of the same kind
tab.split_pane(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.Orientation.Horizontal)
check("split starts another local shell", wait(lambda: len(tab.panes) == 2 and tab.panes[1].chan is not None, 10))
tab.close_pane(tab.panes[1])

# drag & drop with a server's explorer: a server's items dropped here are downloaded into this folder
class FakeRemote:
    _internal_drop = None
ex.navigate(vroot)
wait(lambda: ex.cwd == vroot)
src = FakeRemote()
ex._on_remote_dropped(src, None)
check("a server's items dropped here go to this computer's folder", src._internal_drop is not None
      and src._internal_drop[0] == (to_native(vroot) if WIN else vroot) and src._internal_drop[1] is ex,
      src._internal_drop)

# delete goes to the Recycle Bin (Trash)
trash_me = os.path.join(root, "trash-me.txt")
open(trash_me, "w", encoding="utf-8").write("x")
wait(lambda: ex._find_item(vroot + "/trash-me.txt") is not None, 5)
ex._trash([vroot + "/trash-me.txt"])
check("delete moves to the Recycle Bin", not os.path.exists(trash_me))
check("... and it is gone from the explorer", wait(lambda: ex._find_item(vroot + "/trash-me.txt") is None, 5))
# in an opened subfolder too
sub_item = ex._find_item(vroot + "/sub")
sub_item.setExpanded(True)
check("subfolder opened in place", wait(lambda: ex._find_item(vroot + "/sub/b.txt") is not None, 10))
ex._trash([vroot + "/sub/b.txt"])
check("deleting inside an opened subfolder updates it", wait(lambda: ex._find_item(vroot + "/sub/b.txt") is None, 5))
# a refresh keeps the selection (it does not jump to the current folder)
for i in range(30):
    open(os.path.join(root, f"f{i:02d}.txt"), "w", encoding="utf-8").write("x")
ex.refresh()
wait(lambda: ex._find_item(vroot + "/f29.txt") is not None, 5)
pick = ex._find_item(vroot + "/f20.txt")
ex.tree.clearSelection()
ex.tree.setCurrentItem(pick)
pick.setSelected(True)
ex.tree.verticalScrollBar().setValue(ex.tree.verticalScrollBar().maximum())
before = ex.tree.verticalScrollBar().value()
ex.refresh()
wait(lambda: False, 1.0)
sel = [it.data(0, 0x0100) for it in ex.tree.selectedItems()]
check("refresh keeps the selected file", sel == [vroot + "/f20.txt"], sel)
check("... and the scroll position", ex.tree.verticalScrollBar().value() == before,
      (ex.tree.verticalScrollBar().value(), before))
check("... and the location", ex.cwd == vroot, ex.cwd)
open(os.path.join(root, "zz-new.txt"), "w", encoding="utf-8").write("x")
wait(lambda: ex._find_item(vroot + "/zz-new.txt") is not None, 5)
sel = [it.data(0, 0x0100) for it in ex.tree.selectedItems()]
check("an automatic refresh keeps it too", sel == [vroot + "/f20.txt"], sel)
ex.navigate(vroot + "/sub")
wait(lambda: ex.cwd == vroot + "/sub")
ex.navigate(vroot)
wait(lambda: ex.cwd == vroot and ex._cwd_item is not None)
check("moving to a folder still selects that folder", ex.tree.currentItem() is ex._cwd_item)

# a folder picked with a click (current, still folded) stays folded when the list refreshes
folded = ex._find_item(vroot + "/renamed")
folded.setExpanded(False)
ex.tree.setCurrentItem(folded)
check("clicked folder becomes the location, folded", ex.cwd == vroot + "/renamed" and not folded.isExpanded())
os.remove(os.path.join(root, "f00.txt"))
check("file deleted elsewhere disappears", wait(lambda: ex._find_item(vroot + "/f00.txt") is None, 5))
wait(lambda: False, 0.5)
again = ex._find_item(vroot + "/renamed")
check("... and the clicked folder stays folded and selected", again is not None and not again.isExpanded()
      and ex.tree.currentItem() is again, (again.isExpanded() if again else None))
ex.navigate(vroot)
wait(lambda: ex.cwd == vroot)

# changes made elsewhere (the shell, Explorer/Finder) show up by themselves
open(os.path.join(root, "made-elsewhere.txt"), "w", encoding="utf-8").write("x")
check("a file made elsewhere appears", wait(lambda: ex._find_item(vroot + "/made-elsewhere.txt") is not None, 5))
os.remove(os.path.join(root, "made-elsewhere.txt"))
check("a file deleted elsewhere disappears", wait(lambda: ex._find_item(vroot + "/made-elsewhere.txt") is None, 5))

# the session list: "This computer" with its shells
check("session list has 'This computer'", wait(lambda: any(
    w.session_tree.topLevelItem(i).text(0) == "This computer" for i in range(w.session_tree.topLevelItemCount())), 10))

# the shell ends: the tab offers to start it again
pane.send_text("exit\r")
check("the shell ending is shown", wait(lambda: tab.state == "closed", 15))
tab.connect()
check("... and it starts again", wait(lambda: tab.state == "connected" and pane.chan is not None
                                      and not pane.disconnected, 10))

# recent list on Home: the shell opened is there, newest first, and opens again from there
check("opened shell recorded as recent", w.settings.get("recent", [None])[0] == "local:" + prof.key(),
      w.settings.get("recent"))
w.home.start.refresh()
cards = [w.home.start.recent_grid.itemAt(i).widget() for i in range(w.home.start.recent_grid.count())]
check("Home shows it as a recent card", bool(cards) and cards[0].text().startswith(prof.name)
      and "This computer" in cards[0].text(), [c.text() for c in cards])
n_tabs = len(w.session_tabs())
cards[0].click()
check("... which opens a local terminal", wait(lambda: len(w.session_tabs()) == n_tabs + 1
                                                and getattr(w.current_tab(), "profile", None) is not None, 10))

# own shells (Settings)
from jeopsokheyou.localtab import LocalShellsDialog  # noqa: E402
d = LocalShellsDialog(w.settings, w)
d.custom.append(ShellProfile("Mine", localshell.guess_kind(prof.argv), list(prof.argv), custom=True, id="mine"))
d.default = "mine"
d._ok()
check("own shells are kept and can be the default", localshell.default_profile(w.settings).name == "Mine"
      and any(p.name == "Mine" and p.custom for p in localshell.profiles(w.settings)))

w.settings["confirm_quit"] = False
w.close()
print("DONE")
