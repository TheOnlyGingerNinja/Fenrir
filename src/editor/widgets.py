"""
Fenrir Editor — annotation toolbar and interaction widgets.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QPixmap, QPainter, QPen, QBrush, QAction
from PySide6.QtWidgets import (
    QWidget, QToolBar, QToolButton, QButtonGroup,
    QVBoxLayout, QHBoxLayout, QLabel, QColorDialog,
    QSlider, QSpinBox, QPushButton, QFrame,
    QSizePolicy, QMenu, QWidgetAction,
    QListWidget, QListWidgetItem, QGroupBox,
    QDialog, QTextEdit, QDialogButtonBox,
)


# ── Editor Tool IDs ────────────────────────────────────────────

TOOL_SELECT = "select"        # normal view/navigation
TOOL_HIGHLIGHT = "highlight"
TOOL_UNDERLINE = "underline"
TOOL_STRIKETHROUGH = "strikethrough"
TOOL_NOTE = "note"
TOOL_INK = "ink"
TOOL_TEXTBOX = "textbox"
TOOL_ERASER = "eraser"        # delete annotations

TOOL_ICONS = {
    TOOL_SELECT: "⇱",
    TOOL_HIGHLIGHT: "🖍",
    TOOL_UNDERLINE: "⎄",
    TOOL_STRIKETHROUGH: "⎅",
    TOOL_NOTE: "📌",
    TOOL_INK: "✎",
    TOOL_TEXTBOX: "T",
    TOOL_ERASER: "🗑",
}

TOOL_NAMES = {
    TOOL_SELECT: "Select / Navigate",
    TOOL_HIGHLIGHT: "Highlight",
    TOOL_UNDERLINE: "Underline",
    TOOL_STRIKETHROUGH: "Strikethrough",
    TOOL_NOTE: "Sticky Note",
    TOOL_INK: "Freehand Draw",
    TOOL_TEXTBOX: "Text Box",
    TOOL_ERASER: "Delete Annotation",
}


class EditorToolbar(QToolBar):
    """Floating / dockable toolbar for PDF annotation tools."""

    tool_changed = Signal(str)          # tool ID
    color_changed = Signal(tuple)       # RGB normalized
    opacity_changed = Signal(float)
    pen_width_changed = Signal(float)
    save_requested = Signal()
    undo_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("Editor Tools", parent)
        self._active_tool = TOOL_SELECT
        self._current_color = (1.0, 0.9, 0.2)  # yellow default
        self._current_opacity = 0.3
        self._pen_width = 2.0

        self.setIconSize(QSize(24, 24))
        self._setup_ui()

    def _setup_ui(self):
        # ── Tool buttons ──
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_group.idClicked.connect(self._on_tool_clicked)

        for i, tool_id in enumerate([
            TOOL_SELECT, TOOL_HIGHLIGHT, TOOL_UNDERLINE,
            TOOL_STRIKETHROUGH, TOOL_NOTE, TOOL_INK,
            TOOL_TEXTBOX, TOOL_ERASER,
        ]):
            btn = QToolButton()
            btn.setText(TOOL_ICONS[tool_id])
            btn.setToolTip(TOOL_NAMES[tool_id])
            btn.setCheckable(True)
            btn.setChecked(tool_id == TOOL_SELECT)
            btn.setMinimumWidth(32)
            btn.setMinimumHeight(32)
            stylesheet = """
                QToolButton { font-size: 16px; padding: 4px; border-radius: 4px; }
                QToolButton:checked { background: palette(highlight); color: white; }
                QToolButton:hover { background: palette(midlight); }
            """
            btn.setStyleSheet(stylesheet)

            self._tool_group.addButton(btn, i)
            self.addWidget(btn)

        self.addSeparator()

        # ── Color picker ──
        self._color_btn = QToolButton()
        self._color_btn.setToolTip("Annotation Color")
        self._color_btn.setMinimumWidth(32)
        self._color_btn.setMinimumHeight(32)
        self._update_color_button()
        self._color_btn.clicked.connect(self._on_pick_color)
        self.addWidget(self._color_btn)

        # ── Opacity slider ──
        self.addWidget(QLabel("  Opacity:"))
        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(5, 100)
        self._opacity_slider.setValue(30)
        self._opacity_slider.setFixedWidth(80)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.addWidget(self._opacity_slider)

        # ── Pen width ──
        self.addWidget(QLabel("  Width:"))
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 12)
        self._width_spin.setValue(2)
        self._width_spin.setFixedWidth(40)
        self._width_spin.valueChanged.connect(self._on_width_changed)
        self.addWidget(self._width_spin)

        self.addSeparator()

        # ── Action buttons ──
        save_btn = QToolButton()
        save_btn.setText("💾 Save")
        save_btn.setToolTip("Save annotations to PDF")
        save_btn.clicked.connect(self.save_requested.emit)
        self.addWidget(save_btn)

    def _on_tool_clicked(self, btn_id: int):
        tool_map = [
            TOOL_SELECT, TOOL_HIGHLIGHT, TOOL_UNDERLINE,
            TOOL_STRIKETHROUGH, TOOL_NOTE, TOOL_INK,
            TOOL_TEXTBOX, TOOL_ERASER,
        ]
        if btn_id < len(tool_map):
            self._active_tool = tool_map[btn_id]
            self.tool_changed.emit(self._active_tool)

    def _update_color_button(self):
        r, g, b = self._current_color
        qc = QColor(int(r * 255), int(g * 255), int(b * 255))
        pix = QPixmap(24, 24)
        pix.fill(qc)
        self._color_btn.setIcon(pix)

    def _on_pick_color(self):
        r, g, b = self._current_color
        qc = QColor(int(r * 255), int(g * 255), int(b * 255))
        color = QColorDialog.getColor(qc, self, "Annotation Color")
        if color.isValid():
            self._current_color = (color.red() / 255.0, color.green() / 255.0, color.blue() / 255.0)
            self._update_color_button()
            self.color_changed.emit(self._current_color)

    def _on_opacity_changed(self, value: int):
        self._current_opacity = value / 100.0
        self.opacity_changed.emit(self._current_opacity)

    def _on_width_changed(self, value: int):
        self._pen_width = float(value)
        self.pen_width_changed.emit(self._pen_width)

    @property
    def active_tool(self) -> str:
        return self._active_tool

    @property
    def current_color(self) -> tuple:
        return self._current_color

    @property
    def current_opacity(self) -> float:
        return self._current_opacity

    @property
    def current_pen_width(self) -> float:
        return self._pen_width

    def set_active_tool(self, tool_id: str):
        """Programmatically set the active tool."""
        tool_map = [
            TOOL_SELECT, TOOL_HIGHLIGHT, TOOL_UNDERLINE,
            TOOL_STRIKETHROUGH, TOOL_NOTE, TOOL_INK,
            TOOL_TEXTBOX, TOOL_ERASER,
        ]
        if tool_id in tool_map:
            idx = tool_map.index(tool_id)
            btn = self._tool_group.button(idx)
            if btn:
                btn.setChecked(True)
                self._active_tool = tool_id


class NoteEditDialog(QDialog):
    """Dialog for entering/editing sticky note content."""

    def __init__(self, content: str = "", title: str = "Sticky Note", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(350, 250)

        layout = QVBoxLayout(self)

        self._editor = QTextEdit()
        self._editor.setPlainText(content)
        self._editor.setPlaceholderText("Type your note here...")
        layout.addWidget(self._editor)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def content(self) -> str:
        return self._editor.toPlainText().strip()