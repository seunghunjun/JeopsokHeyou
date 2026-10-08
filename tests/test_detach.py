# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Tear tabs and panes off into windows and dock them back; the shells keep running throughout."""
import os
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "detach")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
root = os.path.join(SP, "srv")
os.makedirs(os.path.join(root, "home", "tester"), exist_ok=True)

from PySide6.QtCore import QPoint, QSize, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QSplitter  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
from _util import stop_server  # noqa: E402
from jeopsokheyou import detach  # noqa: E402
from jeopsokheyou.config import Session  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def wait(cond, sec=8):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


check("tear-off rules: desktop ok, ordinary programs ok",
      not detach.tear_off_blocked("Progman", False, False, "explorer.exe")
      and not detach.tear_off_blocked("Chrome_WidgetWin_1", False, False, "chrome.exe")
      and not detach.tear_off_blocked("PPTFrameClass", False, False, "POWERPNT.EXE"))
check("tear-off rules: taskbar, full screen and administrator programs blocked",
      detach.tear_off_blocked("Shell_TrayWnd", False, False, "explorer.exe")
      and detach.tear_off_blocked("screenClass", True, False, "POWERPNT.EXE")
      and detach.tear_off_blocked("Notepad", False, True, "notepad.exe"))
detach.set_blocked_apps("POWERPNT.EXE; chrome")
check("tear-off rules: programs listed in Settings blocked",
      detach.tear_off_blocked("PPTFrameClass", False, False, "powerpnt.exe")
      and detach.tear_off_blocked("Chrome_WidgetWin_1", False, False, "chrome.exe")
      and not detach.tear_off_blocked("Notepad", False, False, "notepad.exe"))
detach.set_blocked_apps("")
check("drop zones", [detach.drop_zone(QSize(100, 100), QPoint(x, y)) for x, y in ((5, 50), (95, 50), (50, 5), (50, 95))]
      == ["left", "right", "top", "bottom"])

srv = subprocess.Popen([sys.executable, os.path.join(TESTS, "fake_server.py"), "2299", root], stdout=subprocess.PIPE)
srv.stdout.readline()
try:
    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    s1 = Session(host="127.0.0.1", port=2299, user="tester", name="one")
    s2 = Session(host="127.0.0.1", port=2299, user="tester", name="two")
    for s in (s1, s2):
        w.store.upsert(s)
        w.open_session(s, "pw")
    tabs = w.session_tabs()
    t1, t2 = tabs
    check("connected", wait(lambda: t1.state == "connected" and t2.state == "connected", 15))

    # --- panes
    t1.split_pane(Qt.Orientation.Horizontal)
    t1.split_pane(Qt.Orientation.Horizontal)
    check("three panes", wait(lambda: len(t1.panes) == 3 and all(p.chan for p in t1.panes)))
    a, b, c = t1.panes
    chan_c = c.chan
    t1.float_pane(c, QPoint(200, 200))
    app.processEvents()
    win = t1.pane_windows[0] if t1.pane_windows else None
    check("pane torn off into its own window", win is not None and c.window() is win and win.isVisible())
    check("its shell keeps running", c.chan is chan_c and not c.disconnected and c in t1.panes)
    check("the tab keeps the other panes", t1.term_split.isAncestorOf(a) and t1.term_split.isAncestorOf(b))
    check("title bar on the panes in the tab, none in its own window", all(p.frame.bar.isVisibleTo(p.frame) for p in (a, b))
          and not c.frame.bar.isVisibleTo(c.frame))

    # dock it back below pane a
    t1.dock_pane(c, a, "bottom")
    app.processEvents()
    check("docked below another pane", t1.term_split.isAncestorOf(c) and isinstance(c.frame.parentWidget(), QSplitter)
          and c.frame.parentWidget().orientation() == Qt.Orientation.Vertical
          and c.frame.parentWidget().indexOf(c.frame) > c.frame.parentWidget().indexOf(a.frame))
    check("empty pane window closed", wait(lambda: not t1.pane_windows))
    check("same shell after docking", c.chan is chan_c and not c.disconnected)

    # dock on the left of b (same row)
    t1.dock_pane(c, b, "left")
    app.processEvents()
    check("docked left of another pane", c.frame.parentWidget() is b.frame.parentWidget()
          and c.frame.parentWidget().indexOf(c.frame) == c.frame.parentWidget().indexOf(b.frame) - 1)

    # closing a pane's own window ends that terminal; the others stay
    t1.split_pane(Qt.Orientation.Horizontal)
    wait(lambda: len(t1.panes) == 4 and t1.panes[-1].chan is not None)
    extra = t1.panes[-1]
    t1.float_pane(extra, QPoint(250, 250))
    app.processEvents()
    check("its own window has no title bar", not extra.frame.bar.isVisibleTo(extra.frame))
    t1.pane_windows[0].close()
    app.processEvents()
    check("closing the window ends that terminal", extra not in t1.panes and len(t1.panes) == 3
          and not t1.pane_windows)

    # a pane in a window closed by the shell: window goes away too
    t1.float_pane(b, QPoint(250, 250))
    app.processEvents()
    t1.close_pane(b)
    check("closing the last pane of a window closes the window", wait(lambda: not t1.pane_windows)
          and len(t1.panes) == 2)

    # drag-and-drop events: drop the grip of one pane on the top half of another
    from PySide6.QtCore import QPointF  # noqa: E402
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent  # noqa: E402
    a, b = t1.panes
    detach.dragging["pane"] = b
    mime = detach._mime(detach.MIME_PANE)
    pos = QPoint(a.width() // 2, 4)
    for ev in (QDragEnterEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier),
               QDragMoveEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)):
        QApplication.sendEvent(a, ev)
    check("drop zone shown while dragging", a._drop_zone == "top")
    QApplication.sendEvent(a, QDropEvent(QPointF(pos), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                                         Qt.KeyboardModifier.NoModifier))
    detach.dragging["pane"] = None
    check("dropping docks the pane above", wait(lambda: b.frame.parentWidget() is a.frame.parentWidget()
                                                and b.frame.parentWidget().orientation() == Qt.Orientation.Vertical
                                                and b.frame.parentWidget().indexOf(b.frame) < b.frame.parentWidget().indexOf(a.frame)))
    check("highlight cleared after drop", a._drop_zone is None)
    detach.dragging["pane"] = t2.panes[0]
    mv = QDragMoveEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(a, mv)
    check("a pane of another connection can't dock here", not mv.isAccepted())
    detach.dragging["pane"] = None

    # --- tabs
    t2.split_pane(Qt.Orientation.Horizontal)
    wait(lambda: len(t2.panes) == 2)
    w.float_tab(t2, QPoint(300, 120))
    app.processEvents()
    check("tab torn off into a window", len(w.tab_windows) == 1 and w.tab_widget_of(t2) is w.tab_windows[0].tabs
          and w.tabs.indexOf(t2) < 0)
    check("tab keeps its connection and panes", t2.state == "connected" and len(t2.panes) == 2)
    check("listed among all session tabs", t2 in w.session_tabs())
    t2.title_changed.emit(t2, "✕ two")
    check("titles update in the new window", w.tab_windows[0].tabs.tabText(0) == "✕ two")
    t2.title_changed.emit(t2, "two")
    w.move_tab(t2, w.tabs, 99)
    app.processEvents()
    check("tab dropped back on the main tab bar", w.tabs.indexOf(t2) > 0)
    check("empty tab window closed", wait(lambda: not w.tab_windows))
    w.move_tab(t2, w.tabs, 0)
    check("Home stays the first tab", w.tabs.widget(0) is w.home)


    # the only pane of a tab can go too: the tab shows a card to bring it back
    t2.close_pane(t2.panes[1])
    only = t2.panes[0]
    t2.float_pane(only, QPoint(320, 140))
    app.processEvents()
    card = t2.empty_card
    check("only pane floats on its own", len(t2.pane_windows) == 1 and only.window() is t2.pane_windows[0]
          and not only.disconnected)
    check("tab shows the bring-back card", card is not None and card.isVisibleTo(t2) and t2.term_split.indexOf(card) >= 0)
    check("tab title marked", w.tabs.tabText(w.tabs.indexOf(t2)).startswith("⧉"), w.tabs.tabText(w.tabs.indexOf(t2)))
    check("no button to bring it back (drag only)", not hasattr(card, "back_btn"))
    detach.dragging["pane"] = only
    cp = card.rect().center()
    QApplication.sendEvent(card, QDragEnterEvent(cp, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                                                 Qt.KeyboardModifier.NoModifier))
    QApplication.sendEvent(card, QDropEvent(QPointF(cp), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                                            Qt.KeyboardModifier.NoModifier))
    detach.dragging["pane"] = None
    check("dropping it on the card docks it back", wait(lambda: t2.term_split.isAncestorOf(only))
          and t2.term_split.indexOf(card) < 0 and not w.tabs.tabText(w.tabs.indexOf(t2)).startswith("⧉")
          and only.frame.bar.isVisibleTo(only.frame))
    t2.float_pane(only, QPoint(320, 140))
    app.processEvents()
    t2.empty_card.new_btn.click()
    check("New terminal opens another shell in the tab", wait(lambda: len(t2.panes) == 2 and t2.panes[1].chan is not None)
          and t2.term_split.indexOf(t2.empty_card) < 0)
    t2.pane_windows[0].close()
    app.processEvents()
    check("closing the window ends the floating terminal", len(t2.panes) == 1 and only not in t2.panes)
    t2.split_pane(Qt.Orientation.Horizontal)
    wait(lambda: len(t2.panes) == 2)

    # double-click the title bar: one terminal fills the tab, again to restore
    p1, p2 = t2.panes
    t2.toggle_maximize(p1)
    check("double-click fills the tab", p1.frame.isVisibleTo(t2) and not p2.frame.isVisibleTo(t2))
    t2.toggle_maximize(p1)
    check("double-click again restores", p1.frame.isVisibleTo(t2) and p2.frame.isVisibleTo(t2))
    t2.toggle_maximize(p2)
    t2.split_pane(Qt.Orientation.Horizontal)
    check("splitting restores the layout first", wait(lambda: len(t2.panes) == 3)
          and all(p.frame.isVisibleTo(t2) for p in t2.panes))

    # title bar shows the session and folder, active pane highlighted
    t2.panes[0].cwd = "/var/log"
    t2._update_bar(t2.panes[0])
    check("title bar text", "/var/log" in t2.panes[0].frame.bar._full and "two" in t2.panes[0].frame.bar._full)
    t2._pane_focused(t2.panes[1])
    check("active pane bar highlighted", t2.panes[1].frame.bar.property("active")
          and not t2.panes[0].frame.bar.property("active"))

    # moving a torn-off window back over its tab docks it (no title bar needed)
    w.tabs.setCurrentWidget(t2)
    app.processEvents()
    f = t2.panes[-1]
    t2.float_pane(f, QPoint(400, 300))
    app.processEvents()
    win = t2.pane_windows[0]
    tgt = t2.panes[0]
    gp = tgt.mapToGlobal(QPoint(4, tgt.height() // 2))
    target = win._target_at(gp)
    check("moving over a terminal finds its side", target == (tgt, "left"), target)
    win.docker.target = target
    win._show_target(target)
    check("the place lights up while moving", tgt._drop_zone == "left")
    win.docker.finish()
    check("releasing docks the window there", wait(lambda: t2.term_split.isAncestorOf(f) and not t2.pane_windows)
          and f.frame.parentWidget().indexOf(f.frame) < f.frame.parentWidget().indexOf(tgt.frame))
    check("highlight cleared", tgt._drop_zone is None)
    w.float_tab(t2, QPoint(300, 120))
    app.processEvents()
    tw = w.tab_windows[0]
    bar = w.tabs.tabBar()
    hit = tw._target_at(bar.mapToGlobal(bar.rect().center()))
    check("moving a tab window over the main tab bar finds it", hit is bar)
    check("not elsewhere", tw._target_at(w.mapToGlobal(QPoint(w.width() // 2, w.height() - 10))) is None)
    tw.docker.target = hit
    tw.docker.finish()
    check("releasing puts its tabs back", wait(lambda: not w.tab_windows and w.tabs.indexOf(t2) > 0))

    # the drag is followed by the app: desktop tears off, another program's window is not allowed
    w.tabs.setCurrentWidget(t2)
    app.processEvents()
    pa, pb = t2.panes[0], t2.panes[1]
    on_pb = pb.mapToGlobal(QPoint(4, pb.height() // 2))
    check("over another terminal: dock there", detach.pane_target(t2, pa, on_pb) == ("dock", pb, "left"),
          detach.pane_target(t2, pa, on_pb))
    on_explorer = t2.explorer.mapToGlobal(t2.explorer.rect().center())
    check("over the explorer: not allowed", detach.pane_target(t2, pa, on_explorer) == ("none",))
    far = QPoint(-30000, -30000)
    real_fw = detach.foreign_window_at
    detach.foreign_window_at = lambda: False
    check("over the desktop: tear off", detach.pane_target(t2, pa, far) == ("tear",))
    detach.foreign_window_at = lambda: True
    check("over another program: not allowed", detach.pane_target(t2, pa, far) == ("none",)
          and detach.tab_target(far) == ("none",))
    bar_pos = w.tabs.tabBar().mapToGlobal(w.tabs.tabBar().rect().center())
    check("a tab over a tab bar", detach.tab_target(bar_pos) == ("bar", w.tabs.tabBar()))

    # a whole drag: press-move on the title bar, release over the desktop
    from PySide6.QtGui import QMouseEvent  # noqa: E402
    detach.foreign_window_at = lambda: False
    n_win = len(t2.pane_windows)
    detach.start_pane_drag(t2, pb)
    drag = [o for o in pb.frame.bar.children() if isinstance(o, detach.ManualDrag)][0]
    check("cursor while dragging", QApplication.overrideCursor() is not None)
    mv = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(0, 0), QPointF(far), Qt.MouseButton.NoButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(pb.frame.bar, mv)
    check("target follows the mouse", drag.target == ("tear",))
    rel = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(0, 0), QPointF(far), Qt.MouseButton.LeftButton,
                      Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(pb.frame.bar, rel)
    check("released on the desktop: own window", wait(lambda: len(t2.pane_windows) == n_win + 1)
          and QApplication.overrideCursor() is None)
    t2.pane_windows[-1].docker.target = (pa, "right")
    t2.pane_windows[-1].docker.finish()
    wait(lambda: not t2.pane_windows)
    # released over another program: nothing happens
    detach.foreign_window_at = lambda: True
    detach.start_pane_drag(t2, pb)
    QApplication.sendEvent(pb.frame.bar, mv)
    QApplication.sendEvent(pb.frame.bar, rel)
    wait(lambda: False, 0.3)
    check("released over another program: stays put", not t2.pane_windows and t2.term_split.isAncestorOf(pb))
    # Esc cancels
    detach.foreign_window_at = lambda: False
    detach.start_pane_drag(t2, pb)
    QApplication.sendEvent(pb.frame.bar, mv)
    from PySide6.QtGui import QKeyEvent  # noqa: E402
    QApplication.sendEvent(pb.frame.bar, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    wait(lambda: False, 0.3)
    check("Esc cancels the drag", not t2.pane_windows and QApplication.overrideCursor() is None)
    detach.foreign_window_at = real_fw

    # ✕ on the only terminal ends the session
    s3 = Session(host="127.0.0.1", port=2299, user="tester", name="three")
    w.store.upsert(s3)
    w.open_session(s3, "pw")
    t3 = w.session_tabs()[-1]
    wait(lambda: t3.state == "connected")
    t3.panes[0].frame.bar.close_btn.click()
    app.processEvents()
    check("✕ on the last terminal closes the session", t3 not in w.session_tabs())

    # closing a tab window ends its sessions
    w.float_tab(t2, QPoint(300, 120))
    app.processEvents()
    w.tab_windows[0].close()
    check("closing a tab window ends its sessions", wait(lambda: not w.tab_windows) and t2 not in w.session_tabs())
    w.close()
finally:
    stop_server(srv)
print("DONE")
