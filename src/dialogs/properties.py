"""Fenrir Document Properties Dialog."""

from __future__ import annotations

import os
import time
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QPushButton,
    QDialogButtonBox, QTabWidget, QWidget, QTextEdit,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.engine.document import FenrirDocument


class DocumentPropertiesDialog(QDialog):
    """Shows metadata, page info, and font details for a PDF."""

    def __init__(self, doc: FenrirDocument, parent=None):
        super().__init__(parent)
        self._doc = doc
        self.setWindowTitle("Document Properties")
        self.setMinimumSize(420, 360)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── General tab ──
        general = QWidget()
        form = QFormLayout(general)
        form.setLabelAlignment(Qt.AlignLeft)

        meta = self._doc.metadata
        filepath = self._doc.filepath

        form.addRow("File Name:", QLabel(os.path.basename(filepath)))
        form.addRow("Location:", QLabel(os.path.dirname(filepath)))

        try:
            size = os.path.getsize(filepath)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            form.addRow("File Size:", QLabel(size_str))
        except Exception:
            pass

        form.addRow("Pages:", QLabel(str(self._doc.page_count)))
        form.addRow("Title:", QLabel(meta.get("title", "(none)")))
        form.addRow("Author:", QLabel(meta.get("author", "(none)")))
        form.addRow("Subject:", QLabel(meta.get("subject", "(none)")))
        form.addRow("Keywords:", QLabel(meta.get("keywords", "(none)")))
        form.addRow("Producer:", QLabel(meta.get("producer", "(none)")))
        form.addRow("Creator:", QLabel(meta.get("creator", "(none)")))

        created = meta.get("creationDate", "")
        modified = meta.get("modDate", "")
        if created:
            form.addRow("Created:", QLabel(self._format_pdf_date(created)))
        if modified:
            form.addRow("Modified:", QLabel(self._format_pdf_date(modified)))

        tabs.addTab(general, "General")

        # ── Fonts tab ──
        fonts_tab = QWidget()
        fonts_layout = QVBoxLayout(fonts_tab)
        fonts_text = QTextEdit()
        fonts_text.setReadOnly(True)
        fonts_text.setMaximumHeight(200)
        font_info = self._get_font_info()
        fonts_text.setPlainText(font_info if font_info else "No font information available.")
        fonts_layout.addWidget(QLabel("Fonts used in this document:"))
        fonts_layout.addWidget(fonts_text)
        tabs.addTab(fonts_tab, "Fonts")

        # ── Security tab ──
        security = QWidget()
        sec_form = QFormLayout(security)
        sec_form.addRow("Encrypted:", QLabel("Yes" if self._doc.is_encrypted else "No"))
        tabs.addTab(security, "Security")

        # Close button
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _format_pdf_date(self, date_str: str) -> str:
        """Convert a PDF date string (D:20240301120000) to human-readable."""
        try:
            # Strip "D:" prefix if present
            d = date_str.lstrip("D:")
            if len(d) >= 8:
                y, m, day = d[:4], d[4:6], d[6:8]
                time_part = ""
                if len(d) >= 14:
                    h, mi, s = d[8:10], d[10:12], d[12:14]
                    time_part = f" {h}:{mi}:{s}"
                return f"{y}-{m}-{day}{time_part}"
        except Exception:
            pass
        return date_str

    def _get_font_info(self) -> str:
        """Extract font information from the first few pages."""
        lines = []
        seen = set()
        for i in range(min(self._doc.page_count, 10)):
            try:
                blocks = self._doc.doc[i].get_text("dict", flags=3)["blocks"]
                for block in blocks:
                    if block["type"] == 0:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                font_key = f"{span['font']} {span['size']:.1f}pt"
                                if font_key not in seen:
                                    seen.add(font_key)
                                    lines.append(font_key)
            except Exception:
                continue
        lines.sort()
        return "\n".join(lines) if lines else "(none)"