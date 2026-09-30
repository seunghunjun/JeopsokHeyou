# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
import os, sys, shutil
from pathlib import Path
TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")   # test work folder (git-ignored)
os.makedirs(SP, exist_ok=True)
REAL_TABBY = Path(TESTS) / "fixtures" / "tabby-config.yaml"   # sample config (no real server info)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
sys.path.insert(0, os.path.join(os.path.dirname(TESTS)))
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog, QTreeWidget
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
from jeopsokheyou import config
from jeopsokheyou.config import Session, SessionStore
from jeopsokheyou.mainwindow import MainWindow, GROUP_ROLE

def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)

# 1) Tabby import (sample config file, read-only)
found = config.import_tabby_sessions(REAL_TABBY)
check("6 Tabby profiles", len(found) == 6, len(found))
groups = sorted({s.group for s in found})
check("group id -> name", all(len(s.group) != 36 for s in found) and groups == ["Development", "Production", "Staging"], groups)
check("default user root, port 22", all(s.user == "root" and s.port == 22 for s in found))
check("no passwords included", all(not s.password_enc for s in found))
print("   e.g.:", [(s.name, s.host, s.group) for s in found][:3])

# 2) Group store
w = MainWindow(); w.show()
st = w.store
st.sessions += [Session(name="A", host="a"), Session(name="B", host="b", group="Production"), Session(name="C", host="c", group="Production")]
st.save()
check("add empty group", st.add_group("Development") and "Development" in st.groups())
check("duplicate group rejected", not st.add_group("Development"))
ida = next(s.id for s in st.sessions if s.name == "A")
idb = next(s.id for s in st.sessions if s.name == "B")
idc = next(s.id for s in st.sessions if s.name == "C")
st.move_sessions([ida], "Development")
check("move session -> group", st.get(ida).group == "Development")
st.move_sessions([idb, idc], "")
check("group kept after its last session leaves", "Production" in st.groups(), st.groups())
st.rename_group("Development", "Dev servers")
check("rename group (sessions follow)", st.get(ida).group == "Dev servers" and "Development" not in st.groups())
moved = st.remove_group("Dev servers")
check("delete group -> sessions move out of it", moved == 1 and st.get(ida).group == "" and st.get(ida) is not None)
st2 = SessionStore(st.path)
check("empty group kept after restart", "Production" in st2.groups() and "Dev servers" not in st2.groups(), st2.groups())

# 3) Drop position -> target group
st.move_sessions([idb], "Production"); w.reload_sessions()
tree = w.session_tree
g_item = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0, GROUP_ROLE) == "Production")
b_item = g_item.child(0)
Pos = QTreeWidget.DropIndicatorPosition
check("drop on group -> into group", tree.target_group(g_item, Pos.OnItem) == "Production")
check("drop between groups -> no group", tree.target_group(g_item, Pos.AboveItem) == "")
check("next to a session in a group -> that group", tree.target_group(b_item, Pos.BelowItem) == "Production")
check("empty area -> no group", tree.target_group(None, Pos.OnViewport) == "")
check("group items not draggable", not (g_item.flags() & g_item.flags().ItemIsDragEnabled))

# 4) Drop signal -> store updated + redrawn
tree.sessions_dropped.emit([ida, idc], "Production")
check("drag multiple sessions -> group updated", st.get(ida).group == "Production" and st.get(idc).group == "Production")
check("tree shows 3", g_item is not None and next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0, GROUP_ROLE) == "Production").childCount() == 3)

# 5) Menu actions: add/rename group (input dialog stubbed)
QInputDialog.getText = staticmethod(lambda *a, **k: ("Test group", True))
w.add_group(); check("menu: add group", "Test group" in st.groups())
QInputDialog.getText = staticmethod(lambda *a, **k: ("Renamed group", True))
w.rename_group("Test group"); check("menu: rename", "Renamed group" in st.groups() and "Test group" not in st.groups())
w.remove_group("Renamed group"); check("menu: delete group", "Renamed group" not in st.groups())
QInputDialog.getText = staticmethod(lambda *a, **k: ("New group", True))
w.add_group(move_ids=[ida]); check("menu: new group and move", st.get(ida).group == "New group")

# 6) Empty groups hidden while searching
st.add_group("Empty group"); w.filter.setText("b")
hidden = [tree.topLevelItem(i).isHidden() for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).data(0, GROUP_ROLE) == "Empty group"]
check("groups without matches hidden while searching", hidden == [True])
w.close(); print("DONE")
