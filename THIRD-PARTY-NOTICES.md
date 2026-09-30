# Third-Party Notices

JeopsokHeyou itself is licensed under the GNU General Public License v3.0 or
later (`LICENSE`). It uses the following third-party components, each under its
own license. All of them are compatible with GPL-3.0 (LGPL-2.1+/LGPL-3.0,
Apache-2.0, MIT, BSD, ISC, PSF and the SIL Open Font License).

JeopsokHeyou does not modify any of these components. They are used as
separate, unmodified libraries.

## Libraries

| Component | Version | License | Copyright | Source |
|---|---|---|---|---|
| PySide6 / Qt for Python (PySide6, PySide6_Essentials, PySide6_Addons) | 6.11.2 | LGPL-3.0-only | The Qt Company Ltd. | https://code.qt.io/cgit/pyside/pyside-setup.git |
| Shiboken6 | 6.11.2 | LGPL-3.0-only | The Qt Company Ltd. | https://code.qt.io/cgit/pyside/pyside-setup.git |
| Qt 6 (bundled in PySide6) | 6.11.2 | LGPL-3.0-only | The Qt Company Ltd. and other contributors | https://download.qt.io/official_releases/qt/ |
| paramiko | 5.0.0 | LGPL-2.1 | Copyright (C) 2003-2011 Robey Pointer and contributors | https://github.com/paramiko/paramiko |
| pyte | 0.8.2 | LGPL-3.0 | (c) 2011-2012 Selectel, (c) 2012-2017 pyte authors and contributors | https://github.com/selectel/pyte |
| PyYAML | 6.0.3 | MIT | Copyright (c) 2017-2021 Ingy döt Net, Copyright (c) 2006-2016 Kirill Simonov | https://github.com/yaml/pyyaml |
| cryptography | 50.0.1 (48.0.1 on Intel Macs) | Apache-2.0 OR BSD-3-Clause | Copyright (c) Individual contributors | https://github.com/pyca/cryptography |
| OpenSSL (bundled in cryptography) | 4.0.2 | Apache-2.0 | The OpenSSL Project Authors | https://github.com/openssl/openssl |
| bcrypt | 5.0.0 | Apache-2.0 | The Python Cryptographic Authority and individual contributors | https://github.com/pyca/bcrypt |
| PyNaCl | 1.6.2 | Apache-2.0 | Copyright 2013 Donald Stufft and individual contributors | https://github.com/pyca/pynacl |
| libsodium (bundled in PyNaCl) | — | ISC | Copyright (c) 2013-2026 Frank Denis | https://github.com/jedisct1/libsodium |
| cffi | 2.1.1 | MIT-0 | The cffi authors | https://github.com/python-cffi/cffi |
| pycparser | 3.0 | BSD-3-Clause | Copyright (c) 2008-2022, Eli Bendersky | https://github.com/eliben/pycparser |
| invoke | 3.0.3 | BSD-2-Clause | Copyright (c) 2020 Jeff Forcier | https://github.com/pyinvoke/invoke |
| wcwidth | 0.9.1 | MIT | Copyright (c) 2014 Jeff Quast | https://github.com/jquast/wcwidth |

### Included only in binary releases

| Component | License | Notes |
|---|---|---|
| Python runtime | PSF License Agreement | Copyright (c) 2001 Python Software Foundation; full text in `licenses/PSF-Python.txt` |
| PyInstaller bootloader | GPL-2.0 with the PyInstaller bootloader exception | The exception allows bundling applications under any license; https://github.com/pyinstaller/pyinstaller |
| Third-party code inside Qt (FreeType, HarfBuzz, libpng, zlib, …) | Various permissive licenses | Listed by The Qt Company at https://doc.qt.io/qt-6/licenses-used-in-qt.html |

## Fonts

| Component | License | Copyright | Source |
|---|---|---|---|
| Gaegu (`assets/fonts/Gaegu-*.ttf`) | SIL Open Font License 1.1 | Copyright 2018 The Gaegu Project Authors | https://github.com/google/fonts/tree/main/ofl/gaegu |

The Gaegu font files are redistributed unmodified. The font may not be sold by
itself (see `licenses/OFL-1.1-Gaegu.txt`).

## Artwork

- The application icon (`assets/icon2.jpg`, `assets/app.ico`, `assets/app.png`)
  was generated with ChatGPT (OpenAI) for this project.
- The toolbar, folder and file icons are original SVG drawings made for this
  project (`jeopsokheyou/icons.py`).

## License texts

Full license texts are in the `licenses/` directory:

| File | Used by |
|---|---|
| `licenses/LGPL-3.0.txt` + `licenses/GPL-3.0.txt` | PySide6, Shiboken6, Qt, pyte (LGPL-3.0 incorporates GPL-3.0) |
| `licenses/LGPL-2.1.txt` | paramiko |
| `licenses/Apache-2.0.txt` | cryptography, OpenSSL, bcrypt, PyNaCl |
| `licenses/ISC-libsodium.txt` | libsodium |
| `licenses/OFL-1.1-Gaegu.txt` | Gaegu font |
| `licenses/PSF-Python.txt` | Python runtime (binary releases) |

MIT, MIT-0, BSD-2-Clause and BSD-3-Clause texts are included with each
package in its `*.dist-info/licenses` directory when installed.

## LGPL compliance for binary releases

When JeopsokHeyou is distributed as a built binary (the Windows installer/ZIP
or the macOS .app/.dmg made with PyInstaller), the LGPL-licensed libraries
(Qt/PySide6/Shiboken6, paramiko, pyte) are shipped as separate, unmodified files
(a folder "onedir" build on Windows, frameworks and libraries inside
`JeopsokHeyou.app/Contents` on macOS), so that users can replace them with their
own versions. The license files are next to `JeopsokHeyou.exe` on Windows and in
`JeopsokHeyou.app/Contents/Resources` on macOS. The corresponding
source code for these libraries is available at the URLs listed above.
