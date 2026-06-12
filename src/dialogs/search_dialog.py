"""
Fenrir Search Dialog — find text within PDF documents.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QCheckBox, QListWidget,
    QListWidgetItem, QProgressBar, QWidget, QApplication,
)


class SearchDialog(QDialog):
    """Search/find dialog with result list."""

    search_requested = Signal(str, bool)       # query, case_sensitive
    next_requested = Signal()
    prev_requested = Signal()
    result_selected = Signal(int, int)         # page_num, result_index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find in Document")
        self.setMinimumWidth(380)
        self.setMaximumWidth(500)

        layout = QVBoxLayout(self)

        # Search input row
        input_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search document...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.returnPressed.connect(self._do_search)
        input_row.addWidget(self._search_input)

        self._case_cb = QCheckBox("Aa")
        self._case_cb.setToolTip("Case sensitive")
        input_row.addWidget(self._case_cb)

        self._search_btn = QPushButton("Search")
        self._search_btn.clicked.connect(self._do_search)
        self._search_btn.setDefault(True)
        input_row.addWidget(self._search_btn)

        layout.addLayout(input_row)

        # Navigation row
        nav_row = QHBoxLayout()
        self._result_label = QLabel("")
        nav_row.addWidget(self._result_label)
        nav_row.addStretch()

        self._prev_btn = QPushButton("◀ Prev")
        self._prev_btn.clicked.connect(self.prev_requested.emit)
        self._prev_btn.setEnabled(False)
        nav_row.addWidget(self._prev_btn)

        self._next_btn = QPushButton("Next ▶")
        self._next_btn.clicked.connect(self.next_requested.emit)
        self._next_btn.setEnabled(False)
        nav_row.addWidget(self._next_btn)

        layout.addLayout(nav_row)

        # Result list
        self._result_list = QListWidget()
        self._result_list.setAlternatingRowColors(True)
        self._result_list.itemActivated.connect(self._on_result_activated)
        layout.addWidget(self._result_list)

        # Progress bar (hidden by default)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.hide()
        layout.addWidget(self._progress)

        self._total_results = 0

    def _do_search(self) -> None:
        query = self._search_input.text()
        case_sensitive = self._case_cb.isChecked()
        if query:
            self.search_requested.emit(query, case_sensitive)

    def show_searching(self) -> None:
        self._progress.show()
        self._search_btn.setEnabled(False)

    def hide_searching(self) -> None:
        self._progress.hide()
        self._search_btn.setEnabled(True)

    def show_results(self, results: list) -> None:
        self._result_list.clear()
        self._total_results = len(results)
        self._prev_btn.setEnabled(True)
        self._next_btn.setEnabled(True)

        if not results:
            self._result_label.setText("No results found")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            return

        self._result_label.setText(f"{len(results)} result(s) found")

        for i, r in enumerate(results):
            page_num = r["page"] + 1
            page_num_0idx = r["page"]
            text = r["text"].strip()
            display_text = text[:80] + ("..." if len(text) > 80 else "")
            item = QListWidgetItem(f"Page {page_num}:  {display_text}")
            item.setData(Qt.UserRole, i)
            # Store the page number (0-indexed) alongside the result index
            # so the activated handler can emit both values correctly.
            item.setData(Qt.UserRole + 1, page_num_0idx)
            self._result_list.addItem(item)

    def focus_input(self) -> None:
        self._search_input.setFocus()
        self._search_input.selectAll()

    def _on_result_activated(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.UserRole)
        page_num = item.data(Qt.UserRole + 1)
        if index is not None and page_num is not None:
            # Signal signature: result_selected(page_num, result_index)
            self.result_selected.emit(page_num, index)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_F3 and (event.modifiers() & Qt.ShiftModifier):
            self.prev_requested.emit()
        elif event.key() == Qt.Key_F3:
            self.next_requested.emit()
        elif event.key() == Qt.Key_N and (event.modifiers() & Qt.ControlModifier):
            if event.modifiers() & Qt.ShiftModifier:
                self.prev_requested.emit()
            else:
                self.next_requested.emit()
        else:
            super().keyPressEvent(event)