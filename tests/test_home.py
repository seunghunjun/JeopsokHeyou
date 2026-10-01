# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Home tab: menu pages (Hosts, Keychain, Port Forwarding, Snippets, Known Hosts, History) and the version shown."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work")
os.makedirs(SP, exist_ok=True)
os.environ["APPDATA"] = os.path.join(SP, "appdata-home")
shutil.rmtree(os.environ["APPDATA"], ignore_errors=True)
root = os.path.join(SP, "srvroot-home")
os.makedirs(root, exist_ok=True)
srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
sys.path.insert(0, os.path.dirname(TESTS))
from _util import stop_server  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
from jeopsokheyou import __version__, home, library  # noqa: E402
from jeopsokheyou.config import Session, SessionStore  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow, SessionTab, apply_dark_theme  # noqa: E402


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


apply_dark_theme(app)
w = MainWindow()
w.resize(1200, 760)
w.show()
wait(lambda: False, 0.2)
check("version in the window title", w.windowTitle() == f"JeopsokHeyou {__version__}", w.windowTitle())
check("home is the first tab and cannot be closed", w.tabs.widget(0) is w.home and
      w.tabs.tabBar().tabButton(0, w.tabs.tabBar().ButtonPosition.RightSide) is None)
check("no session list panel on Home", not w.sessions_dock.isVisible())
check("menu pages", [w.home.nav.item(i).data(home.Qt.ItemDataRole.UserRole) for i in range(w.home.nav.count())] ==
      ["start", "hosts", "keychain", "forwarding", "snippets", "known_hosts", "history"])
check("Home opens on the start page (1.0.x start screen)", w.home.stack.currentWidget() is w.home.start
      and w.home.start.findChild(home.QLabel, "Title").text() == "JeopsokHeyou")

# ---------------------------------------------------------------- Hosts
for n, g in (("prod-web", "Production"), ("prod-db", "Production"), ("lab", "")):
    w.store.upsert(Session(name=n, host="127.0.0.1", port=2299, user="tester", group=g))
w.store.get(next(s.id for s in w.store.sessions if s.name == "lab")).password = "pw"
w.store.save()
w.reload_sessions()
hp = w.home.hosts
w.show_home("hosts")
check("top level shows the groups and every host", hp.groups_flow.count() == 1 and
      sorted(w.store.get(i).name for i in hp.cards) == ["lab", "prod-db", "prod-web"])
check("grouped hosts show their group", "Production" in hp.cards[next(s.id for s in w.store.sessions
                                                                        if s.name == "prod-web")].subtitle.text())
hp.open_group("Production")
check("opening a group lists its hosts", hp.hosts_flow.count() == 2 and hp.groups_flow.count() == 0
      and hp.back.isVisibleTo(hp))
hp.back.click()
check("All hosts goes back to every host", hp.group == "" and len(hp.cards) == 3 and hp.groups_flow.count() == 1)
hp.open_group("Production")
w.home.nav.itemClicked.emit(w.home.nav.item(1))
check("clicking Hosts in the menu goes back to every host", hp.group == "" and len(hp.cards) == 3)
# subgroups: "New group" inside a group creates it there
from jeopsokheyou import mainwindow as mw  # noqa: E402
hp.open_group("Production")
real_get = mw.QInputDialog.getText
mw.QInputDialog.getText = staticmethod(lambda *a, **k: ("DB", True))
next(b for b in hp.findChildren(home.QPushButton) if b.text() == "New group").click()
check("new group inside a group becomes a subgroup", "Production / DB" in w.store.groups() and "DB" not in w.store.groups())
check("subgroup shown inside its parent", hp.group == "Production" and hp.groups_flow.count() == 1
      and hp.groups_flow.itemAt(0).widget().title.text() == "DB")
hp.open_group("")
check("top level shows only top-level groups", sorted(hp.groups_flow.itemAt(i).widget().title.text()
                                                       for i in range(hp.groups_flow.count())) == ["Production"])
prod_web = next(x for x in w.store.sessions if x.name == "prod-web")
w._move_sessions([prod_web.id], "Production / DB")
hp.open_group("Production / DB")
check("inside the subgroup: its hosts", [w.store.get(i).name for i in hp.cards] == ["prod-web"])
check("path shows every level and each can be clicked", [b.text() for b in hp.crumb_buttons()] == ["All hosts", "Production"])
next(b for b in hp.crumb_buttons() if b.text() == "All hosts").click()
wait(lambda: hp.group == "", 2)
check("clicking All hosts in the path goes to the top", hp.group == "")
hp.open_group("Production / DB")
next(b for b in hp.crumb_buttons() if b.text() == "Production").click()
wait(lambda: hp.group == "Production", 2)
check("clicking a level in the path goes there", hp.group == "Production")
hp.open_group("Production / DB")
hp.back.click()
check("back to the parent", hp.group == "Production")
hp.open_group("")
prod_card = next(hp.groups_flow.itemAt(i).widget() for i in range(hp.groups_flow.count())
                 if hp.groups_flow.itemAt(i).widget().title.text() == "Production")
check("group count includes its subgroups", prod_card.subtitle.text() == "2 hosts", prod_card.subtitle.text())
mw.QInputDialog.getText = staticmethod(lambda *a, **k: ("Databases", True))
w.rename_group("Production / DB")
check("rename keeps the subgroup under its parent", "Production / Databases" in w.store.groups()
      and w.store.get(prod_web.id).group == "Production / Databases")
mw.QInputDialog.getText = staticmethod(lambda *a, **k: ("Prod", True))
w.rename_group("Production")
check("renaming a parent renames its subgroups", "Prod / Databases" in w.store.groups()
      and w.store.get(prod_web.id).group == "Prod / Databases")
w.remove_group("Prod / Databases")
check("deleting a subgroup moves its hosts up to the parent", w.store.get(prod_web.id).group == "Prod"
      and "Prod / Databases" not in w.store.groups())
# group / host tree on the left of the Hosts page
hp.open_group("")
names = [hp.tree.topLevelItem(i).text(0) for i in range(hp.tree.topLevelItemCount())]
check("tree: groups and hosts under the All hosts row", hp.all_hosts_btn.text() == "All hosts"
      and hp.all_hosts_btn.isChecked() and "Prod" in names and "lab" in names, names)
prod_item = next(hp.tree.topLevelItem(i) for i in range(hp.tree.topLevelItemCount())
                 if hp.tree.topLevelItem(i).text(0) == "Prod")
kinds = [prod_item.child(i).data(0, hp.TREE_ROLE)[0] for i in range(prod_item.childCount())]
check("tree: a group's own hosts come before its subgroups", kinds == sorted(kinds, key=lambda k: k != "host"), kinds)
hp.tree.itemClicked.emit(prod_item, 0)
wait(lambda: hp.group == "Prod", 2)
check("clicking a group in the tree opens it", hp.group == "Prod")
check("tree highlights the open group", hp.tree.currentItem().text(0) == "Prod" and not hp.all_hosts_btn.isChecked())
host_item = next(it for it in hp._tree_items() if it.text(0) == "prod-web")
hp.tree.itemClicked.emit(host_item, 0)
wait(lambda: hp.selected_id, 2)
check("clicking a host in the tree selects it", not hp.panel.isVisible()
      and hp.selected_id == next(x.id for x in w.store.sessions if x.name == "prod-web"))
hp.close_panel()
prod_item = next(it for it in hp._tree_items() if it.text(0) == "Prod")
hp.tree.itemClicked.emit(prod_item, 0)
wait(lambda: hp.selected_id == "", 2)
check("choosing a group after a host moves the focus to the group", hp.tree.currentItem().text(0) == "Prod"
      and hp.selected_id == "", hp.tree.currentItem().text(0))
hp.all_hosts_btn.click()
wait(lambda: hp.group == "", 2)
check("All hosts row goes to the top level", hp.group == "" and hp.all_hosts_btn.isChecked()
      and hp.tree.currentItem() is None)

# hide button next to "All hosts" collapses the tree to a strip
hp.tree_hide_btn.click()
wait(lambda: not hp.tree_box.isVisible(), 2)
check("hide button next to All hosts collapses the tree", not hp.tree_box.isVisible() and hp.tree_strip.isVisible()
      and w.settings["show_host_tree"] is False)
hp.tree_expand_btn.click()
check("the strip's button brings the tree back", hp.tree_box.isVisible() and not hp.tree_strip.isVisible())

# right-click menu on empty space
hp.open_group("")
texts = [a.text() for a in hp.page_menu().actions() if a.text()]
check("empty-space menu at the top level", texts[:2] == ["New host", "New group"] and "Import" in texts, texts)
hp.open_group("Prod")
texts = [a.text() for a in hp.page_menu().actions() if a.text()]
check("empty-space menu inside a group", texts[:2] == ["New host", "New subgroup…"] and "Delete group" in texts
      and "Rename group…" in texts, texts)
next(a for a in hp.page_menu().actions() if a.text() == "New host").trigger()
check("New host from the menu uses the open group", hp.panel.isVisible() and
      hp.editor_dialog.group.currentText() == "Prod")
hp.close_panel()
mw.QInputDialog.getText = real_get
hp.open_group("")
hp.search.setText("db")
check("search finds hosts in any group", [w.store.get(i).name for i in hp.cards] == ["prod-db"])
hp.search.setText("nobody@192.0.2.55")
opened = []
real_open = w.open_session
w.open_session = lambda s, *a, **k: opened.append(s)
hp._enter()
check("Enter with no match quick-connects user@host", opened and opened[0].host == "192.0.2.55" and opened[0].user == "nobody")
w.open_session = real_open
hp.search.clear()
# edit panel
lab = next(s for s in w.store.sessions if s.name == "lab")
hp.edit(lab)
check("edit panel opens on the right", hp.panel.isVisible() and hp.editor_dialog is not None)
hp.editor_dialog.name.setText("lab-renamed")
hp.editor_dialog._accept()
wait(lambda: False, 0.1)
check("saving from the panel updates the host and closes it", SessionStore().get(lab.id).name == "lab-renamed"
      and not hp.panel.isVisible())
hp.edit(None)
hp.editor_dialog.host.setText("192.0.2.77")
hp.editor_dialog._accept()
check("new host from the panel", any(s.host == "192.0.2.77" for s in SessionStore().sessions))
hp.edit(lab)
hp.editor_dialog.reject()
check("cancel closes the panel", not hp.panel.isVisible())
# one click opens the panel; clicking another host swaps its details in; X closes it
from PySide6.QtTest import QTest  # noqa: E402
lab = w.store.get(lab.id)
db = next(s for s in w.store.sessions if s.name == "prod-db")
QTest.mouseClick(hp.cards[lab.id], home.Qt.MouseButton.LeftButton)
check("one click only selects (no edit panel)", not hp.panel.isVisible() and hp.cards[lab.id].property("selected") is True)
hp.cards[lab.id].edit_requested.emit()
check("Edit opens the edit panel", hp.panel.isVisible() and hp.editor_dialog.name.text() == "lab-renamed")
QTest.mouseClick(hp.cards[db.id], home.Qt.MouseButton.LeftButton)
check("clicking another host shows its details", hp.editor_dialog.name.text() == "prod-db"
      and hp.cards[db.id].property("selected") is True and hp.cards[lab.id].property("selected") is False)
hp.editor_dialog.name.setText("typing…")
QTest.mouseClick(hp.cards[db.id], home.Qt.MouseButton.LeftButton)
check("clicking the same host keeps what was typed", hp.editor_dialog.name.text() == "typing…")
hp.panel_close.click()
check("X closes the panel (the host stays selected)", not hp.panel.isVisible() and hp.cards[db.id].property("selected") is True)

# ---------------------------------------------------------------- connect: history + known hosts
lab = w.store.get(lab.id)
w.open_session(lab)
tab = w.current_tab()
check("connected from Hosts", wait(lambda: tab.state == "connected"), tab.state)
check("session list panel shown next to the terminal", w.sessions_dock.isVisible())
w.home_btn.click()
check("toolbar Home button goes to the start page", w.tabs.currentWidget() is w.home
      and w.home.stack.currentWidget() is w.home.start)
check("start page lists recent sessions", w.home.start.recent_grid.count() >= 1
      and w.home.start.recent_grid.itemAt(0).widget().text().startswith("lab"))
check("hidden again on Home", not w.sessions_dock.isVisible())
w.tabs.setCurrentWidget(tab)
w.sessions_collapse_btn.click()
check("hide button inside the session list collapses it to a strip", w.sessions_dock.isVisible()
      and w.sessions_stack.currentWidget() is w.sessions_strip and w.settings["show_sessions"] is False)
w.show_home()
w.tabs.setCurrentWidget(tab)
check("stays collapsed when coming back", w.sessions_stack.currentWidget() is w.sessions_strip)
w.sessions_expand_btn.click()
check("the strip's button brings it back", w.sessions_stack.currentWidget() is w.sessions_full
      and w.settings["show_sessions"] is True)
w.sessions_act.trigger()
check("Ctrl+Shift+S / View menu toggles it too", w.settings["show_sessions"] is False and not w.sessions_act.isChecked())
w.sessions_act.trigger()
check("inject done", wait(lambda: tab.panes[0]._inject_state == "done", 15))
hist = library.load_history()
check("history recorded", hist and hist[0]["session_id"] == lab.id)
w.show_home("history")
check("history page lists it", w.home.history.table.rowCount() >= 1 and
      w.home.history.table.item(0, 1).text() == "lab-renamed")
w.show_home("known_hosts")
kh = w.home.known_hosts.table
check("trusted host key listed", kh.rowCount() == 1 and "2299" in kh.item(0, 0).text(), kh.item(0, 0).text() if kh.rowCount() else "")

# ---------------------------------------------------------------- snippets
w.snippets.upsert(library.Snippet(name="say hi", command="echo snippet-ok", run=True))
w.show_home("snippets")
sp = w.home.snippets
check("snippet listed", sp.table.rowCount() == 1)
sp.table.selectRow(0)
sp.send_selected()
check("snippet goes to the last terminal and that tab is shown", w.tabs.currentWidget() is tab)
check("snippet ran in the terminal", wait(lambda: "snippet-ok" in "\n".join(tab.panes[0].screen.display)))
check("snippet text: newlines become Enter, Enter only when run",
      library.Snippet(command="a\nb\n", run=False).text_to_send() == "a\rb" and
      library.Snippet(command="ls", run=True).text_to_send() == "ls\r")
home.SnippetPicker.exec = lambda self: (setattr(self, "chosen", self.store.snippets[0]), QDialog.DialogCode.Accepted)[1]
tab.panes[0].send_text("clear\r")
w.pick_snippet()
check("snippet picker from the terminal", wait(lambda: "snippet-ok" in "\n".join(tab.panes[0].screen.display)))

# ---------------------------------------------------------------- known hosts: remove
w.show_home("known_hosts")
kh.selectRow(0)
w.home.known_hosts.remove()
check("known host removed", kh.rowCount() == 0 and library.known_hosts() == [])

# ---------------------------------------------------------------- keychain
library.SSH_DIR = Path(SP) / "home-ssh"
shutil.rmtree(library.SSH_DIR, ignore_errors=True)
line = library.generate_ed25519(library.SSH_DIR / "id_test", "", "test")
check("ed25519 key generated", line.startswith("ssh-ed25519 ") and (library.SSH_DIR / "id_test").exists())
try:
    library.generate_ed25519(library.SSH_DIR / "id_test")
    check("never overwrites a key", False)
except FileExistsError:
    check("never overwrites a key", True)
check("public key read back", library.public_key(library.SSH_DIR / "id_test") == line)
enc = library.generate_ed25519(library.SSH_DIR / "id_enc", "secret phrase")
os.remove(str(library.SSH_DIR / "id_enc") + ".pub")
check("public key from an encrypted key with its passphrase",
      library.public_key(library.SSH_DIR / "id_enc", "secret phrase").split()[:2] == enc.split()[:2])
w.show_home("keychain")
kp = w.home.keychain
check("keys listed", {kp.keys.item(r, 0).text() for r in range(kp.keys.rowCount())} >= {"id_test", "id_enc"})
rows = kp.secrets.rowCount()
check("saved password listed", rows == 1 and kp.secrets.item(0, 0).text() == "lab-renamed")
kp.secrets.selectRow(0)
kp.forget()
check("forget removes the saved password", kp.secrets.rowCount() == 0 and SessionStore().get(lab.id).password_enc == "")

# ---------------------------------------------------------------- misc
w.show_tunnels()
check("Tools → Port forwarding opens the Home page", w.tabs.currentWidget() is w.home and
      w.home.stack.currentWidget() is w.home.forwarding)
w.close_tab(0)
check("home tab cannot be closed", w.tabs.widget(0) is w.home)
for i in range(w.tabs.count() - 1, 0, -1):
    w.close_tab(i)
check("closing all terminals leaves Home", w.tabs.count() == 1 and not any(isinstance(w.tabs.widget(i), SessionTab)
                                                                          for i in range(w.tabs.count())))
w.close()
stop_server(srv)
print("DONE")
