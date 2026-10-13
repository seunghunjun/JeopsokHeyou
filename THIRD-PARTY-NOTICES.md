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
| pywinpty (Windows only: local terminals) | 3.0.5 | MIT | Copyright (c) 2017 Spyder IDE | https://github.com/andfoy/pywinpty |
| winpty (bundled in pywinpty) | — | MIT | Copyright (c) 2011-2016 Ryan Prichard | https://github.com/rprichard/winpty |
| OpenConsole / ConPTY (bundled in pywinpty) | — | MIT | Copyright (c) Microsoft Corporation | https://github.com/microsoft/terminal |
| Rust crates compiled into pywinpty | — | MIT OR Apache-2.0 (see below) | Their respective authors | https://crates.io |

Rust crates inside pywinpty's native module (name, version, license): autocfg 1.5.1 (Apache-2.0 OR MIT), bitflags 2.13.0 (MIT OR Apache-2.0), crossbeam-channel 0.5.15 (MIT OR Apache-2.0), crossbeam-utils 0.8.21 (MIT OR Apache-2.0), enum-primitive-derive 0.3.0 (MIT), glob 0.3.3 (MIT OR Apache-2.0), heck 0.5.0 (MIT OR Apache-2.0), itoa 1.0.18 (MIT OR Apache-2.0), libc 0.2.186 (MIT OR Apache-2.0), memchr 2.8.1 (Unlicense OR MIT), num-traits 0.2.19 (MIT OR Apache-2.0), once_cell 1.21.4 (MIT OR Apache-2.0), portable-atomic 1.13.1 (Apache-2.0 OR MIT), proc-macro2 1.0.106 (MIT OR Apache-2.0), pyo3-build-config 0.28.3 (MIT OR Apache-2.0), pyo3-ffi 0.28.3 (MIT OR Apache-2.0), pyo3-macros-backend 0.28.3 (MIT OR Apache-2.0), pyo3-macros 0.28.3 (MIT OR Apache-2.0), pyo3 0.28.3 (MIT OR Apache-2.0), quote 1.0.45 (MIT OR Apache-2.0), serde 1.0.228 (MIT OR Apache-2.0), serde_core 1.0.228 (MIT OR Apache-2.0), serde_derive 1.0.228 (MIT OR Apache-2.0), serde_json 1.0.150 (MIT OR Apache-2.0), syn 2.0.117 (MIT OR Apache-2.0), target-lexicon 0.13.5 (Apache-2.0 WITH LLVM-exception), unicode-ident 1.0.24 ((MIT OR Apache-2.0) AND Unicode-3.0), which 8.0.3 (MIT), windows-bindgen 0.66.0 (MIT OR Apache-2.0), windows-collections 0.3.2 (MIT OR Apache-2.0), windows-core 0.62.2 (MIT OR Apache-2.0), windows-future 0.3.2 (MIT OR Apache-2.0), windows-implement 0.60.2 (MIT OR Apache-2.0), windows-interface 0.59.3 (MIT OR Apache-2.0), windows-link 0.2.1 (MIT OR Apache-2.0), windows-numerics 0.3.1 (MIT OR Apache-2.0), windows-result 0.4.1 (MIT OR Apache-2.0), windows-strings 0.5.1 (MIT OR Apache-2.0), windows-threading 0.2.1 (MIT OR Apache-2.0), windows 0.62.2 (MIT OR Apache-2.0), winpty-rs 1.0.6 (MIT OR Apache-2.0), zmij 1.0.21 (MIT).

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
| `licenses/Apache-2.0.txt` | cryptography, OpenSSL, bcrypt, PyNaCl, Rust crates inside pywinpty (Apache-2.0 option; target-lexicon with the LLVM exception) |
| `licenses/ISC-libsodium.txt` | libsodium |
| `licenses/OFL-1.1-Gaegu.txt` | Gaegu font |
| `licenses/PSF-Python.txt` | Python runtime (binary releases) |
| `licenses/MIT-pywinpty.txt` | pywinpty, winpty, OpenConsole/ConPTY (Windows) |
| `licenses/Unicode-3.0.txt` | unicode-ident (inside pywinpty) |

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
