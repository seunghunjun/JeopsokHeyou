<div align="center">
  <img src="assets/app.png" alt="JeopsokHeyou logo" width="96" />
  <br/>
  <h1>JeopsokHeyou</h1>

  <p><strong>A tabbed SSH terminal and SFTP explorer for Windows and macOS — the file browser follows your shell, and your shell follows the file browser.</strong></p>

  <p>
    <a href="https://github.com/seunghunjun/JeopsokHeyou/releases/latest"><img src="https://img.shields.io/github/v/release/seunghunjun/JeopsokHeyou?label=release&color=3b82f6" alt="Latest release" /></a>
    <a href="https://github.com/seunghunjun/JeopsokHeyou/actions/workflows/ci.yml"><img src="https://github.com/seunghunjun/JeopsokHeyou/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
    <img src="https://img.shields.io/github/stars/seunghunjun/JeopsokHeyou?style=flat&color=eab308" alt="Stars" />
    <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078d4?logo=windows" alt="Windows 10 and 11" />
    <img src="https://img.shields.io/badge/macOS-13%2B-000000?logo=apple" alt="macOS 13 or later" />
    <img src="https://img.shields.io/badge/built_with-Python-3776ab?logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/UI-Qt%206%20(PySide6)-41cd52?logo=qt&logoColor=white" alt="Qt 6" />
    <img src="https://img.shields.io/badge/languages-EN%20%7C%20KO%20%7C%20JA-8b5cf6" alt="English, Korean, Japanese" />
    <img src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue" alt="GPL-3.0-or-later" />
  </p>

  <img width="880" alt="JeopsokHeyou demo" src=".github/media/demo.webp" />
</div>

<br/>

JeopsokHeyou (pronounced *jup-sok-hae-yu*, a playful Korean way of saying "let's connect") is a
lightweight SSH/SFTP client built for people who live in PuTTY or Tabby but keep switching to a
separate program to move files. No account, no telemetry, no cloud.

## ✨ Features

No account required. Free and open source (GPL-3.0).

- **🗂️ Terminal + SFTP side by side** — every tab shows a remote file explorer next to the shell.
- **🔗 Two-way folder sync** — `cd` in the terminal and the explorer follows; open a folder in the explorer and the terminal quietly `cd`s there (bash/zsh). It never types into a running program or over a half-written command.
- **🖱️ Drag & drop both ways** — drop files from Explorer or Finder to upload; drag remote files onto a folder window or the desktop to download there. Background transfers with progress and cancel.
- **✏️ Edit remote files locally** — double-click to open in your usual app; save and JeopsokHeyou offers to upload the change (only when the content really changed). "Open with…" is built in.
- **🪟 Tabs & split panes** — split left/right or top/bottom on the same connection, close any pane with one click.
- **📁 Sessions & groups** — search, drag sessions between groups, collapse groups, recent-session cards on the start page.
- **📥 One-click import** — bring your sessions over from **PuTTY** and **Tabby** (including Tabby groups).
- **⏱️ Idle auto-disconnect** — per session or global, with a one-minute warning; never disconnects during a transfer.
- **🛡️ Safe by default** — host-key verification (trust on first use, block on mismatch), passwords not saved unless you ask (and then kept in Windows DPAPI or the macOS Keychain), private keys referenced by path only.
- **🎨 Finder-style UI** — light and dark themes, crisp vector icons, Korean handwriting font (Gaegu) as an option.
- **🌐 English, Korean and Japanese** — follows the system language; switch anytime in Settings.
- **🍎 Native on both platforms** — ⌘ shortcuts, Keychain and Finder on macOS; Explorer, DPAPI and a per-user installer on Windows.

## 📸 Screenshots

<table>
  <tr>
    <td width="50%"><img src=".github/media/main-light.png" alt="Terminal and SFTP explorer side by side" /><br/><sub><b>Terminal + explorer</b> — one tab, one connection, both views</sub></td>
    <td width="50%"><img src=".github/media/sync.png" alt="The explorer follows a cd in the terminal" /><br/><sub><b>Folder sync</b> — <code>cd logs</code> in the shell, the explorer is already there</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src=".github/media/split-panes.png" alt="Three terminal panes on one connection" /><br/><sub><b>Split panes</b> — nested left/right and top/bottom splits</sub></td>
    <td width="50%"><img src=".github/media/main-dark.png" alt="Dark theme" /><br/><sub><b>Dark mode</b> — follows Windows or pick it yourself</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src=".github/media/welcome.png" alt="Start page with recent sessions" /><br/><sub><b>Start page</b> — recent sessions one click away</sub></td>
    <td width="50%" align="center"><img src=".github/media/sidebar-dark.png" alt="Session sidebar with groups" height="330" /><br/><sub><b>Session groups</b> — drag sessions in and out of groups</sub></td>
  </tr>
</table>

## 📦 Install

Downloads are published on the [Releases](https://github.com/seunghunjun/JeopsokHeyou/releases) page, together with a `SHA256SUMS.txt`
file so you can verify what you downloaded.

### Windows 10 / 11

- **Installer:** `JeopsokHeyou-<version>-setup.exe` — choose English, Korean or Japanese; installs per user
  (no administrator rights) to `%LOCALAPPDATA%\Programs\JeopsokHeyou`.
- **Portable:** `JeopsokHeyou-<version>-win-x64.zip` — unzip and run `JeopsokHeyou.exe`.

> **SmartScreen:** the builds are not code-signed yet, so Windows may show "Windows protected your PC".
> Choose *More info → Run anyway* only if you downloaded the file from this repository's Releases page.
> Some corporate PCs block unsigned installers entirely — use the portable ZIP or ask your IT team.

### macOS 13 Ventura or later

- `JeopsokHeyou-<version>-macos-arm64.dmg` for Apple silicon, `…-macos-x86_64.dmg` for Intel Macs.
- Open the DMG and drag **JeopsokHeyou** to **Applications**.

> **Gatekeeper:** the builds are not notarized by Apple yet. On first launch, right-click the app and
> choose **Open** (or allow it in *System Settings → Privacy & Security*). Drag-to-download asks once
> for permission to query Finder.

### From source (both platforms)

```bash
git clone https://github.com/seunghunjun/JeopsokHeyou.git
cd JeopsokHeyou
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt      # Windows: .venv\Scripts\pip
.venv/bin/python main.py                            # Windows: run.bat
```

### Uninstall

- **Windows:** *Settings → Apps → Installed apps → JeopsokHeyou → Uninstall* (or run `Uninstall.exe` in the
  install folder). Tick *Also delete my sessions and settings* to remove `%APPDATA%\JeopsokHeyou` too.
  For the portable ZIP, delete the folder.
- **macOS:** drag **JeopsokHeyou** from *Applications* to the Trash. To remove your data as well, delete
  `~/Library/Application Support/JeopsokHeyou` and the *JeopsokHeyou* items in Keychain Access.

### Language

The UI language follows the system language (English is used for anything other than Korean or
Japanese). Change it in **View → Settings → Language**, or start with `--lang en|ko|ja`.

## ⚖️ Comparison

| Feature | JeopsokHeyou | PuTTY | Tabby | MobaXterm Home |
| --- | --- | --- | --- | --- |
| **Engine** | Python + Qt 6 | C (native) | Electron | Native (closed source) |
| **Tabs** | ✅ | ❌ | ✅ | ✅ |
| **Split panes** | ✅ | ❌ | ✅ | ✅ |
| **Graphical SFTP browser** | ✅ | ❌ (`psftp` CLI) | ✅ | ✅ |
| **Explorer follows terminal `cd`** | ✅ | ❌ | ? | ✅ |
| **Terminal follows explorer** | ✅ | ❌ | ? | ? |
| **Drag & drop to Windows Explorer** | ✅ | ❌ | ? | ✅ |
| **Edit remote file → re-upload** | ✅ | ❌ | ? | ✅ |
| **Import PuTTY / Tabby sessions** | ✅ / ✅ | — | ? | ? |
| **Idle auto-disconnect** | ✅ | ? | ? | ? |
| **Host-key verification** | ✅ | ✅ | ✅ | ✅ |
| **Saved passwords** | 🟡 optional (DPAPI / Keychain) | ❌ by design | ✅ vault | ✅ master password |
| **Port forwarding** | ❌ planned | ✅ | ✅ | ✅ |
| **X11 forwarding** | ❌ | ✅ | ✅ | ✅ |
| **Serial console** | ❌ | ✅ | ✅ | ✅ |
| **Platforms** | Windows, macOS | Windows, Unix | Windows, macOS, Linux | Windows |
| **UI languages** | EN, KO, JA | EN | many | ? |
| **Account required** | No | No | No (sync optional) | No |
| **License** | GPL-3.0-or-later | MIT | MIT | Proprietary freeware |

<sub>✅ yes · ❌ no · 🟡 partial · ? not verified. Based on our understanding in September 2026 — corrections are welcome via pull request.</sub>

## 🛡️ Architecture & Security

JeopsokHeyou is **local-only**: it talks to the SSH servers you connect to and nothing else —
no account, no analytics, no auto-update service.

| Topic | How it works |
| --- | --- |
| **Where data lives** | Windows `%APPDATA%\JeopsokHeyou\`, macOS `~/Library/Application Support/JeopsokHeyou/` — `sessions.json`, `known_hosts`, `settings.json`. Nothing is written next to the program. |
| **Passwords** | Not saved unless you tick *Save password*. Windows: encrypted with DPAPI (bound to your Windows account). macOS: stored in your login Keychain — `sessions.json` only holds a marker. |
| **Private keys** | Only the key **path** is stored. OpenSSH format (convert PuTTY `.ppk` with PuTTYgen). SSH agent (Pageant/OpenSSH) is used for key sessions. |
| **Host keys** | Trust on first use with the SHA256 fingerprint shown; a changed key **blocks** the connection. |
| **Remote file names** | Names containing `\`, `:`, `..` or Windows device names are sanitised so a malicious server cannot write outside the chosen folder. |
| **Temporary copies** | Files opened for editing are copied to the system temp folder (`JeopsokHeyou/`) and cleaned up after 3 days. |

### Connecting

```mermaid
flowchart LR
    A[Connect] --> B{Host key in<br/>known_hosts?}
    B -- "no" --> C[Show SHA256 fingerprint] --> D{User trusts?}
    D -- "yes" --> E[Save to known_hosts]
    D -- "no" --> X[Cancel]
    B -- "matches" --> F[Authenticate<br/>password / key / agent]
    B -- "different" --> Y[Block: possible MITM]
    E --> F --> G[Shell channel] & H[SFTP: browse] & I[SFTP: transfers]
```

### Two-way folder sync

```mermaid
sequenceDiagram
    participant E as Explorer
    participant T as Terminal pane
    participant S as Remote shell (bash/zsh)
    Note over T,S: On connect, a prompt hook is installed<br/>that reports $PWD via OSC 7 (hidden from the screen)
    S-->>T: OSC 7 /home/me/logs (on every prompt)
    T-->>E: follow /home/me/logs
    E->>T: user opens /var/www
    alt at an idle prompt and nothing typed
        T->>S: cd -- '/var/www' (echo hidden)
        S-->>T: OSC 7 /var/www
    else program running or command being typed
        T-->>E: leave the terminal alone and say why
    end
```

## 🛠️ Development & Build

Prerequisites: Windows 10/11 or macOS 13+, Python 3.12+.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-lock.txt   # Windows: .venv\Scripts\pip
.venv/bin/python main.py --lang ja               # --lang en|ko|ja to test translations
.venv/bin/python tests/run_all.py                # headless tests against a local fake SSH/SFTP server
.venv/bin/pip install pyinstaller pillow && .venv/bin/python tools/build_release.py
                                                 # Windows: setup.exe + ZIP (needs NSIS 3); macOS: .dmg
```

Continuous integration runs the test suite on Windows and macOS (Apple silicon and Intel) for every
push; pushing a `v*` tag builds all installers and drafts a GitHub Release.

- Translations live in `jeopsokheyou/locales/{ko,ja}.json` (English is the source language). `tests/test_i18n.py` fails if a string is missing.
- `tools/make_icon.py` builds the multi-size `app.ico`; `tools/make_readme_media.py` regenerates every image in this README (needs `pip install pillow`).
- Test data never contains real servers: `tests/fixtures` uses documentation-only addresses (RFC 5737).

## 🧰 Tech Stack

| Layer | Tech |
| --- | --- |
| UI | Qt 6 via PySide6, custom Finder-style theme and SVG icons |
| Terminal | pyte (VT100/xterm emulation) with a custom Qt renderer, IME support |
| SSH / SFTP | paramiko (OpenSSH-compatible, modern algorithms only) |
| Crypto | cryptography / OpenSSL, bcrypt, PyNaCl (via paramiko) |
| Secrets | Windows DPAPI (`CryptProtectData`) / macOS Keychain (`security`) |
| Import | Windows registry (PuTTY), PyYAML (Tabby) |

## 🗺️ Roadmap

- Code-signed Windows installer and notarized macOS app
- Port forwarding (local / remote / dynamic)
- PuTTY `.ppk` key support
- Mouse reporting for full-screen programs (htop, mc) and line reflow on resize

<a id="code-signing-policy"></a>

## ✍️ Code signing policy

Windows releases are being prepared for signing through the
[SignPath Foundation](https://signpath.org) free code signing program for open source projects
(application pending — builds up to 1.0.0 are **not** signed).

- Only JeopsokHeyou's own binaries are signed (`JeopsokHeyou.exe`, the installer and the uninstaller);
  third-party libraries are shipped unmodified from their upstream projects.
- Every release is built from a tagged commit by GitHub Actions, and every signing request is approved manually.

**Team roles**

| Role | Members |
| --- | --- |
| Committers and reviewers | [Seunghun Jun](https://github.com/seunghunjun) |
| Approvers | [Seunghun Jun](https://github.com/seunghunjun) |

### Privacy policy

This program will not transfer any information to other networked systems unless specifically requested
by the user or the person installing or operating it. JeopsokHeyou only connects to the SSH/SFTP servers
you choose; it has no telemetry, analytics or update checks. The bundled third-party libraries
(Qt/PySide6, paramiko, pyte, cryptography, …) do not collect or send data either.

## 📄 Licensing

JeopsokHeyou is © 2026 Seunghun Jun and **free software** released under the
**GNU General Public License v3.0 or later** — see [LICENSE](LICENSE).

- ✅ Use it anywhere (personally or at work), study it, change it and share it.
- 🔁 If you distribute JeopsokHeyou or a modified version — for free or for a fee — you must
  do so under the same license and give your users the complete corresponding source code.
- Provided **"as is"**, without warranty of any kind.

Every release on GitHub is built from the tagged source by GitHub Actions, and the source code for
that exact version is attached to the release.

Third-party libraries (Qt/PySide6, paramiko, pyte, …) and the Gaegu font keep their own licenses,
all compatible with GPL-3.0 — see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) and
[licenses/](licenses/). The app icon was generated with ChatGPT; all other icons are original SVGs.

PuTTY, Tabby, MobaXterm, Windows, macOS and Finder are trademarks of their respective owners. JeopsokHeyou is an
independent project and is not affiliated with them.

## 🤝 Contributing & Security

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Please report vulnerabilities
privately as described in [SECURITY.md](SECURITY.md), and never post passwords, keys or real server
addresses in issues.
