"""
Fenrir Viewer Canvas — PDF rendering, scrolling, zooming, and text selection.
"""
from __future__ import annotations

import math

import fitz
from PySide6.QtCore import (
    Qt, QRectF, QPointF, QSizeF, Signal, Slot, QTimer
)
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QPen, QColor, QBrush, QFont,
    QTransform, QPolygonF, QTextDocument, QTextCursor, QCursor,
    QKeySequence, QAction,
)
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsItem, QGraphicsTextItem,
    QWidget, QVBoxLayout, QScrollBar, QApplication, QRubberBand,
    QGraphicsSimpleTextItem, QLineEdit, QDialog, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QComboBox,
)

from src.engine.document import FenrirDocument
from src.editor.annotations import Annotation, AnnotationManager
from src.editor.widgets import TOOL_SELECT, TOOL_HIGHLIGHT, TOOL_UNDERLINE, \
    TOOL_STRIKETHROUGH, TOOL_NOTE, TOOL_INK, TOOL_TEXTBOX, TOOL_ERASER, NoteEditDialog


# ── constants ──────────────────────────────────────────────────

ZOOM_LEVELS = [
    0.25, 0.33, 0.50, 0.67, 0.75, 0.80, 0.90,
    1.00, 1.25, 1.50, 1.75, 2.00, 2.50, 3.00, 4.00, 5.00,
]
BASE_DPI = 150.0
PAGE_GAP = 12  # pixels between pages in continuous mode
MARGIN = 20    # margin around pages
MIN_PAGE_WIDTH = 50  # minimum zoomed page width before we switch to page-level rendering


class PageGraphicsItem(QGraphicsPixmapItem):
    """A single PDF page rendered as a pixmap in the scene."""

    def __init__(self, page_num: int, page_rect: QRectF, parent=None):
        super().__init__(parent)
        self.page_num = page_num
        self.page_rect = page_rect  # original page rect in points
        self.search_highlights: list[QGraphicsRectItem] = []

    def clear_search_highlights(self):
        for h in self.search_highlights:
            scene = self.scene()
            if scene:
                scene.removeItem(h)
        self.search_highlights.clear()


class TextSelectionOverlay:
    """Manages text selection state on the canvas."""

    def __init__(self, canvas: "PdfCanvas"):
        self.canvas = canvas
        self.is_selecting = False
        self.anchor_page = -1
        self.anchor_pos = QPointF()
        self.current_pos = QPointF()
        self.selection_rects: list[QGraphicsRectItem] = []

    def clear(self):
        for r in self.selection_rects:
            scene = self.canvas.scene()
            if scene:
                scene.removeItem(r)
        self.selection_rects.clear()
        self.is_selecting = False
        self.anchor_page = -1


class SearchResult:
    def __init__(self, page: int, text: str, rect: fitz.Rect):
        self.page = page
        self.text = text
        self.rect = rect


class PdfCanvas(QGraphicsView):
    """Main PDF rendering viewport with scroll, zoom, and selection."""

    # Signals
    page_changed = Signal(int)       # Emitted when current visible page changes
    zoom_changed = Signal(float)     # Emitted when zoom changes
    text_selected = Signal(str)      # Emitted when text is selected
    search_result_clicked = Signal(int)  # Emitted when a search result is activated
    document_loaded = Signal()       # Emitted after a document finishes loading
    annotation_created = Signal(object)  # Emitted when an annotation is created
    annotation_deleted = Signal(str)     # Emitted when an annotation is deleted

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        # Document state
        self._doc: FenrirDocument | None = None
        self._page_items: list[PageGraphicsItem] = []
        self._pixmap_cache: dict[int, QPixmap] = {}  # page_num -> rendered pixmap
        self._visible_range = (0, 0)  # (first_visible, last_visible)

        # View settings
        self._zoom = 1.0
        self._fit_mode = None  # "width", "page", or None
        self._continuous = True
        self._dark_mode = False
        self._dpi = BASE_DPI

        # Navigation state
        self._current_page = 0
        self._target_page: int | None = None  # for programmatic jump
        self._scroll_animation_timer = QTimer(self)
        self._scroll_animation_timer.setSingleShot(True)
        self._scroll_animation_timer.timeout.connect(self._finish_scroll_animation)

        # Rendering state
        self._pending_render: set[int] = set()
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(80)  # debounce renders
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_visible_pages)

        # Selection state
        self._selection = TextSelectionOverlay(self)
        self._selection_mode = False  # True when Ctrl is held / text tool active

        # Annotation state
        self._annot_manager: AnnotationManager | None = None
        self._annot_items: dict[str, QGraphicsItem] = {}  # annot_id -> overlay item
        self._active_tool: str = TOOL_SELECT
        self._editor_color: tuple = (1.0, 0.9, 0.2)
        self._editor_opacity: float = 0.3
        self._editor_width: float = 2.0
        self._ink_points: list[list[list[float]]] = []  # [[[x,y], ...], ...]
        self._current_stroke: list = []  # current in-progress ink stroke

        # Form fill state
        self._form_mode: bool = False
        self._form_fields: dict[int, list[dict]] = {}  # page_num -> [field_dict, ...]
        self._form_items: dict[str, QGraphicsItem] = {}  # field_key -> overlay item
        self._form_text_input: QLineEdit | None = None  # active text field widget
        self._form_active_field: str | None = None  # key of currently focused field

        # Search results
        self._search_results: list[SearchResult] = []
        self._search_index = -1
        self._search_items: list[QGraphicsRectItem] = []

        # Appearance
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setBackgroundBrush(QBrush(QColor(60, 60, 60)))

        # Enable drop
        self.setAcceptDrops(True)

        # Keyboard scroll pacing
        self._key_scroll_amount = 60

    # ── document management ─────────────────────────────────────

    def load_document(self, doc: FenrirDocument) -> None:
        """Load a new document and render the first page."""
        self._doc = doc
        self._page_items.clear()
        self._pixmap_cache.clear()
        self._current_page = 0
        self._target_page = None
        self._selection.clear()
        self._clear_search_results()
        self._clear_annotation_overlays()
        self._scene.clear()

        # Initialize annotation manager
        if doc:
            self._annot_manager = AnnotationManager(doc)

        self._build_pages()
        self._render_visible_pages()
        self._render_annotation_overlays()
        self.document_loaded.emit()

    def close_document(self) -> None:
        """Unload the current document."""
        if self._doc:
            self._doc.close()
            self._doc = None
        self._annot_manager = None
        self._page_items.clear()
        self._pixmap_cache.clear()
        self._search_results.clear()
        self._annot_items.clear()
        self._scene.clear()
        self._current_page = 0

    @property
    def document(self) -> FenrirDocument | None:
        return self._doc

    @property
    def current_page(self) -> int:
        """Get the page number that is currently most visible."""
        return self._current_page

    @property
    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    # ── page layout ─────────────────────────────────────────────

    def _build_pages(self) -> None:
        """Create PageGraphicsItem for each page and arrange them vertically."""
        if not self._doc:
            return

        self._page_items = []
        y_offset = MARGIN
        self._page_height_cache = {}

        for i in range(self._doc.page_count):
            size = self._doc.page_size(i, dpi=72.0)
            pw, ph = size.width(), size.height()
            # Convert points to pixels at current zoom
            ratio = self._dpi / 72.0
            w = pw * ratio * self._zoom
            h = ph * ratio * self._zoom

            self._page_height_cache[i] = h

            rect = QRectF(MARGIN, y_offset, w, h)
            item = PageGraphicsItem(i, rect)

            # Placeholder border while loading
            item.setPos(MARGIN, y_offset)
            item.setFlag(QGraphicsItem.ItemIsSelectable, False)

            self._scene.addItem(item)
            self._page_items.append(item)
            y_offset += h + PAGE_GAP

        self._update_scene_rect()

    def _update_scene_rect(self) -> None:
        """Update the scene bounding rectangle."""
        if not self._page_items:
            return
        last = self._page_items[-1]
        total_w = last.pos().x() + last.page_rect.width() + MARGIN
        total_h = last.pos().y() + last.page_rect.height() + MARGIN
        self._scene.setSceneRect(QRectF(0, 0, total_w, total_h))

    # ── rendering ───────────────────────────────────────────────

    def _render_visible_pages(self) -> None:
        """Render pages that are currently visible in the viewport."""
        if not self._doc or not self._page_items:
            return

        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        dirty = set()

        for item in self._page_items:
            item_rect = QRectF(
                item.pos(), QSizeF(item.page_rect.width(), item.page_rect.height())
            )
            if visible_rect.intersects(item_rect):
                pn = item.page_num
                dirty.add(pn)

        # Don't re-render what's already cached
        need_render = dirty - self._pixmap_cache.keys()
        for pn in dirty:
            if pn not in self._pixmap_cache:
                self._render_page_to_cache(pn)

        # Apply pixmaps
        for item in self._page_items:
            if item.page_num in self._pixmap_cache:
                item.setPixmap(self._pixmap_cache[item.page_num])
                item.setPos(item.page_rect.topLeft())

        # Update visible page
        self._update_current_page(visible_rect)

    def _render_page_to_cache(self, page_num: int) -> None:
        """Render a single page and cache it."""
        if not self._doc:
            return
        img = self._doc.render_page(page_num, dpi=self._dpi * self._zoom)
        # Scale to our actual display size
        pw, ph = self._doc.page_size(page_num, dpi=72.0).toTuple()
        ratio = (self._dpi * self._zoom) / 72.0
        target_w = int(pw * ratio)
        target_h = int(ph * ratio)
        if img.width() != target_w or img.height() != target_h:
            img = img.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._pixmap_cache[page_num] = QPixmap.fromImage(img)

    def _update_current_page(self, visible_rect: QRectF | None = None) -> None:
        """Determine which page is most visible."""
        if not self._page_items:
            return
        if visible_rect is None:
            visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()

        center_y = visible_rect.center().y()
        best_page = 0
        best_dist = float("inf")

        for item in self._page_items:
            item_y = item.pos().y() + item.page_rect.height() / 2
            dist = abs(center_y - item_y)
            if dist < best_dist:
                best_dist = dist
                best_page = item.page_num

        if best_page != self._current_page:
            self._current_page = best_page
            self.page_changed.emit(best_page)

    def clear_page_cache(self) -> None:
        """Clear the pixmap cache (after zoom or rotation change)."""
        self._pixmap_cache.clear()
        self._render_timer.start()

    # ── resize event ────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode and self._page_items:
            self._apply_fit()
        if self._doc:
            self._render_timer.start()

    # ── zoom ────────────────────────────────────────────────────

    def zoom_to(self, factor: float) -> None:
        """Set zoom to a specific factor."""
        self._zoom = max(0.1, min(10.0, factor))
        self._fit_mode = None
        self._rebuild_and_render()
        self.zoom_changed.emit(self._zoom)

    def zoom_in(self) -> None:
        """Zoom in one level."""
        next_zoom = self._next_zoom_level(self._zoom, up=True)
        self.zoom_to(next_zoom)

    def zoom_out(self) -> None:
        """Zoom out one level."""
        next_zoom = self._next_zoom_level(self._zoom, up=False)
        self.zoom_to(next_zoom)

    def zoom_fit_width(self) -> None:
        """Zoom so the current page fits the viewport width."""
        self._fit_mode = "width"
        self._apply_fit()

    def zoom_fit_page(self) -> None:
        """Zoom so the current page fits entirely in the viewport."""
        self._fit_mode = "page"
        self._apply_fit()

    def zoom_actual_size(self) -> None:
        """Zoom to 100% (1 point = 1 pixel at 72 DPI)."""
        self._fit_mode = None
        self._zoom = 72.0 / self._dpi
        self._rebuild_and_render()

    @property
    def zoom(self) -> float:
        return self._zoom

    def _next_zoom_level(self, current: float, up: bool = True) -> float:
        """Find the next zoom level in ZOOM_LEVELS."""
        if up:
            for z in ZOOM_LEVELS:
                if z > current * 1.01:
                    return z
            return ZOOM_LEVELS[-1]
        else:
            for z in reversed(ZOOM_LEVELS):
                if z < current * 0.99:
                    return z
            return ZOOM_LEVELS[0]

    def _apply_fit(self) -> None:
        """Apply the current fit mode."""
        if not self._doc or not self._page_items:
            return
        view_w = self.viewport().width()
        view_h = self.viewport().height()

        if self._fit_mode == "width":
            pw, ph = self._doc.page_size(self._current_page, dpi=72.0).toTuple()
            if pw > 0:
                ratio = (self._dpi / 72.0)
                self._zoom = (view_w - 2 * MARGIN) / (pw * ratio)
                self._zoom = max(0.1, min(10.0, self._zoom))
                self._rebuild_and_render()
                self.zoom_changed.emit(self._zoom)

        elif self._fit_mode == "page":
            pw, ph = self._doc.page_size(self._current_page, dpi=72.0).toTuple()
            if pw > 0 and ph > 0:
                ratio = self._dpi / 72.0
                zoom_w = (view_w - 2 * MARGIN) / (pw * ratio)
                zoom_h = (view_h - 2 * MARGIN) / (ph * ratio)
                self._zoom = min(zoom_w, zoom_h)
                self._zoom = max(0.1, min(10.0, self._zoom))
                self._rebuild_and_render()
                self.zoom_changed.emit(self._zoom)

    def _rebuild_and_render(self) -> None:
        """Rebuild page layout and re-render after zoom change."""
        self._clear_search_items()
        self._clear_annotation_overlays()
        self._clear_form_overlays()
        self._scene.clear()
        self._page_items.clear()
        self._pixmap_cache.clear()
        self._annot_items.clear()
        if self._doc:
            self._build_pages()
            self._render_visible_pages()
            self._show_search_results()
            self._render_annotation_overlays()
            if self._form_mode:
                self._render_form_overlays()

    # ── wheel zoom ──────────────────────────────────────────────

    def wheelEvent(self, event) -> None:
        """Scroll vertically by default; zoom with Ctrl+Wheel."""
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    # ── navigation ──────────────────────────────────────────────

    def go_to_page(self, page_num: int) -> None:
        """Navigate to a specific page by number (0-based)."""
        if not self._doc or not self._page_items:
            return
        page_num = max(0, min(self._doc.page_count - 1, page_num))

        if page_num < len(self._page_items):
            item = self._page_items[page_num]
            target_y = item.pos().y() - MARGIN
            self.verticalScrollBar().setValue(int(target_y))
            self._current_page = page_num
            self.page_changed.emit(page_num)

    def go_to_next_page(self) -> None:
        self.go_to_page(self._current_page + 1)

    def go_to_prev_page(self) -> None:
        self.go_to_page(self._current_page - 1)

    def go_to_first_page(self) -> None:
        self.go_to_page(0)

    def go_to_last_page(self) -> None:
        if self._doc:
            self.go_to_page(self._doc.page_count - 1)

    def scroll_by(self, dy: int) -> None:
        """Scroll the view by dy pixels."""
        sb = self.verticalScrollBar()
        sb.setValue(sb.value() + dy)

    # ── rotation ────────────────────────────────────────────────

    def rotate_clockwise(self) -> None:
        if self._doc:
            self._doc.rotate_all(90)
            self._rebuild_and_render()

    def rotate_counterclockwise(self) -> None:
        if self._doc:
            self._doc.rotate_all(-90)
            self._rebuild_and_render()

    # ── text selection ──────────────────────────────────────────

    def _page_at_pos(self, scene_pos: QPointF) -> tuple[int, QPointF] | None:
        """Find the page and local position for a scene position."""
        for item in self._page_items:
            rect = QRectF(
                item.pos(), QSizeF(item.page_rect.width(), item.page_rect.height())
            )
            if rect.contains(scene_pos):
                local = scene_pos - item.pos()
                return item.page_num, local
        return None

    def _page_index_at_pos(self, scene_pos: QPointF) -> int | None:
        """Find just the page index at a scene position."""
        for item in self._page_items:
            rect = QRectF(
                item.pos(), QSizeF(item.page_rect.width(), item.page_rect.height())
            )
            if rect.contains(scene_pos):
                return item.page_num
        return None

    def _scene_to_page_coords(self, page_num: int, scene_pos: QPointF) -> tuple[float, float]:
        """Convert scene coordinates to PDF page coordinates (points)."""
        if page_num >= len(self._page_items):
            return (0.0, 0.0)
        item = self._page_items[page_num]
        local = scene_pos - item.pos()
        ratio = self._dpi * self._zoom / 72.0
        return (local.x() / ratio, local.y() / ratio)

    def _page_to_scene_coords(self, page_num: int, page_x: float, page_y: float) -> QPointF:
        """Convert PDF page coordinates to scene coordinates."""
        if page_num >= len(self._page_items):
            return QPointF(0, 0)
        item = self._page_items[page_num]
        ratio = self._dpi * self._zoom / 72.0
        return QPointF(
            item.pos().x() + page_x * ratio,
            item.pos().y() + page_y * ratio,
        )

    def _page_rect_to_scene(self, page_num: int, rect: tuple) -> QRectF:
        """Convert a page-coordinate rect (x0,y0,x1,y1) to scene coords."""
        if page_num >= len(self._page_items):
            return QRectF()
        item = self._page_items[page_num]
        ratio = self._dpi * self._zoom / 72.0
        return QRectF(
            item.pos().x() + rect[0] * ratio,
            item.pos().y() + rect[1] * ratio,
            (rect[2] - rect[0]) * ratio,
            (rect[3] - rect[1]) * ratio,
        )

    def mousePressEvent(self, event) -> None:
        scene_pos = self.mapToScene(event.pos())

        # ── Form Fill Mode: interact with form fields ──
        if event.button() == Qt.LeftButton and self._form_mode:
            self._cancel_form_input()
            page_num = self._page_index_at_pos(scene_pos)
            if page_num is not None and page_num in self._form_fields:
                px, py = self._scene_to_page_coords(page_num, scene_pos)
                for field in self._form_fields[page_num]:
                    r = field["rect"]
                    if r.x0 <= px <= r.x1 and r.y0 <= py <= r.y1:
                        if field["is_readonly"]:
                            break
                        self._on_form_field_click(page_num, field, scene_pos)
                        return
            return

        # ── Highlight / Underline / Strikethrough: start selection ──
        if event.button() == Qt.LeftButton and self._active_tool in (
            TOOL_HIGHLIGHT, TOOL_UNDERLINE, TOOL_STRIKETHROUGH,
        ):
            hit = self._page_at_pos(scene_pos)
            if hit:
                self._selection.is_selecting = True
                self._selection.anchor_page = hit[0]
                self._selection.anchor_pos = hit[1]
                self._selection.current_pos = hit[1]
                self._update_selection_overlay()
                return

        # ── Sticky Note: place on click ──
        if event.button() == Qt.LeftButton and self._active_tool == TOOL_NOTE:
            page_num = self._page_index_at_pos(scene_pos)
            if page_num is not None:
                px, py = self._scene_to_page_coords(page_num, scene_pos)
                rect = (px - 10, py - 10, px + 10, py + 10)
                dialog = NoteEditDialog("", "Sticky Note", self)
                if dialog.exec():
                    text = dialog.content
                    if text and self._annot_manager:
                        annot = self._annot_manager.add_note(page_num, rect, text)
                        self._render_annotation_overlays()
                        self.annotation_created.emit(annot)
                return

        # ── Text Box: place on click, then edit text ──
        if event.button() == Qt.LeftButton and self._active_tool == TOOL_TEXTBOX:
            page_num = self._page_index_at_pos(scene_pos)
            if page_num is not None:
                px, py = self._scene_to_page_coords(page_num, scene_pos)
                size = 80 / (self._dpi * self._zoom / 72.0)  # ~80px wide
                rect = (px, py, px + size, py + size * 0.3)
                dialog = NoteEditDialog("", "Text Box", self)
                if dialog.exec():
                    text = dialog.content
                    if text and self._annot_manager:
                        annot = self._annot_manager.add_textbox(page_num, rect, text)
                        self._render_annotation_overlays()
                        self.annotation_created.emit(annot)
                return

        # ── Ink: start drawing ──
        if event.button() == Qt.LeftButton and self._active_tool == TOOL_INK:
            page_num = self._page_index_at_pos(scene_pos)
            if page_num is not None:
                px, py = self._scene_to_page_coords(page_num, scene_pos)
                self._ink_points = []
                self._current_stroke = [[px, py]]
                return

        # ── Eraser: find and delete annotation ──
        if event.button() == Qt.LeftButton and self._active_tool == TOOL_ERASER:
            # Check if click is near an annotation
            page_num = self._page_index_at_pos(scene_pos)
            if page_num is not None and self._annot_manager:
                px, py = self._scene_to_page_coords(page_num, scene_pos)
                deleted = False
                for annot in self._annot_manager.for_page(page_num):
                    r = annot.rect
                    if r[0] <= px <= r[2] and r[1] <= py <= r[3]:
                        self._annot_manager.remove(annot.id)
                        self.annotation_deleted.emit(annot.id)
                        deleted = True
                        break
                if deleted:
                    self._render_annotation_overlays()
                return

        # ── Select tool: normal drag / text selection ──
        if event.button() == Qt.LeftButton and self._active_tool == TOOL_SELECT and self._selection_mode:
            hit = self._page_at_pos(scene_pos)
            if hit:
                self._selection.is_selecting = True
                self._selection.anchor_page = hit[0]
                self._selection.anchor_pos = hit[1]
                self._selection.current_pos = hit[1]
                self._update_selection_overlay()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        scene_pos = self.mapToScene(event.pos())

        # Text selection in progress
        if self._selection.is_selecting:
            hit = self._page_at_pos(scene_pos)
            if hit and hit[0] == self._selection.anchor_page:
                self._selection.current_pos = hit[1]
                self._update_selection_overlay()
            return

        # Ink drawing in progress
        if self._active_tool == TOOL_INK and self._current_stroke:
            page_num = self._page_index_at_pos(scene_pos)
            if page_num is not None:
                px, py = self._scene_to_page_coords(page_num, scene_pos)
                self._current_stroke.append([px, py])
                # Draw temporary ink preview
                self._render_temporary_ink()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        # ── Completion of text selection -> create highlight/underline/strikethrough ──
        if self._selection.is_selecting:
            self._selection.is_selecting = False
            if self._active_tool in (TOOL_HIGHLIGHT, TOOL_UNDERLINE, TOOL_STRIKETHROUGH):
                self._create_text_annotation()
            else:
                # Normal text selection (select/copy mode)
                text = self._extract_selected_text()
                if text:
                    self.text_selected.emit(text)
            return

        # ── Completion of ink stroke ──
        if self._active_tool == TOOL_INK and self._current_stroke:
            if len(self._current_stroke) > 2:
                points = self._current_stroke
                # Find which page the ink is on
                if self._page_items and self._annot_manager:
                    # Use the first point to determine page
                    scene_pos = self.mapToScene(event.pos())
                    page_num = self._page_index_at_pos(scene_pos)
                    if page_num is None:
                        # Fallback: use anchor page from first point
                        page_num = 0
                    annot = self._annot_manager.add_ink(
                        page_num, [points], color=self._editor_color,
                    )
                    self._render_annotation_overlays()
                    self.annotation_created.emit(annot)
            self._current_stroke = []
            self._ink_points = []
            return

        super().mouseReleaseEvent(event)

    def _render_temporary_ink(self) -> None:
        """Draw the current in-progress ink stroke as a preview."""
        # Remove any existing temp ink item
        if hasattr(self, '_temp_ink_item') and self._temp_ink_item:
            scene = self.scene()
            if scene:
                scene.removeItem(self._temp_ink_item)

        if not self._current_stroke or len(self._current_stroke) < 2:
            return

        # Find which page the stroke is on
        if not self._page_items:
            return
        page_num = 0
        # Use first point's approximate position
        first_pt = self._current_stroke[0]
        ratio = self._dpi * self._zoom / 72.0
        scene_x = self._page_items[page_num].pos().x() + first_pt[0] * ratio
        scene_y = self._page_items[page_num].pos().y() + first_pt[1] * ratio

        points = []
        for px, py in self._current_stroke:
            pts = []
            for item in self._page_items:
                r = QRectF(item.pos(), QSizeF(item.page_rect.width(), item.page_rect.height()))
                if r.contains(QPointF(
                    item.pos().x() + px * ratio,
                    item.pos().y() + py * ratio,
                )):
                    pts.append(QPointF(
                        item.pos().x() + px * ratio,
                        item.pos().y() + py * ratio,
                    ))
                    break
            else:
                pts.append(QPointF(
                    self._page_items[page_num].pos().x() + px * ratio,
                    self._page_items[page_num].pos().y() + py * ratio,
                ))
            points.extend(pts)

        if len(points) >= 2:
            color = QColor(
                int(self._editor_color[0] * 255),
                int(self._editor_color[1] * 255),
                int(self._editor_color[2] * 255),
                int(self._editor_opacity * 255),
            )
            pen = QPen(color, self._editor_width * ratio, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            path = QPolygonF(points)
            line_item = self._scene.addPolygon(path, pen)
            line_item.setZValue(200)
            self._temp_ink_item = line_item

    def _create_text_annotation(self) -> None:
        """Create an annotation from the current selection and the active tool."""
        if not self._annot_manager or self._selection.anchor_page < 0:
            self._selection.clear()
            return

        x0 = min(self._selection.anchor_pos.x(), self._selection.current_pos.x())
        y0 = min(self._selection.anchor_pos.y(), self._selection.current_pos.y())
        x1 = max(self._selection.anchor_pos.x(), self._selection.current_pos.x())
        y1 = max(self._selection.anchor_pos.y(), self._selection.current_pos.y())

        self._selection.clear()

        # Convert to page coordinates
        ratio = self._dpi * self._zoom / 72.0
        rect = (x0 / ratio, y0 / ratio, x1 / ratio, y1 / ratio)

        # Skip tiny selections
        if rect[2] - rect[0] < 2 or rect[3] - rect[1] < 2:
            return

        annot = None
        if self._active_tool == TOOL_HIGHLIGHT:
            annot = self._annot_manager.add_highlight(self._selection.anchor_page, rect)
        elif self._active_tool == TOOL_UNDERLINE:
            annot = self._annot_manager.add_underline(self._selection.anchor_page, rect)
        elif self._active_tool == TOOL_STRIKETHROUGH:
            annot = self._annot_manager.add_strikethrough(self._selection.anchor_page, rect)

        if annot:
            self._render_annotation_overlays()
            self.annotation_created.emit(annot)

    def _update_selection_overlay(self) -> None:
        """Draw the current selection rectangle on the page."""
        self._selection.clear()
        if self._selection.anchor_page < 0:
            return

        # Build a rect from anchor to current
        x0 = min(self._selection.anchor_pos.x(), self._selection.current_pos.x())
        y0 = min(self._selection.anchor_pos.y(), self._selection.current_pos.y())
        x1 = max(self._selection.anchor_pos.x(), self._selection.current_pos.x())
        y1 = max(self._selection.anchor_pos.y(), self._selection.current_pos.y())

        item = self._page_items[self._selection.anchor_page]
        color = QColor(0, 120, 215, 60)

        # For highlight/underline/strikethrough, use annotation color
        if self._active_tool in (TOOL_HIGHLIGHT, TOOL_UNDERLINE, TOOL_STRIKETHROUGH):
            r_, g_, b_ = self._editor_color
            color = QColor(int(r_ * 255), int(g_ * 255), int(b_ * 255), 80)

        rect_item = self._scene.addRect(
            item.pos().x() + x0,
            item.pos().y() + y0,
            x1 - x0,
            y1 - y0,
            QPen(QColor(0, 120, 215), 1),
            QBrush(color),
        )
        rect_item.setZValue(100)
        self._selection.selection_rects.append(rect_item)

    def _extract_selected_text(self) -> str:
        """Get the text under the current selection rectangle."""
        if not self._doc or self._selection.anchor_page < 0:
            return ""

        x0 = min(self._selection.anchor_pos.x(), self._selection.current_pos.x())
        y0 = min(self._selection.anchor_pos.y(), self._selection.current_pos.y())
        x1 = max(self._selection.anchor_pos.x(), self._selection.current_pos.x())
        y1 = max(self._selection.anchor_pos.y(), self._selection.current_pos.y())

        # Convert display coordinates back to page coordinates
        ratio = self._dpi * self._zoom / 72.0
        rect = fitz.Rect(x0 / ratio, y0 / ratio, x1 / ratio, y1 / ratio)

        text = self._doc.text_under_rect(self._selection.anchor_page, rect)
        return text.strip()

    def set_selection_mode(self, enabled: bool) -> None:
        """Enable/disable text selection mode."""
        self._selection_mode = enabled
        if enabled:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(QCursor(Qt.IBeamCursor))
        else:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.setCursor(QCursor(Qt.ArrowCursor))
            self._selection.clear()

    def copy_selected_text(self) -> None:
        """Emit the currently visible selection as text."""
        text = self._extract_selected_text()
        if text:
            QApplication.clipboard().setText(text)

    # ── editor tool management ──────────────────────────────────

    def set_editor_tool(self, tool_id: str) -> None:
        """Switch the active annotation tool."""
        self._active_tool = tool_id
        self._current_stroke = []
        self._ink_points = []

        if tool_id == TOOL_SELECT:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.setCursor(QCursor(Qt.ArrowCursor))
            self._selection_mode = False
        elif tool_id == TOOL_ERASER:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(QCursor(Qt.PointingHandCursor))
            self._selection_mode = False
        elif tool_id == TOOL_INK:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(QCursor(Qt.CrossCursor))
            self._selection_mode = False
        elif tool_id in (TOOL_HIGHLIGHT, TOOL_UNDERLINE, TOOL_STRIKETHROUGH):
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(QCursor(Qt.IBeamCursor))
            self._selection_mode = False
        elif tool_id in (TOOL_NOTE, TOOL_TEXTBOX):
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(QCursor(Qt.CrossCursor))
            self._selection_mode = False

    def set_editor_color(self, color: tuple) -> None:
        self._editor_color = color

    def set_editor_opacity(self, opacity: float) -> None:
        self._editor_opacity = opacity

    def set_editor_width(self, width: float) -> None:
        self._editor_width = width

    @property
    def annot_manager(self) -> AnnotationManager | None:
        return self._annot_manager

    # ── annotation overlay rendering ────────────────────────────

    def _render_annotation_overlays(self) -> None:
        """Render all annotations as overlay items on the scene."""
        self._clear_annotation_overlays()
        if not self._annot_manager or not self._page_items:
            return

        for page_num in range(len(self._page_items)):
            for annot in self._annot_manager.for_page(page_num):
                self._create_annot_overlay_item(annot)

    # ── form mode ────────────────────────────────────────────────

    def set_form_mode(self, enabled: bool) -> None:
        """Enable or disable interactive form fill mode."""
        self._form_mode = enabled
        if enabled:
            self._load_form_fields()
            self._render_form_overlays()
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(QCursor(Qt.IBeamCursor))
        else:
            self._clear_form_overlays()
            self._cancel_form_input()
            self._form_fields.clear()
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.setCursor(QCursor(Qt.ArrowCursor))

    def has_form_fields(self) -> bool:
        """Check if the loaded document has any interactive form fields."""
        return bool(self._doc and self._doc.has_forms())

    def _load_form_fields(self) -> None:
        """Load form field data for all pages from the document."""
        self._form_fields.clear()
        if not self._doc:
            return
        for i in range(self._doc.page_count):
            fields = self._doc.get_form_fields(i)
            if fields:
                self._form_fields[i] = fields

    def _render_form_overlays(self) -> None:
        """Render form field overlays on visible pages."""
        self._clear_form_overlays()
        if not self._doc or not self._form_mode:
            return

        for page_num, fields in self._form_fields.items():
            page_item = self._page_items[page_num] if page_num < len(self._page_items) else None
            if not page_item:
                continue

            for field in fields:
                key = f"{page_num}:{field['name']}"
                scene_rect = self._page_rect_to_scene(page_num, field["rect"])

                if field["is_readonly"]:
                    continue

                ftype = field["type"]
                color = QColor(0, 120, 215, 60)  # light blue fill
                border = QPen(QColor(0, 100, 200), 1.5)

                if ftype in ("text", "textarea"):
                    item = self._scene.addRect(scene_rect, border, QBrush(color))
                    item.setZValue(50)
                    item.setData(0, key)

                    # Show current value if any
                    if field["value"]:
                        txt = self._scene.addSimpleText(str(field["value"]))
                        txt.setPos(scene_rect.x() + 2, scene_rect.y() + 1)
                        txt.setZValue(51)
                        font = txt.font()
                        font.setPointSize(9)
                        txt.setFont(font)
                        self._form_items[key + "_val"] = txt

                elif ftype == "checkbox":
                    # Draw a clickable square
                    size = min(scene_rect.width(), scene_rect.height())
                    item = self._scene.addRect(
                        scene_rect.x(), scene_rect.y(), size, size,
                        border, QBrush(color)
                    )
                    item.setZValue(50)
                    item.setData(0, key)

                    # Check mark if checked
                    if field["value"] and field["value"] not in ("Off", "No", ""):
                        check = self._scene.addSimpleText("✓")
                        check.setPos(scene_rect.x() + 1, scene_rect.y() - 2)
                        check.setZValue(51)
                        check.setBrush(QColor(0, 120, 215))
                        font = check.font()
                        font.setPointSize(11)
                        font.setBold(True)
                        check.setFont(font)
                        self._form_items[key + "_val"] = check

                elif ftype == "radio_button":
                    size = min(scene_rect.width(), scene_rect.height())
                    # Circle
                    item = self._scene.addEllipse(
                        scene_rect.x(), scene_rect.y(), size, size,
                        border, QBrush(color)
                    )
                    item.setZValue(50)
                    item.setData(0, key)

                    # Dot if selected
                    if field["value"] and field["value"] not in ("Off", ""):
                        dot = self._scene.addEllipse(
                            scene_rect.x() + size * 0.25,
                            scene_rect.y() + size * 0.25,
                            size * 0.5, size * 0.5,
                            QPen(Qt.NoPen), QBrush(QColor(0, 120, 215))
                        )
                        dot.setZValue(51)
                        self._form_items[key + "_val"] = dot

                elif ftype in ("combo_box", "list_box"):
                    item = self._scene.addRect(scene_rect, border, QBrush(color))
                    item.setZValue(50)
                    item.setData(0, key)
                    # Dropdown arrow indicator
                    arrow = self._scene.addSimpleText("▼")
                    arrow.setPos(
                        scene_rect.right() - 14,
                        scene_rect.top() + 1
                    )
                    arrow.setZValue(51)
                    arrow.setBrush(QColor(100, 100, 100))
                    self._form_items[key + "_arr"] = arrow

                    # Show current value
                    if field["value"]:
                        txt = self._scene.addSimpleText(str(field["value"]))
                        txt.setPos(scene_rect.x() + 2, scene_rect.y() + 1)
                        txt.setZValue(51)
                        font = txt.font()
                        font.setPointSize(9)
                        txt.setFont(font)
                        self._form_items[key + "_val"] = txt

                self._form_items[key] = item

    def _clear_form_overlays(self) -> None:
        """Remove all form field overlay items from the scene."""
        for item in self._form_items.values():
            scene = item.scene()
            if scene:
                scene.removeItem(item)
        self._form_items.clear()

    def _cancel_form_input(self) -> None:
        """Remove any active text input widget."""
        if self._form_text_input:
            self._form_text_input.deleteLater()
            self._form_text_input = None
        self._form_active_field = None

    def _on_form_field_click(self, page_num: int, field: dict, scene_pos: QPointF) -> None:
        """Handle clicking on a form field in form fill mode."""
        ftype = field["type"]
        key = f"{page_num}:{field['name']}"

        if ftype in ("text", "textarea"):
            scene_rect = self._page_rect_to_scene(page_num, field["rect"])
            self._form_active_field = key
            # Create an overlay QLineEdit for text input
            self._form_text_input = QLineEdit(self)
            self._form_text_input.setGeometry(
                int(scene_rect.x()), int(scene_rect.y()),
                int(scene_rect.width()),
                max(20, int(scene_rect.height()))
            )
            self._form_text_input.setText(str(field["value"]))
            self._form_text_input.selectAll()
            self._form_text_input.setStyleSheet(
                "QLineEdit { background-color: rgba(255, 255, 255, 220); "
                "border: 2px solid #0078d7; padding: 2px; font-size: 11pt; }"
            )
            self._form_text_input.returnPressed.connect(
                lambda k=key: self._commit_form_text(k)
            )
            self._form_text_input.setFocus()
            self._form_text_input.show()

        elif ftype == "checkbox":
            new_val = "Yes" if field["value"] in ("Off", "No", "") else "Off"
            self._doc.set_form_field(page_num, field["name"], new_val)
            self._render_form_overlays()

        elif ftype == "radio_button":
            self._doc.set_form_field(page_num, field["name"], "Yes")
            self._render_form_overlays()

        elif ftype in ("combo_box", "list_box"):
            choices = field["choices"]
            if choices:
                dialog = QDialog(self)
                dialog.setWindowTitle(f"Select: {field['label'] or field['name']}")
                layout = QVBoxLayout(dialog)
                combo = QComboBox()
                combo.addItems(choices)
                current = str(field["value"])
                if current in choices:
                    combo.setCurrentText(current)
                layout.addWidget(combo)
                buttons = QHBoxLayout()
                ok_btn = QPushButton("OK")
                cancel_btn = QPushButton("Cancel")
                buttons.addWidget(ok_btn)
                buttons.addWidget(cancel_btn)
                layout.addLayout(buttons)
                ok_btn.clicked.connect(dialog.accept)
                cancel_btn.clicked.connect(dialog.reject)
                dialog.setResult(QDialog.Rejected)
                if dialog.exec() == QDialog.Accepted:
                    self._doc.set_form_field(page_num, field["name"], combo.currentText())
                    self._render_form_overlays()

    def _commit_form_text(self, key: str) -> None:
        """Save text from the active QLineEdit to the form field."""
        if not self._form_text_input or not self._form_active_field:
            return
        text = self._form_text_input.text()
        parts = self._form_active_field.split(":", 1)
        if len(parts) == 2:
            page_num = int(parts[0])
            field_name = parts[1]
            self._doc.set_form_field(page_num, field_name, text)
        self._cancel_form_input()
        self._render_form_overlays()

    def _create_annot_overlay_item(self, annot: Annotation) -> None:
        """Create a scene item for a single annotation."""
        if annot.page >= len(self._page_items):
            return

        scene_rect = self._page_rect_to_scene(annot.page, annot.rect)
        r, g, b = annot.color
        alpha = int(annot.opacity * 255)

        item = None

        if annot.type == "highlight":
            color = QColor(int(r * 255), int(g * 255), int(b * 255), alpha)
            item = self._scene.addRect(
                scene_rect, QPen(Qt.NoPen), QBrush(color)
            )
            item.setZValue(40)

        elif annot.type == "underline":
            color = QColor(int(r * 255), int(g * 255), int(b * 255))
            pen = QPen(color, max(1.0, annot.border_width))
            y = scene_rect.y() + scene_rect.height()
            item = self._scene.addLine(
                scene_rect.x(), y, scene_rect.x() + scene_rect.width(), y, pen
            )
            item.setZValue(40)

        elif annot.type == "strikethrough":
            color = QColor(int(r * 255), int(g * 255), int(b * 255))
            pen = QPen(color, max(1.0, annot.border_width))
            y = scene_rect.center().y()
            item = self._scene.addLine(
                scene_rect.x(), y, scene_rect.x() + scene_rect.width(), y, pen
            )
            item.setZValue(40)

        elif annot.type == "note":
            color = QColor(int(r * 255), int(g * 255), int(b * 255))
            size = 16 * (self._dpi * self._zoom / 72.0)
            item = self._scene.addRect(
                scene_rect.x(), scene_rect.y(),
                size, size,
                QPen(QColor(80, 80, 80), 1),
                QBrush(color),
            )
            item.setZValue(40)
            # Add "note" label
            note_label = self._scene.addSimpleText("📌")
            note_label.setPos(scene_rect.x(), scene_rect.y())
            note_label.setZValue(41)
            self._annot_items[annot.id + "_label"] = note_label

        elif annot.type == "ink":
            if annot.paths:
                color = QColor(int(r * 255), int(g * 255), int(b * 255), alpha)
                ratio = self._dpi * self._zoom / 72.0
                pen = QPen(color, max(1.0, annot.border_width * ratio),
                           Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                for stroke in annot.paths:
                    if len(stroke) < 2:
                        continue
                    pts = []
                    for px, py in stroke:
                        scene_pt = self._page_to_scene_coords(annot.page, px, py)
                        pts.append(scene_pt)
                    if len(pts) >= 2:
                        path = QPolygonF(pts)
                        line_item = self._scene.addPolygon(path, pen)
                        line_item.setZValue(40)
                        key = f"{annot.id}_ink"
                        self._annot_items[key] = line_item

        elif annot.type == "textbox":
            color = QColor(int(r * 255), int(g * 255), int(b * 255))
            bg = QColor(255, 255, 255, 200)
            item = self._scene.addRect(
                scene_rect,
                QPen(color, 1),
                QBrush(bg),
            )
            item.setZValue(40)
            # Add text content
            if annot.content:
                text_item = self._scene.addSimpleText(annot.content)
                text_item.setPos(scene_rect.x() + 3, scene_rect.y() + 2)
                text_item.setZValue(41)
                text_item.setScale(0.8)
                self._annot_items[annot.id + "_text"] = text_item

        if item:
            self._annot_items[annot.id] = item

    def _clear_annotation_overlays(self) -> None:
        """Remove all annotation overlay items from the scene."""
        for item in self._annot_items.values():
            scene = self.scene()
            if scene:
                scene.removeItem(item)
        self._annot_items.clear()

        # Clean up temp ink preview
        if hasattr(self, '_temp_ink_item') and self._temp_ink_item:
            scene = self.scene()
            if scene:
                scene.removeItem(self._temp_ink_item)
            self._temp_ink_item = None

    # ── search ──────────────────────────────────────────────────

    def search(self, query: str, *, case_sensitive: bool = False) -> list[SearchResult]:
        """Search the document and highlight results."""
        self._clear_search_results()
        if not self._doc or not query:
            return []

        raw = self._doc.search_all_pages(query, case_sensitive=case_sensitive)
        self._search_results = [
            SearchResult(r["page"], r["text"], r["rect"]) for r in raw
        ]

        self._show_search_results()
        return self._search_results

    def _show_search_results(self) -> None:
        """Highlight search results on pages."""
        self._clear_search_items()
        if not self._doc or not self._search_results:
            return

        for result in self._search_results:
            if result.page >= len(self._page_items):
                continue

            item = self._page_items[result.page]
            ratio = self._dpi * self._zoom / 72.0

            r = result.rect
            x = item.pos().x() + r.x0 * ratio
            y = item.pos().y() + r.y0 * ratio
            w = (r.x1 - r.x0) * ratio
            h = (r.y1 - r.y0) * ratio

            highlight = self._scene.addRect(
                x, y, w, h,
                QPen(QColor(255, 200, 0, 180), 1),
                QBrush(QColor(255, 255, 0, 80)),
            )
            highlight.setZValue(50)
            self._search_items.append(highlight)

    def _clear_search_results(self) -> None:
        self._clear_search_items()
        self._search_results.clear()
        self._search_index = -1

    def _clear_search_items(self) -> None:
        for item in self._search_items:
            scene = self.scene()
            if scene:
                scene.removeItem(item)
        self._search_items.clear()
        # Also clear per-page search highlights
        for pg in self._page_items:
            pg.clear_search_highlights()

    def go_to_next_search_result(self) -> None:
        """Jump to the next search result."""
        if not self._search_results:
            return
        self._search_index = (self._search_index + 1) % len(self._search_results)
        result = self._search_results[self._search_index]
        self.go_to_page(result.page)
        self.search_result_clicked.emit(result.page)

    def go_to_prev_search_result(self) -> None:
        """Jump to the previous search result."""
        if not self._search_results:
            return
        self._search_index = (self._search_index - 1) % len(self._search_results)
        result = self._search_results[self._search_index]
        self.go_to_page(result.page)
        self.search_result_clicked.emit(result.page)

    # ── fullscreen ──────────────────────────────────────────────

    def toggle_fullscreen(self) -> None:
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()

    # ── drag & drop ─────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(".pdf"):
                    self.parent().open_file(path) if hasattr(self.parent(), "open_file") else None
                    break

    # ── keyboard shortcuts (handled here for viewport focus) ────

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mod = event.modifiers()

        if key == Qt.Key_Home:
            self.go_to_first_page()
        elif key == Qt.Key_End:
            self.go_to_last_page()
        elif key == Qt.Key_PageUp:
            self.scroll_by(-self.viewport().height())
        elif key == Qt.Key_PageDown:
            self.scroll_by(self.viewport().height())
        elif key == Qt.Key_Up:
            self.scroll_by(-self._key_scroll_amount)
        elif key == Qt.Key_Down:
            self.scroll_by(self._key_scroll_amount)
        elif key == Qt.Key_Left:
            self.scroll_by(-self._key_scroll_amount)
        elif key == Qt.Key_Right:
            self.scroll_by(self._key_scroll_amount)
        elif key == Qt.Key_Space:
            self.scroll_by(self.viewport().height() * 0.8)
        else:
            super().keyPressEvent(event)

    def _finish_scroll_animation(self) -> None:
        """Called after smooth scroll settles — re-evaluate current page."""
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        self._update_current_page(visible)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        # Render newly visible pages
        self._render_timer.start()
        # Schedule page detection after scrolling settles
        self._scroll_animation_timer.start(150)
