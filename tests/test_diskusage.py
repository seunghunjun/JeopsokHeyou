# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Server disk space: mount parsing, statvfs over SFTP, thresholds, and the explorer capsule / card /
low-space banner against the fake server. Nothing here may run a command or scan on the server."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "disk")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
sys.path.insert(0, os.path.dirname(TESTS))

from paramiko.message import Message  # noqa: E402
from paramiko.sftp import CMD_EXTENDED, CMD_EXTENDED_REPLY  # noqa: E402

from jeopsokheyou import diskusage  # noqa: E402

GB = 1024 ** 3


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


# ---------------------------------------------------------------- mount list
MOUNTS = "\n".join([
    "proc /proc proc rw 0 0",
    "sysfs /sys sysfs rw 0 0",
    "tmpfs /run tmpfs rw 0 0",
    "overlay /var/lib/docker/overlay2/x/merged overlay rw 0 0",
    "/dev/sda1 / ext4 rw 0 0",
    "/dev/sdb1 /data xfs rw 0 0",
    "/dev/sdb1 /srv/bind xfs rw 0 0",                    # bind mount of the same disk
    "/dev/loop3 /snap/core/1 squashfs ro 0 0",
    "/dev/sdc1 /mnt/My\\040Disk ext4 rw 0 0",            # space escaped as \040
    "pool/data /tank zfs rw 0 0",
    "192.0.2.50:/vol1 /mnt/nas nfs4 rw 0 0",
    "//192.0.2.51/share /mnt/smb cifs rw 0 0",
    "user@192.0.2.52:/ /mnt/ssh fuse.sshfs rw 0 0",
    "short",
])
disks = diskusage.parse_mounts(MOUNTS)
local = [d.mount for d in disks if not d.network]
net = [d.mount for d in disks if d.network]
check("virtual file systems dropped, root first", local == ["/", "/data", "/mnt/My Disk", "/tank"], local)
check("network shares listed but marked", sorted(net) == ["/mnt/nas", "/mnt/smb", "/mnt/ssh"], net)
check("bind mount counted once", local.count("/data") == 1 and "/srv/bind" not in local)


# ---------------------------------------------------------------- statvfs over a fake SFTP client
def reply(total_blocks, free_blocks, avail_blocks, frsize=4096):
    m = Message()
    for v in (4096, frsize, total_blocks, free_blocks, avail_blocks, 0, 0, 0, 0, 0, 255):
        m.add_int64(v)
    return Message(m.asbytes())


class FakeFile:
    def __init__(self, data):
        self.data = data

    def read(self, n):
        out, self.data = self.data[:n], self.data[n:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSftp:
    def __init__(self, mounts, sizes, supported=True):
        self.mounts, self.sizes, self.supported = mounts, sizes, supported
        self.asked: list[str] = []
        self.opened: list[str] = []
        self.other: list = []

    def open(self, path, mode):
        self.opened.append(path)
        if self.mounts is None or "w" in mode or "a" in mode:
            raise IOError("no such file")
        return FakeFile(self.mounts.encode())

    def _request(self, t, *args):
        if t != CMD_EXTENDED or args[0] != "statvfs@openssh.com":
            self.other.append((t, args))
            raise IOError("unexpected request")
        if not self.supported:
            raise IOError("Operation unsupported")
        self.asked.append(args[1])
        total, free, avail = self.sizes[args[1]]
        return CMD_EXTENDED_REPLY, reply(total, free, avail)


blocks = GB // 4096
sizes = {"/": (50 * blocks, 30 * blocks, 29 * blocks), "/data": (1000 * blocks, 210 * blocks, 200 * blocks),
         "/mnt/My Disk": (20 * blocks, 2 * blocks, 1 * blocks), "/tank": (100 * blocks, 50 * blocks, 50 * blocks)}
f = FakeSftp(MOUNTS, sizes)
s = diskusage.query(f, "/home/tester")
check("only local disks asked, network shares never", sorted(f.asked) == sorted(sizes), f.asked)
check("nothing but reading the mount list and statvfs", f.other == [] and f.opened == ["/proc/self/mounts"],
      (f.other, f.opened))
d = {x.mount: x for x in s.disks}
check("sizes from statvfs", d["/"].total == 50 * GB and d["/"].avail == 29 * GB and d["/"].used == 20 * GB,
      (d["/"].total, d["/"].used, d["/"].avail))
check("free share counted like df", abs(d["/data"].free_pct - 200 / (790 + 200) * 100) < 0.01, d["/data"].free_pct)
check("totals add up local disks only", s.total == 1170 * GB and s.avail == 280 * GB, (s.total, s.avail))
check("worst disk found", s.worst().mount == "/mnt/My Disk", s.worst().mount)
check("network disks kept in the list for the card", len(s.disks) == 7 and len(s.measured) == 4)

f = FakeSftp(MOUNTS, sizes, supported=False)
check("server without the extension: nothing shown", diskusage.query(f, "/home/tester") is None)
check("...and only one ask was tried", len(f.other) == 0 and f.asked == [])

f = FakeSftp(None, {"/": (10 * blocks, 5 * blocks, 5 * blocks), "/home/tester": (10 * blocks, 5 * blocks, 5 * blocks)})
s = diskusage.query(f, "/home/tester")
check("no /proc: root and home, same disk counted once", s is not None and [x.mount for x in s.disks] == ["/"],
      s and [x.mount for x in s.disks])

check("levels", (diskusage.level(50, 10, 5), diskusage.level(7, 10, 5), diskusage.level(3, 10, 5))
      == ("ok", "warn", "crit"))

# ---------------------------------------------------------------- widgets
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou import diskui, theme  # noqa: E402

theme.manager.apply(app, "light")
check("thresholds sanitised", diskui.thresholds({"disk_warn_pct": 80, "disk_crit_pct": 90}) == (50.0, 50.0)
      and diskui.thresholds({"disk_warn_pct": "x"}) == (10, 5) and diskui.thresholds({}) == (10, 5))
check("size text", (diskui.size_text(204 * GB), diskui.size_text(int(1.4 * GB)), diskui.size_text(1024 ** 4))
      == ("204 GB", "1.4 GB", "1 TB"), (diskui.size_text(204 * GB), diskui.size_text(int(1.4 * GB))))

summary = diskusage.query(FakeSftp(MOUNTS, sizes), "")
pill = diskui.DiskPill()
pill.set_summary(summary, 10, 5)
check("pill level follows the worst disk (5.3% free)", pill.level() == "warn")
pill.set_summary(summary, 3, 1)
check("user thresholds respected", pill.level() == "ok")
pill.show()
pill.resize(pill.sizeHint())
img_full = pill.grab()
pill.resize(pill.minimumSizeHint())
img_short = pill.grab()
check("pill paints full and compact", not img_full.isNull() and not img_short.isNull()
      and pill.minimumSizeHint().width() < pill.sizeHint().width())
cache = os.path.join(SP, "cache.json")
from pathlib import Path  # noqa: E402

diskusage.save_last("a", summary, Path(cache), now=1000.0)
diskusage.save_last("b", summary, Path(cache), now=2000.0)
got = diskusage.load_last(Path(cache))
check("cache keeps the lowest disk per host", set(got) == {"a", "b"} and got["a"]["mount"] == "/mnt/My Disk"
      and got["a"]["time"] == 1000.0, got.get("a"))
diskusage.forget_last(["a"], Path(cache))
check("cache entry forgotten", set(diskusage.load_last(Path(cache))) == {"b"})
open(cache, "w", encoding="utf-8").write("{broken")
check("broken cache file is ignored", diskusage.load_last(Path(cache)) == {})
check("relative time", (diskui.ago_text(100, 130), diskui.ago_text(0, 600), diskui.ago_text(0, 7300),
                        diskui.ago_text(0, 3 * 86400 + 5)) == ("just now", "10 min ago", "2 h ago", "3 days ago"))
card = diskui.DiskCard()
card.fill("web-01", summary, 10, 5, time.time())
check("card has a row per disk", card.rows.count() == len(summary.disks))
theme.manager.apply(app, "dark")
card.show_at(pill)
check("card paints in dark mode", not card.grab().isNull())
card.hide()

# ---------------------------------------------------------------- explorer + banner against the fake server
root = os.path.join(SP, "srvroot")
os.makedirs(os.path.join(root, "home", "tester"), exist_ok=True)
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, TESTS)
from _util import stop_server  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)   # trust the test host key

def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


try:
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    sess = Session(host="127.0.0.1", port=2299, user="tester", name="disk-test")
    w.store.upsert(sess)
    w.open_session(sess, "pw")
    tab = w.current_tab()
    ex = tab.explorer
    check("connected", wait(lambda: tab.state == "connected"))
    wait(lambda: ex.tree.topLevelItemCount() >= 0 and ex.cwd != "", 8)
    wait(lambda: False, 0.8)
    # the fake server (like some real ones) does not support statvfs: hidden, no error shown
    check("unsupported server: capsule hidden", not ex.disk_pill.isVisible() and ex.disk_summary is None)
    check("unsupported server: no error in the status bar", "Error" not in ex.info.text(), ex.info.text())
    check("unsupported server: no banner", not tab.disk_banner.isVisible())

    # now a server that answers: low space on one disk
    real_read, real_stat = diskusage.read_mounts, diskusage.statvfs
    diskusage.read_mounts = lambda sftp: "/dev/sda1 / ext4 rw 0 0\n/dev/sdb1 /var/log ext4 rw 0 0\n"
    answers = {"/": (100 * GB, 40 * GB, 60 * GB), "/var/log": (20 * GB, int(18.6 * GB), int(1.4 * GB))}
    diskusage.statvfs = lambda sftp, path: answers.get(path)
    ex.refresh_disk()
    check("capsule shown", wait(lambda: ex.disk_pill.isVisible()))
    check("banner shown for the low disk", wait(lambda: tab.disk_banner.isVisible())
          and "/var/log" in tab.disk_label.text(), tab.disk_label.text())
    check("banner level is warn (7% free, 10/5 defaults)", tab.disk_banner.property("level") == "warn")
    ex.show_disk_card()
    check("card opens with both disks", ex._disk_card.isVisible() and ex._disk_card.rows.count() == 2)
    ex._disk_card.hide()
    # user lowers the warning level -> banner goes away, capsule stays
    w.settings["disk_warn_pct"], w.settings["disk_crit_pct"] = 5, 2
    tab.update_disk_banner()
    ex.apply_disk_settings()
    check("user threshold hides the banner", not tab.disk_banner.isVisible() and ex.disk_pill.isVisible())
    w.settings["disk_warn_pct"], w.settings["disk_crit_pct"] = 10, 8
    tab.update_disk_banner()
    check("critical level turns the banner red", tab.disk_banner.isVisible()
          and tab.disk_banner.property("level") == "crit")
    # host card: last value kept on this PC, shown only when the option is on
    last = diskusage.load_last()
    check("last value saved locally for the host card", sess.id in last and last[sess.id]["mount"] == "/var/log",
          last.get(sess.id))
    w.show_home("hosts")
    hp = w.home.hosts
    hp.refresh()
    check("host card: badge shown by default", len(hp.cards[sess.id].findChildren(diskui.DiskBadge)) == 1)
    w.settings["disk_card"] = False
    hp.refresh()
    check("host card: no badge when the option is off", not hp.cards[sess.id].findChildren(diskui.DiskBadge))
    w.settings["disk_card"] = True
    hp.refresh()
    badges = hp.cards[sess.id].findChildren(diskui.DiskBadge)
    check("host card: badge with the lowest disk", len(badges) == 1 and round(badges[0].free_pct) == 7
          and badges[0].lv == "crit", badges and (badges[0].free_pct, badges[0].lv))
    check("host card: tooltip says when it was checked", "/var/log" in badges[0].toolTip(), badges[0].toolTip())
    w.settings["disk_show"] = False
    hp.refresh()
    check("host card: hidden when disk space is turned off", not hp.cards[sess.id].findChildren(diskui.DiskBadge))
    w.settings["disk_show"] = True
    w.tabs.setCurrentWidget(tab)
    tab._dismiss_disk_banner()
    tab.update_disk_banner()
    check("dismissed banner stays hidden", not tab.disk_banner.isVisible())
    w.settings["disk_show"] = False
    ex.apply_disk_settings()
    check("turning the feature off hides the capsule", not ex.disk_pill.isVisible())
    w.settings["disk_show"] = True
    ex.apply_disk_settings()
    tab.panes[0].send_text("exit\r")
    check("disconnect clears the capsule", wait(lambda: tab.state == "closed") and not ex.disk_pill.isVisible())
    diskusage.read_mounts, diskusage.statvfs = real_read, real_stat
    w.store.remove(sess.id)
    check("deleting the host forgets its disk values", sess.id not in diskusage.load_last())
    w.close()
finally:
    stop_server(srv)

# settings dialog round trip
from jeopsokheyou.dialogs import SettingsDialog  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402

dlg = SettingsDialog({"disk_warn_pct": 15, "disk_crit_pct": 30, "disk_banner": False}, QFont("Consolas", 11))
v = dlg.values()
check("settings dialog: values", (v["disk_show"], v["disk_banner"], v["disk_warn_pct"], v["disk_crit_pct"])
      == (True, False, 15, 15), (v["disk_show"], v["disk_banner"], v["disk_warn_pct"], v["disk_crit_pct"]))
dlg.disk_show.setChecked(False)
check("settings dialog: options disabled with the feature", not dlg.disk_banner.isEnabled())
dlg.reject()
print("DONE")
