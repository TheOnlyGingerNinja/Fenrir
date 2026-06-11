# 🐺 Fenrir PDF Reader

A native, cross-platform PDF reader and editor built with Python, PySide6 (Qt6), and PyMuPDF.

- **Native desktop app** — not a web app, not Electron, not bloated
- **Full reader** — zoom, search, TOC, thumbnails, text selection, print
- **Editor tools** — highlight, underline, strikethrough, sticky notes, freehand draw, text boxes
- **Cross-platform** — Linux and Windows (macOS support possible)

---

## Quick Start

### Linux (current setup)

```bash
cd ~/.openclaw/workspace/fenrir-reader
./venv/bin/python main.py ~/Documents/doc.pdf
```

Fenrir is already set as the **default PDF application** on this machine. Double-click any PDF in your file manager — it opens in Fenrir. A desktop shortcut is on your Desktop.

### Windows — Transfer & Setup

#### Option A: Run from Source (easiest, no build needed)

1. **Install Python 3.11+** on Windows from [python.org](https://python.org) — check "Add to PATH"
2. Open **Command Prompt (cmd)** and run:
   ```cmd
   pip install PySide6 PyMuPDF
   ```
3. **Get the code** — either:
   - Download ZIP from: https://github.com/TheOnlyGingerNinja/Fenrir
   - Or clone with: `git clone https://github.com/TheOnlyGingerNinja/Fenrir.git`
4. Run it:
   ```cmd
   cd Fenrir
   python main.py
   ```

#### Option B: Build a Standalone .exe (no Python needed)

On the Windows machine, after installing Python and cloning the repo:

```cmd
pip install pyinstaller
python build.py
```

This creates `dist/Fenrir.exe` — a single, portable .exe you can put anywhere, send to friends, or pin to your taskbar.

### Make Fenrir the Default PDF App on Windows

1. Right-click any `.pdf` file → **Open with** → **Choose another app**
2. Click **More apps ↓** → **Look for another app on this PC**
3. Navigate to `dist/Fenrir.exe` or wherever you have it
4. Check **"Always use this app to open .pdf files"**
5. Click **Open**

### Create a Desktop Shortcut on Windows

1. Right-click `dist/Fenrir.exe` → **Send to** → **Desktop (create shortcut)**
2. (Optional) Right-click the shortcut → **Properties** → **Change Icon** → browse to `resources/icons/fenrir.png`

---

## Updates

Since the code is on GitHub, updating is straightforward.

### On Linux (this machine)

The desktop file points to the source code directly — updates are instant:

```bash
cd ~/.openclaw/workspace/fenrir-reader
git pull
```

Done. Next time you open a PDF, you're on the latest version.

### On Windows (running from source)

```cmd
cd C:\path\to\Fenrir
git pull
```

Same — one command, instantly updated.

### On Windows (running from .exe)

1. `git pull` to get the latest code
2. Rebuild: `python build.py`
3. The new `dist/Fenrir.exe` replaces the old one

### Pro Tip: No Uninstall Needed

Because Fenrir is just:
- Python source files (runs from source, or
- `Fenrir.exe` (single file, no registry entries)

Updates are **replace, not reinstall**. No uninstaller needed. Just overwrite the old .exe with the new one, or re-pull the source.

---

## Key Shortcuts

| Key | Action |
|---|---|
| `Ctrl+O` | Open PDF |
| `Ctrl+F` | Search |
| `Ctrl+E` | Toggle Editor Tools |
| `Ctrl+P` | Print |
| `F11` | Fullscreen |
| `Ctrl++` / `Ctrl+-` | Zoom in / out |
| `Ctrl+0` | Fit to page |

---

## Project Structure

```
fenrir-reader/
├── main.py                  # Entry point
├── build.py                 # PyInstaller build script
├── src/
│   ├── engine/
│   │   └── document.py      # PDF engine (PyMuPDF wrapper)
│   ├── viewer/
│   │   └── canvas.py        # Page viewer/canvas
│   ├── editor/
│   │   ├── annotations.py   # Annotation models + I/O
│   │   └── widgets.py       # Editor toolbar UI
│   ├── sidebar/
│   │   └── panels.py        # TOC, thumbnails, search results
│   ├── dialogs/             # Search, goto dialogs
│   ├── utils/               # Settings
│   └── main_window.py       # Main application window
├── resources/
│   └── icons/               # App icons
└── venv/                    # Python virtual env (Linux only)
```

## GitHub Repo

https://github.com/TheOnlyGingerNinja/Fenrir