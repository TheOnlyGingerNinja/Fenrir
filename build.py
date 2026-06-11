#!/usr/bin/env python3
"""Fenrir — Cross-platform build script (PyInstaller)."""

import os
import sys
import platform
import shutil
import subprocess

APP_NAME = "Fenrir"
ICON = os.path.join("resources", "icons", "fenrir.png")
MAIN = "main.py"

SYSTEM = platform.system()


def build():
    dist_dir = os.path.join(os.path.dirname(__file__) or ".", "dist")
    if os.path.isdir(dist_dir):
        shutil.rmtree(dist_dir)

    cmd = [
        "pyinstaller",
        "--name", APP_NAME,
        "--windowed",
        "--onefile",
        f"--icon={ICON}",
    ]

    # Bundle resources: platform-specific separator
    if SYSTEM == "Windows":
        cmd.append(f'--add-data=resources\\icons;resources\\icons')
        cmd.append("--distpath=dist")
    else:
        cmd.append('--add-data=resources/icons:resources/icons')
        cmd.append("--distpath=dist")

    cmd.extend([
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "fitz",
        "--hidden-import", "src.engine.document",
        "--hidden-import", "src.editor.annotations",
        "--hidden-import", "src.editor.widgets",
        "--hidden-import", "src.viewer.canvas",
        "--hidden-import", "src.main_window",
        "--hidden-import", "src.sidebar.panels",
        "--hidden-import", "src.dialogs.search_dialog",
        "--hidden-import", "src.dialogs.goto_dialog",
        "--hidden-import", "src.utils.settings",
        MAIN,
    ])

    print(f"🔨 Building Fenrir for {SYSTEM}...")
    print(f"   Command: {' '.join(cmd[:8])} ...")
    result = subprocess.run(cmd, cwd=os.path.dirname(__file__) or ".")
    if result.returncode == 0:
        print(f"\n✅ Build complete!")
        if SYSTEM == "Windows":
            print(f"   dist/{APP_NAME}.exe")
        else:
            print(f"   dist/{APP_NAME}")
    else:
        print(f"\n❌ Build failed (code {result.returncode})")
        sys.exit(1)


if __name__ == "__main__":
    build()