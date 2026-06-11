# Fenrir PDF Reader — Build Script

Build standalone executables for distribution.

## Prerequisites

```bash
pip install pyinstaller
```

## Build Commands

### Linux
```bash
pyinstaller --name "Fenrir" \
  --windowed \
  --onefile \
  --icon resources/icons/fenrir.png \
  --add-data "resources/icons:resources/icons" \
  --hidden-import PySide6.QtCore \
  --hidden-import PySide6.QtGui \
  --hidden-import PySide6.QtWidgets \
  --hidden-import fitz \
  main.py
```

Output: `dist/Fenrir` (single binary)

### Windows
```bash
pyinstaller --name "Fenrir" ^
  --windowed ^
  --onefile ^
  --icon resources\icons\fenrir.png ^
  --add-data "resources\icons;resources\icons" ^
  --hidden-import PySide6.QtCore ^
  --hidden-import PySide6.QtGui ^
  --hidden-import PySide6.QtWidgets ^
  --hidden-import fitz ^
  main.py
```

Output: `dist/Fenrir.exe` (single .exe)

### Alternative: One-Click Build
```bash
python build.py
```