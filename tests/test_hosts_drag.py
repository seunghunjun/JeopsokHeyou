# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Hosts screen: drag hosts and groups onto groups (tree, group cards, path, All hosts)."""
import os
import shutil
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "hostsdrag")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
from jeopsokheyou import home  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402

QMessageBox.information = staticmethod(lambda *a, **k: None)


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def pump(sec=0.15):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


MOVE = Qt.DropAction.MoveAction
LB = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier


def send_drop(widget, payload, pos=None):
    """Drag enter + move + drop on a widget; returns whether the move was accepted."""
    mime = home.drag_payload(*payload)
    p = pos if pos is not None else widget.rect().center()
    enter = QDragEnterEvent(p, MOVE, mime, LB, NOMOD)
    QApplication.sendEvent(widget, enter)
    move = QDragMoveEvent(p, MOVE, mime, LB, NOMOD)
    QApplication.sendEvent(widget, move)
    accepted = move.isAccepted()
    drop = QDropEvent(QPointF(p), MOVE, mime, LB, NOMOD)
    QApplication.sendEvent(widget, drop)
    pump()
    return accepted and drop.isAccepted()


w = MainWindow()
w.resize(1300, 800)
w.show()
st = w.store
a = Session(host="192.0.2.1", name="web-a", group="Dev")
b = Session(host="192.0.2.2", name="web-b", group="Dev")
c = Session(host="192.0.2.3", name="db-c", group="Prod / DB")
d = Session(host="192.0.2.4", name="loose")
for s in (a, b, c, d):
    st.upsert(s)
st.add_group("Staging")
w.reload_sessions()
w.show_home("hosts")
hp = w.home.hosts
hp.open_group("")
pump()

# store
check("move_group refuses moving into itself", st.move_group("Prod", "Prod / DB") is None)
check("move_group to the same place is a no-op", st.move_group("Dev", "") is None)

# can_drop
check("can drop a host on another group", hp.can_drop(([a.id], []), "Prod"))
check("nothing to do -> not allowed", not hp.can_drop(([a.id], []), "Dev"))
check("group into its own subgroup -> not allowed", not hp.can_drop(([], ["Prod"]), "Prod / DB"))

# card: click happens on release, a drag never clicks
card = hp.cards[a.id]
clicked, dragged = [], []
card.clicked.connect(lambda: clicked.append(1))
card.drag_requested.connect(lambda: dragged.append(1))
QTest.mousePress(card, LB, NOMOD, QPoint(20, 20))
check("press alone is not a click", clicked == [])
QTest.mouseRelease(card, LB, NOMOD, QPoint(20, 20))
check("press + release is a click", clicked == [1] and dragged == [])
real_start = hp.start_drag
hp.start_drag = lambda *a_, **k: None            # QDrag.exec would block in a test
QTest.mousePress(card, LB, NOMOD, QPoint(20, 20))
QTest.mouseMove(card, QPoint(80, 40))
QTest.mouseRelease(card, LB, NOMOD, QPoint(80, 40))
check("moving the mouse starts a drag, not a click", dragged == [1] and clicked == [1], (dragged, clicked))
hp.start_drag = real_start

# host card -> group card
hp.refresh()
pump()
group_card = next(cc for cc in hp.groups_flow.widgets() if cc.title.text() == "Staging") \
    if hasattr(hp.groups_flow, "widgets") else None
if group_card is None:
    group_card = [hp.groups_box.findChildren(home.Card)[i] for i in range(len(hp.groups_box.findChildren(home.Card)))
                  if hp.groups_box.findChildren(home.Card)[i].title.text() == "Staging"][0]
check("drop a host on a group card", send_drop(group_card, ([a.id], [])) and st.get(a.id).group == "Staging",
      st.get(a.id).group)

# group card -> another group card (group with subgroups and hosts moves along)
pump()
cards = {cc.title.text(): cc for cc in hp.groups_box.findChildren(home.Card)}
check("drop a group on a group card", send_drop(cards["Staging"], ([], ["Prod"]))
      and st.get(c.id).group == "Staging / Prod / DB", st.get(c.id).group)
check("moved group listed under its new parent", "Staging / Prod" in st.groups() and "Prod" not in st.groups())

# not allowed: group into itself
pump()
cards = {cc.title.text(): cc for cc in hp.groups_box.findChildren(home.Card)}
check("dropping a group onto itself is refused", not send_drop(cards["Staging"], ([], ["Staging"])))

# tree: host onto a group item, and onto empty space (top level)
hp.refresh()
pump()
tree = hp.tree


def tree_item(text):
    return tree.findItems(text, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)[0]


dev = tree_item("Dev")
pos = tree.visualItemRect(dev).center()
check("drop a host on a group in the tree", send_drop(tree.viewport(), ([d.id], []), pos)
      and st.get(d.id).group == "Dev", st.get(d.id).group)
empty = QPoint(10, tree.viewport().height() - 5)
send_drop(tree.viewport(), ([d.id], ["Dev"]), empty)
pump()
check("drop on empty tree space -> top level (host and group)", st.get(d.id).group == ""
      and st.get(b.id).group == "Dev" and "Dev" in st.groups(), (st.get(d.id).group, st.groups()))
hp.refresh()
pump()
staging_prod = tree_item("Prod")
send_drop(tree.viewport(), ([b.id], []), tree.visualItemRect(staging_prod).center())
pump()
check("drop on a subgroup in the tree", st.get(b.id).group == "Staging / Prod", st.get(b.id).group)

# breadcrumb and All hosts
hp.open_group("Staging / Prod / DB")
pump()
crumbs = {btn.text(): btn for btn in hp.crumb_buttons()}
check("path buttons accept drops", send_drop(crumbs["Staging"], ([c.id], []))
      and st.get(c.id).group == "Staging", st.get(c.id).group)
check("All hosts accepts drops (top level)", send_drop(hp.all_hosts_btn, ([c.id], [])) and st.get(c.id).group == "")

# the open group follows when it is moved
hp.open_group("Staging / Prod")
pump()
w.move_items([], ["Staging / Prod"], "")
pump()
check("open group follows its move", hp.group == "Prod", hp.group)

# name clash: refused with a message, nothing lost
st.add_group("Dev / Prod")
w.move_items([], ["Dev / Prod"], "")
check("same name at the target -> not moved", "Dev / Prod" in st.groups() and "Prod" in st.groups())

# Ctrl+click only selects (no navigation)
hp.open_group("")
pump()
it = tree_item("Dev")
QTest.mouseClick(tree.viewport(), LB, Qt.KeyboardModifier.ControlModifier, tree.visualItemRect(it).center())
pump()
check("Ctrl+click in the tree does not open the group", hp.group == "")

# last connection on host cards (from the connection history)
from jeopsokheyou import library  # noqa: E402

now = time.time()
check("when: recent is relative", home.when_text(now - 3 * 86400, now) == "3 days ago")
check("when: same year shows month/day", "/" in home.when_text(now - 40 * 86400, now)
      or "-" in home.when_text(now - 40 * 86400, now))
check("when: older years show the full date", home.when_text(now - 800 * 86400, now).count("-") == 2)
check("no note before any connection", hp.cards[a.id].note is None)
library.add_history(st.get(a.id))
hp.refresh()
note = hp.cards[a.id].note
check("note after a connection", note is not None and note.text() == "just now"
      and note.toolTip().startswith("Last connected:"), note and note.text())
check("other hosts without a note", hp.cards[b.id].note is None)
w.settings["card_last_connected"] = False
hp.refresh()
check("can be turned off", hp.cards[a.id].note is None)
w.settings["card_last_connected"] = True

# group colors: top-level groups never share a color automatically; a picked color wins and moves along
from jeopsokheyou import config as cfg  # noqa: E402

VERIFY = chr(44160) + chr(51613)   # Korean group name
OPS = chr(50868) + chr(50689)   # Korean group name
DEVK = chr(44060) + chr(48156)   # Korean group name
for name in (VERIFY, OPS, DEVK, "Alpha", "Beta"):
    st.add_group(name)
tops = sorted({g.split(cfg.GROUP_SEP)[0] for g in st.groups()}, key=str.lower)
auto = [st.group_color(t) for t in tops]
check("automatic colors differ between top-level groups", len(set(auto)) == min(len(tops), 8), (tops, auto))
check("subgroups use the top-level color", st.group_color("Staging") == st.group_color("Staging"))
st.add_group(OPS + " / DB")
check("subgroup follows its parent", st.group_color(OPS + " / DB") == st.group_color(OPS))
check("no group is gray", st.group_color("") == cfg.NO_GROUP_COLOR)
w.set_group_color(OPS, "#FF375F")
check("picked color used", st.group_color(OPS) == "#FF375F" and st.group_color(OPS + " / DB") == "#FF375F")
x = Session(host="192.0.2.50", name="ops-1", group=OPS + " / DB")
st.upsert(x)
hp.open_group("")
hp.refresh()
pump()
check("host card tile uses the group color", "#FF375F" in hp.cards[x.id].findChild(home.QLabel, "Tile").styleSheet())
st.rename_group(OPS, "Operations")
check("color follows a rename", st.group_color("Operations / DB") == "#FF375F")
st.move_group("Operations", "Alpha")
check("color follows a move", st.group_color("Alpha / Operations") == "#FF375F")
reloaded = cfg.SessionStore(st.path)
check("color saved", reloaded.group_colors.get("Alpha / Operations") == "#FF375F")
w.set_group_color("Alpha / Operations", "")
check("Automatic clears it", "Alpha / Operations" not in st.group_colors)
st.remove_group("Alpha")
check("deleting a group forgets its colors", not any(k.startswith("Alpha") for k in st.group_colors))
w.close()
print("DONE")
