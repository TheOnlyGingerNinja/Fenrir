"""
Fenrir Sidebar — Table of Contents, Thumbnails, and Annotation List panels.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize, QRect, QThread, QObject
from PySide6.QtGui import QImage, QPixmap, QFont, QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QListWidget, QListWidgetItem, QListView, QLabel, QSplitter,
    QHBoxLayout, QPushButton, QFrame, QSizePolicy,
    QApplication, QStackedWidget, QMenu,
)

from src.engine.document import FenrirDocument
from src.editor.annotations import Annotation, AnnotationManager, ANNOT_TYPES


# ── Annotation emoji icons ──────────────────────────────────────

ANNOT_ICONS = {
    "highlight": "🖍",
    "underline": "⎄",
    "strikethrough": "⎅",
    "note": "📌",
    "ink": "✎",
    "textbox": "T",
    "rectangle": "▭",
    "circle": "○",
}


class AnnotationListPanel(QWidget):
    """Sidebar panel showing all annotations in the document."""

    page_navigated = Signal(int)
    delete_requested = Signal(str)  # annot_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._annot_manager: AnnotationManager | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("   Annotations")
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
        self._list.setAlternatingRowColors(True)
        self._list.setWordWrap(True)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list)

    def set_manager(self, manager: AnnotationManager | None) -> None:
        """Set the annotation manager and refresh the list."""
        self._annot_manager = manager
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the annotation list from the annotation manager."""
        self._list.clear()

        if not self._annot_manager:
            empty = QListWidgetItem("  (no annotations)")
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            empty.setForeground(QColor(128, 128, 128))
            self._list.addItem(empty)
            return

        all_annots = self._annot_manager.all_annotations()
        if not all_annots:
            empty = QListWidgetItem("  (no annotations)")
            empty.setFlags(empty.flags() & ~Qt.ItemIsSelectable)
            empty.setForeground(QColor(128, 128, 128))
            self._list.addItem(empty)
            return

        # Sort by page number
        all_annots.sort(key=lambda a: (a.page, a.date_created))

        for annot in all_annots:
            icon = ANNOT_ICONS.get(annot.type, "📄")
            page_num = annot.page + 1
            color_str = ""
            if annot.color:
                r, g, b = annot.color[:3]
                color_str = f"  <font color='#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'>■</font>"

            # Content preview
            content = annot.content or ""
            if not content and annot.type == "highlight":
                content = "(highlighted text)"
            elif not content:
                content = f"({annot.type})"
            preview = content[:60] + ("..." if len(content) > 60 else "")

            text = f"{icon}  Page {page_num}{color_str}  {preview}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, annot.id)
            item.setData(Qt.UserRole + 1, annot.page)
            item.setToolTip(f"{annot.type} on page {page_num}\n{content}")
            self._list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """Navigate to the page containing this annotation."""
        page = item.data(Qt.UserRole + 1)
        if page is not None:
            self.page_navigated.emit(page)

    def _on_context_menu(self, pos) -> None:
        """Show right-click context menu for an annotation."""
        item = self._list.itemAt(pos)
        if not item:
            return
        annot_id = item.data(Qt.UserRole)
        if not annot_id:
            return

        menu = QMenu(self)
        delete_action = menu.addAction("🗑 Delete Annotation")
        action = menu.exec(self._list.mapToGlobal(pos))
        if action == delete_action:
            self.delete_requested.emit(annot_id)


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
        self._list.setViewMode(QListView.ListMode)
        self._list.setIconSize(QSize(140, 180))
        self._list.setSpacing(4)
        self._list.setFlow(QListView.TopToBottom)
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
    delete_requested = Signal(str)

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

        self._annot_btn = QPushButton("✎ Annots")
        self._annot_btn.setCheckable(True)
        self._annot_btn.clicked.connect(lambda: self._switch_tab(2))
        self._annot_btn.setStyleSheet(self._toc_btn.styleSheet())

        tab_bar.addWidget(self._toc_btn)
        tab_bar.addWidget(self._thumb_btn)
        tab_bar.addWidget(self._annot_btn)
        tab_bar.addStretch()

        layout.addLayout(tab_bar)

        # Stack area
        self._stack = QStackedWidget(self)
        self._outline = OutlinePanel()
        self._thumbnails = ThumbnailPanel()
        self._annotations = AnnotationListPanel()
        self._stack.addWidget(self._outline)
        self._stack.addWidget(self._thumbnails)
        self._stack.addWidget(self._annotations)
        layout.addWidget(self._stack)

        # Connect navigation signals
        self._outline.page_navigated.connect(self.page_navigated.emit)
        self._thumbnails.page_navigated.connect(self.page_navigated.emit)
        self._annotations.page_navigated.connect(self.page_navigated.emit)

        # Propagate delete from annotation panel
        self._annotations.delete_requested.connect(self.delete_requested.emit)

        self.setMinimumWidth(180)
        self.setMaximumWidth(300)

    def load(self, doc: FenrirDocument) -> None:
        self._doc = doc
        self._outline.load(doc)
        self._thumbnails.load(doc)

    def set_annotation_manager(self, manager: AnnotationManager | None) -> None:
        """Pass the annotation manager to the annotations panel."""
        self._annotations.set_manager(manager)

    def refresh_annotations(self) -> None:
        """Rebuild the annotation list (call after add/delete)."""
        self._annotations.refresh()

    def highlight_page(self, page_num: int) -> None:
        self._thumbnails.highlight_page(page_num)

    def _switch_tab(self, index: int) -> None:
        self._current_tab = index
        self._stack.setCurrentIndex(index)
        self._toc_btn.setChecked(index == 0)
        self._thumb_btn.setChecked(index == 1)
        self._annot_btn.setChecked(index == 2)