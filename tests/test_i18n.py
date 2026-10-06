# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
"""Translation checks: every tr("...") string has Korean and Japanese translations,
placeholders match, and no Korean text is left hard-coded in the source."""
import ast
import json
import os
import re
import string
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
PKG = os.path.join(ROOT, "jeopsokheyou")
sys.path.insert(0, ROOT)

HANGUL = re.compile("[\uac00-\ud7a3\u3131-\u318e]")   # Hangul syllables and jamo


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)


def tr_strings(path):
    """Literal first arguments of tr(...) calls in a Python file."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "tr"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    return found


def fields(s):
    return sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)


sources = sorted(os.path.join(PKG, f) for f in os.listdir(PKG) if f.endswith(".py"))
used = set()
for p in sources:
    used |= tr_strings(p)
check("translatable strings found", len(used) > 100, len(used))

# Label tables translated at display time (not literal tr() calls)
sys.path.insert(0, ROOT)
from jeopsokheyou import icons, theme  # noqa: E402
from jeopsokheyou.dialogs import IDLE_CHOICES  # noqa: E402
from jeopsokheyou.mainwindow import THEME_CHOICES, SessionTab  # noqa: E402
tables = {label for _k, label in THEME_CHOICES} | {label for _m, label in IDLE_CHOICES} \
    | {v[0] for v in theme.UI_FONTS.values()} | {v[0] for v in icons.KINDS.values()} \
    | set(SessionTab.SYNC_MSG.values())
from jeopsokheyou import forwarding, home, tunnels, vaultui  # noqa: E402
tables |= set(forwarding.KIND_LABELS.values()) | set(tunnels.KIND_HINTS.values()) | set(tunnels.TunnelsPage.COLS) \
    | {label for _m, label in vaultui.LOCK_CHOICES} | set(forwarding.VALIDATION_MESSAGES) \
    | {tunnels.NO_SERVER_MESSAGE} | {label for _k, label, _i in home.PAGES}
from jeopsokheyou import tour  # noqa: E402
tables |= {st.title for st in tour.STEPS} | {st.body for st in tour.STEPS}
used |= tables

for lang in ("ko", "ja"):
    cat = json.load(open(os.path.join(PKG, "locales", f"{lang}.json"), encoding="utf-8"))
    missing = sorted(used - set(cat))
    check(f"{lang}: every string translated", not missing, missing[:10])
    empty = [k for k, v in cat.items() if not str(v).strip()]
    check(f"{lang}: no empty translations", not empty, empty[:5])
    bad = [k for k, v in cat.items() if fields(k) != fields(v)]
    check(f"{lang}: placeholders match", not bad, bad[:5])
    unused = sorted(set(cat) - used)
    check(f"{lang}: no stale entries", not unused, unused[:10])

# No Korean left in code, tests, tools or docs (exceptions: the language list in i18n.py and the
# language links in README.md; README.ko.md / README.ja.md are the translated READMEs)
offenders = []
for folder in ("jeopsokheyou", "tests", "tools"):
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
        if ".work" in dirpath or "locales" in dirpath or "__pycache__" in dirpath:
            continue
        for f in files:
            if not f.endswith((".py", ".yaml", ".md", ".txt", ".bat")):
                continue
            p = os.path.join(dirpath, f)
            for i, line in enumerate(open(p, encoding="utf-8"), 1):
                if HANGUL.search(line) and not (f == "i18n.py" and "LANGUAGES" in line):
                    offenders.append(f"{os.path.relpath(p, ROOT)}:{i}")
for f in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "THIRD-PARTY-NOTICES.md", "LICENSE", "main.py", "run.bat"):
    p = os.path.join(ROOT, f)
    if os.path.exists(p):
        # README.md may name the translated READMEs in their own language (README.ko.md / README.ja.md)
        offenders += [f"{f}:{i}" for i, line in enumerate(open(p, encoding="utf-8"), 1)
                      if HANGUL.search(line) and "README.ko.md" not in line]
check("no Korean outside the translation files", not offenders, offenders[:10])

# Switching language really changes the text
from jeopsokheyou import i18n  # noqa: E402
i18n.set_language("ko")
ko = i18n.tr("Settings…")
i18n.set_language("ja")
ja = i18n.tr("Settings…")
i18n.set_language("en")
check("set_language switches catalogs", ko != "Settings…" and ja != "Settings…" and ko != ja, (ko, ja))
check("unknown language falls back to English", i18n.resolve("xx") in i18n.LANGUAGES)
print("DONE")
