"""
Fenrir PDF Reader — Application entry point.

Usage:
    python main.py [file.pdf]
"""
from __future__ import annotations

import sys
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Fenrir")
    app.setOrganizationName("FlowRidge")

    # Styling
    app.setStyle("Fusion")

    window = MainWindow()

    # Accept command-line file argument
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        if os.path.isfile(filepath):
            window.open_file(filepath)

    window.show()

    # Handle macOS "open file" events
    if hasattr(app, "openFile"):
        app.openFile.connect(window.open_file)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()