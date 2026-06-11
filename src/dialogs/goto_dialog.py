"""
Fenrir Go-to-Page Dialog.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QPushButton, QDialogButtonBox,
)


class GotoPageDialog(QDialog):
    """Simple dialog to jump to a specific page number."""

    def __init__(self, current_page: int, total_pages: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go to Page")
        self.setFixedWidth(280)

        layout = QVBoxLayout(self)

        label = QLabel(f"Enter page number (1–{total_pages}):")
        layout.addWidget(label)

        spin = QSpinBox()
        spin.setRange(1, total_pages)
        spin.setValue(current_page + 1)
        spin.selectAll()
        spin.setFocus()
        layout.addWidget(spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._spin = spin

    @property
    def page(self) -> int:
        return self._spin.value() - 1  # Convert to 0-based