# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Getting-started guide: shown until finished or turned off, resumes where it was closed,
Help replays it without changing the saved progress."""
import os
import shutil
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(TESTS, ".work", "tour")
shutil.rmtree(SP, ignore_errors=True)
os.makedirs(SP)
os.environ["APPDATA"] = os.path.join(SP, "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(TESTS))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from jeopsokheyou import config, tour  # noqa: E402
from jeopsokheyou.mainwindow import MainWindow  # noqa: E402


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def pump(sec=0.2):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


# saved-state helpers
s = {}
check("first run recorded once", tour.mark_first_run(s) and not tour.mark_first_run(s) and s["first_run_at"] > 0)
check("new and existing users: shown until finished", tour.should_autostart({}) and
      tour.should_autostart({"first_run_at": 1}))
check("not shown once done", not tour.should_autostart({"tour": {"done": True}}))
check("not shown once turned off", not tour.should_autostart({"tour": {"dismissed": True}}))
check("broken saved state tolerated", tour.state({"tour": {"step": "x"}})["step"] == 0
      and tour.state({"tour": {"step": 99}})["step"] == len(tour.STEPS) - 1)

w = MainWindow()
w.resize(1200, 760)
w.show()
pump()
t = w.start_tour()
pump()
check("guide opens over the window", t is not None and t.isVisible() and t.geometry() == w.rect())
check("first step is a centred card", t.index == 0 and t.hole is None)
t.next()
pump()
check("step 2 highlights New host", t.step().key == "add_host" and t.hole is not None
      and t.hole.contains(w.home.hosts.new_btn.mapTo(w, w.home.hosts.new_btn.rect().center())))
check("card does not cover the highlight", not t.card.geometry().intersects(t.hole), (t.card.geometry(), t.hole))
check("progress saved", config.load_settings().get("tour", {}).get("step") == 1)
t.next()
t.next()
pump()
check("step 4 shows a picture", t.step().picture == "session" and t.picture_box.count() == 1)
t.skip()
pump()
check("skip closes the guide", w.tour is None and not t.isVisible())
check("skip keeps the step for next time", tour.state(config.load_settings())["step"] == 3
      and tour.should_autostart(config.load_settings()))

w.settings = config.load_settings()
t = w.start_tour()
pump()
check("next start resumes at the same step", t.index == 3)
t.back()
check("back works", t.index == 2)
while t.index < tour.BASICS - 1:
    t.next()
pump()
check("end of the basics highlights Settings", t.step().key == "settings" and t.hole is not None)
check("end of the basics offers to finish there", t.basics_btn.isVisible() and not t.never_btn.isVisible()
      and t.next_btn.text() == "See what's different")
seen = []
while t.index < len(tour.STEPS) - 1:
    t.next()
    pump(0.05)
    seen.append(t.step().key)
check("then the three differences, each with a picture", seen == ["edit", "dragout", "disk"]
      and t.picture_box.count() == 1, seen)
check("last button says Done", t.next_btn.text() == "Done" and not t.basics_btn.isVisible())
w.grab()                                    # every drawing paints without errors
t.next()
pump()
saved = tour.state(config.load_settings())
check("finishing marks it done", saved["done"] and not tour.should_autostart(config.load_settings()))
check("automatic start does nothing once done", w.start_tour() is None)

t = w.start_tour(from_help=True)
pump()
check("Help replays from the start", t is not None and t.index == 0 and not t.never_btn.isVisible())
t.next()
t.skip()
check("replay leaves saved progress alone", tour.state(config.load_settings())["done"])

w.settings["tour"] = {"step": tour.BASICS - 1}
t = w.start_tour()
t.finish_basics()
check("Finish with the basics marks it done", tour.state(config.load_settings())["done"])

for key in ("session", "edit", "dragout", "disk"):
    pic = tour.Picture(key)
    pic.resize(324, 118)
    check(f"picture '{key}' draws", not pic.grab().isNull())

w.settings["tour"] = {"step": 0}
t = w.start_tour()
t.dismiss()
check("Don't show again turns it off", tour.state(config.load_settings())["dismissed"]
      and not tour.should_autostart(config.load_settings()))

w.settings["tour"] = {"step": 1}
t = w.start_tour()
pump()
w.resize(900, 600)
pump()
check("follows window resize", t.geometry() == w.rect() and t.card.geometry().right() <= w.width())
t.skip()
w.close()
print("DONE")
