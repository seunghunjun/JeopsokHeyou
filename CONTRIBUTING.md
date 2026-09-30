# Contributing

Thank you for your interest in JeopsokHeyou.

## License of contributions

By submitting a pull request, you agree that your contribution is licensed
under the same terms as this project: the GNU General Public License v3.0 or
later (see `LICENSE`). You also confirm that you have the right to submit the
contribution under these terms.

New source files start with:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Seunghun Jun
```

Please do not submit code, icons or fonts copied from sources whose license is
incompatible with these terms.

## Before opening a pull request

- Run the tests: `.venv\Scripts\python tests\run_all.py`
- Never commit passwords, private keys, tokens, real server addresses or
  session files (`sessions.json`, `known_hosts`).

## Translations

The UI is written in English and translated through `jeopsokheyou/i18n.py`.

- Wrap every user-visible string in `tr("English text")`. Use named placeholders:
  `tr("{n} items", n=count)`. Never call `tr()` at import time — for module-level
  label tables keep the English text and translate where it is displayed.
- Add the Korean and Japanese translations to `jeopsokheyou/locales/ko.json` and
  `jeopsokheyou/locales/ja.json` (keys are the exact English source strings).
- `tests/test_i18n.py` fails when a string is missing, a placeholder does not match,
  or an entry is no longer used.
- Qt's standard buttons (OK, Cancel, Yes, No) are translated by Qt itself.
