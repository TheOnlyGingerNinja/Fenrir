"""
Fenrir Sidebar — Table of Contents and Thumbnails panels.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize, QRect, QThread, QObject
from PySide6.QtGui import QImage, QPixmap, QFont, QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QListWidget, QListWidgetItem, QLabel, QSplitter,
    QHBoxLayout, QPushButton, QFrame, QSizePolicy,
    QApplication, QStackedWidget,
)

from src.engine.document import FenrirDocument


class OutlinePanel(QWidget):
    """Table of contents / bookmarks sidebar panel."""

    page_navigated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: FenrirDocument | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("   Table of Contents")
        header.setStyleSheet("""
            QLabel {
                background: palette(window);
                padding: 8px;
                font-weight: bold;
                border-bottom: 1px solid palette(midlight);
            }
        """)
        layout.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setAnimated(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

    def load(self, doc: FenrirDocument) -> None:
        self._doc = doc
        self._tree.clear()
        if not doc:
            return

        toc = doc.get_toc()
        if not toc:
            empty = QTreeWidgetItem(["  (no bookmarks)"])
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            empty.setForeground(0, QColor(128, 128, 128))
            self._tree.addTopLevelItem(empty)
            return

        # Build tree from flat list with level info
        parent_stack: list[QTreeWidgetItem] = []
        for item in toc:
            level, title, page = item["level"], item["title"], item["page"]
            tree_item = QTreeWidgetItem([f"  {title}"])
            tree_item.setData(0, Qt.UserRole, page)
            tree_item.setToolTip(0, f"Page {page + 1}")

            if level == 1:
                self._tree.addTopLevelItem(tree_item)
                parent_stack = [tree_item]
            else:
                # Find correct parent based on level
                while len(parent_stack) >= level:
                    parent_stack.pop()
                if parent_stack:
                    parent_stack[-1].addChild(tree_item)
                else:
                    self._tree.addTopLevelItem(tree_item)
                parent_stack.append(tree_item)

        # Expand first level
        self._tree.expandToDepth(1)

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        page = item.data(0, Qt.UserRole)
        if page is not None:
            self.page_navigated.emit(page)


class ThumbnailPanel(QWidget):
    """Page thumbnail previews sidebar panel."""

    page_navigated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: FenrirDocument | None = None
        self._thumbnails: dict[int, QPixmap] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("   Thumbnails")
        header.setStyleSheet("""
            QLabel {
                background: palette(window);
                padding: 8px;
                font-weight: bold;
                border-bottom: 1px solid palette(midlight);
            }
        """)
        layout.addWidget(header)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ListMode)
        self._list.setIconSize(QSize(140, 180))
        self._list.setSpacing(4)
        self._list.setFlow(QListWidget.TopToBottom)
        self._list.setWordWrap(True)
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

    def load(self, doc: FenrirDocument) -> None:
        self._doc = doc
        self._list.clear()
        self._thumbnails.clear()

        if not doc:
            return

        for i in range(doc.page_count):
            page_num = i + 1
            item = QListWidgetItem(f"  {page_num}")
            item.setData(Qt.UserRole, i)
            item.setSizeHint(QSize(140, 200))

            # Render thumbnail asynchronously (small size)
            thumb = doc.render_thumbnail(i, max_size=160)
            pix = QPixmap.fromImage(thumb)
            self._thumbnails[i] = pix
            item.setIcon(pix)
            self._list.addItem(item)

    def _on_row_changed(self, row: int) -> None:
        if row >= 0:
            item = self._list.item(row)
            page = item.data(Qt.UserRole)
            if page is not None:
                self.page_navigated.emit(page)

    def highlight_page(self, page_num: int) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == page_num:
                self._list.blockSignals(True)
                self._list.setCurrentRow(i)
                self._list.blockSignals(False)
                break


class SidebarWidget(QWidget):
    """Container for sidebar panels with tab-style switching."""

    page_navigated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: FenrirDocument | None = None
        self._current_tab = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab buttons
        tab_bar = QHBoxLayout()
        tab_bar.setContentsMargins(0, 0, 0, 0)
        tab_bar.setSpacing(0)

        self._toc_btn = QPushButton("📑 TOC")
        self._toc_btn.setCheckable(True)
        self._toc_btn.setChecked(True)
        self._toc_btn.clicked.connect(lambda: self._switch_tab(0))
        self._toc_btn.setStyleSheet("""
            QPushButton {
                border: none; padding: 8px 12px;
                border-right: 1px solid palette(midlight);
                background: palette(window);
                font-size: 12px;
            }
            QPushButton:checked {
                background: palette(highlight);
                color: palette(highlighted-text);
            }
        """)

        self._thumb_btn = QPushButton("🖼 Thumbs")
        self._thumb_btn.setCheckable(True)
        self._thumb_btn.clicked.connect(lambda: self._switch_tab(1))
        self._thumb_btn.setStyleSheet(self._toc_btn.styleSheet())

        tab_bar.addWidget(self._toc_btn)
        tab_bar.addWidget(self._thumb_btn)
        tab_bar.addStretch()

        layout.addLayout(tab_bar)

        # Stack area
        self._stack = QStackedWidget(self)
        self._outline = OutlinePanel()
        self._thumbnails = ThumbnailPanel()
        self._stack.addWidget(self._outline)
        self._stack.addWidget(self._thumbnails)
        layout.addWidget(self._stack)

        # Connect navigation signals
        self._outline.page_navigated.connect(self.page_navigated.emit)
        self._thumbnails.page_navigated.connect(self.page_navigated.emit)

        self.setMinimumWidth(180)
        self.setMaximumWidth(300)

    def load(self, doc: FenrirDocument) -> None:
        self._doc = doc
        self._outline.load(doc)
        self._thumbnails.load(doc)

    def highlight_page(self, page_num: int) -> None:
        self._thumbnails.highlight_page(page_num)

    def _switch_tab(self, index: int) -> None:
        self._current_tab = index
        self._stack.setCurrentIndex(index)
        self._toc_btn.setChecked(index == 0)
        self._thumb_btn.setChecked(index == 1)


