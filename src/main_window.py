"""
Fenrir Main Window — the full PDF reader application window.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QSize, QTimer, Slot
from PySide6.QtGui import (
    QAction, QKeySequence, QIcon, QColor, QPalette, QFont,
    QCloseEvent, QTextDocument, QPainter, QBrush,
)
from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QStatusBar, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QPushButton, QComboBox, QStyle, QStyleFactory,
    QMessageBox, QFileDialog, QApplication, QMenu, QMenuBar,
    QCheckBox, QScrollArea,
)

from src.engine.document import FenrirDocument
from src.viewer.canvas import PdfCanvas
from src.sidebar.panels import SidebarWidget
from src.dialogs.search_dialog import SearchDialog
from src.dialogs.goto_dialog import GotoPageDialog
from src.editor.annotations import Annotation, AnnotationManager
from src.editor.widgets import EditorToolbar, TOOL_SELECT
from src.utils.settings import AppSettings


class MainWindow(QMainWindow):
    """Fenrir PDF Reader main application window."""

    def __init__(self):
        super().__init__()
        self._doc: FenrirDocument | None = None
        self._search_dialog: SearchDialog | None = None
        self._search_results: list = []

        self._setup_ui()
        self._setup_actions()
        self._setup_shortcuts()
        self._setup_connections()
        self._restore_state()

        self.setWindowTitle("Fenrir PDF Reader")
        self.setMinimumSize(800, 600)
        self.resize(1200, 800)

    # ── UI Setup ────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the main window layout."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar
        self._toolbar = QToolBar("Main Toolbar")
        self._toolbar.setIconSize(QSize(20, 20))
        self._toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(self._toolbar)

        # Editor toolbar (annotation tools)
        self._editor_toolbar = EditorToolbar(self)
        self.addToolBar(self._editor_toolbar)
        self._editor_toolbar.hide()  # Hidden until a document is loaded

        # Splitter: sidebar | canvas
        self._splitter = QSplitter(Qt.Horizontal)

        # Sidebar
        self._sidebar = SidebarWidget()
        self._splitter.addWidget(self._sidebar)

        # Canvas
        self._canvas = PdfCanvas()
        self._splitter.addWidget(self._canvas)

        # Set proportions
        self._splitter.setSizes([220, 980])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)

        main_layout.addWidget(self._splitter)

        # Status bar
        self._status = QStatusBar()
        self._page_label = QLabel("Page: - / -")
        self._zoom_label = QLabel("Zoom: 100%")
        self._file_label = QLabel("")
        self._file_label.setStyleSheet("padding-left: 12px;")
        self._status.addWidget(self._file_label, 1)
        self._status.addPermanentWidget(self._page_label)
        self._status.addPermanentWidget(self._zoom_label)
        self.setStatusBar(self._status)

    def _setup_actions(self) -> None:
        """Create all toolbar/menu actions with icons and shortcuts."""

        # ── File Actions ──
        self._act_open = QAction("📂 Open", self)
        self._act_open.setShortcut(QKeySequence.Open)
        self._act_open.setStatusTip("Open a PDF file")
        self._act_open.triggered.connect(self._on_open)

        self._act_close = QAction("Close", self)
        self._act_close.setShortcut(QKeySequence("Ctrl+W"))
        self._act_close.setStatusTip("Close current document")
        self._act_close.triggered.connect(self._on_close)

        self._act_print = QAction("🖨 Print", self)
        self._act_print.setShortcut(QKeySequence.Print)
        self._act_print.setStatusTip("Print current document")
        self._act_print.triggered.connect(self._on_print)

        self._act_quit = QAction("Quit", self)
        self._act_quit.setShortcut(QKeySequence.Quit)
        self._act_quit.triggered.connect(self.close)

        # ── Navigation Actions ──
        self._act_first = QAction("⏮ First", self)
        self._act_first.setShortcut(QKeySequence.MoveToStartOfDocument)
        self._act_first.triggered.connect(self._canvas.go_to_first_page)

        self._act_prev = QAction("◀ Prev", self)
        self._act_prev.setShortcut(QKeySequence.MoveToPreviousPage)
        self._act_prev.triggered.connect(self._canvas.go_to_prev_page)

        self._act_next = QAction("Next ▶", self)
        self._act_next.setShortcut(QKeySequence.MoveToNextPage)
        self._act_next.triggered.connect(self._canvas.go_to_next_page)

        self._act_last = QAction("⏭ Last", self)
        self._act_last.setShortcut(QKeySequence.MoveToEndOfDocument)
        self._act_last.triggered.connect(self._canvas.go_to_last_page)

        self._act_goto = QAction("🔢 Go to Page...", self)
        self._act_goto.setShortcut(QKeySequence("Ctrl+G"))
        self._act_goto.triggered.connect(self._on_goto)

        # ── Zoom Actions ──
        self._act_zoom_in = QAction("🔍+ Zoom In", self)
        self._act_zoom_in.setShortcut(QKeySequence.ZoomIn)
        self._act_zoom_in.triggered.connect(self._canvas.zoom_in)

        self._act_zoom_out = QAction("🔍- Zoom Out", self)
        self._act_zoom_out.setShortcut(QKeySequence.ZoomOut)
        self._act_zoom_out.triggered.connect(self._canvas.zoom_out)

        self._act_zoom_fit_width = QAction("📐 Fit Width", self)
        self._act_zoom_fit_width.setShortcut(QKeySequence("Ctrl+0"))
        self._act_zoom_fit_width.triggered.connect(self._canvas.zoom_fit_width)

        self._act_zoom_fit_page = QAction("📄 Fit Page", self)
        self._act_zoom_fit_page.setShortcut(QKeySequence("Ctrl+9"))
        self._act_zoom_fit_page.triggered.connect(self._canvas.zoom_fit_page)

        self._act_zoom_actual = QAction("🔲 Actual Size", self)
        self._act_zoom_actual.setShortcut(QKeySequence("Ctrl+1"))
        self._act_zoom_actual.triggered.connect(self._canvas.zoom_actual_size)

        # ── View Actions ──
        self._act_fullscreen = QAction("⛶ Fullscreen", self)
        self._act_fullscreen.setShortcut(QKeySequence("F11"))
        self._act_fullscreen.setCheckable(True)
        self._act_fullscreen.triggered.connect(self._on_toggle_fullscreen)

        self._act_sidebar = QAction("📑 Sidebar", self)
        self._act_sidebar.setShortcut(QKeySequence("F9"))
        self._act_sidebar.setCheckable(True)
        self._act_sidebar.setChecked(AppSettings.sidebar_visible())
        self._act_sidebar.triggered.connect(self._on_toggle_sidebar)

        self._act_dark_mode = QAction("🌙 Dark Mode", self)
        self._act_dark_mode.setCheckable(True)
        self._act_dark_mode.setChecked(AppSettings.dark_mode())
        self._act_dark_mode.triggered.connect(self._on_toggle_dark_mode)

        # ── Edit Actions ──
        self._act_search = QAction("🔎 Find", self)
        self._act_search.setShortcut(QKeySequence.Find)
        self._act_search.triggered.connect(self._on_search)

        self._act_select_text = QAction("✎ Select Text", self)
        self._act_select_text.setShortcut(QKeySequence("Ctrl+T"))
        self._act_select_text.setCheckable(True)
        self._act_select_text.triggered.connect(self._on_select_text)

        self._act_copy = QAction("📋 Copy", self)
        self._act_copy.setShortcut(QKeySequence.Copy)
        self._act_copy.triggered.connect(self._canvas.copy_selected_text)

        # ── Rotate Actions ──
        self._act_rotate_cw = QAction("↻ Rotate CW", self)
        self._act_rotate_cw.setShortcut(QKeySequence("Ctrl+R"))
        self._act_rotate_cw.triggered.connect(self._canvas.rotate_clockwise)

        self._act_rotate_ccw = QAction("↺ Rotate CCW", self)
        self._act_rotate_ccw.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self._act_rotate_ccw.triggered.connect(self._canvas.rotate_counterclockwise)

        # ── Editor Actions ──
        self._act_toggle_editor = QAction("✎ Annotate", self)
        self._act_toggle_editor.setShortcut(QKeySequence("Ctrl+E"))
        self._act_toggle_editor.setCheckable(True)
        self._act_toggle_editor.setEnabled(False)
        self._act_toggle_editor.triggered.connect(self._on_toggle_editor)

        # ── Form Fill Actions ──
        self._act_toggle_form = QAction("📝 Forms", self)
        self._act_toggle_form.setCheckable(True)
        self._act_toggle_form.setEnabled(False)
        self._act_toggle_form.triggered.connect(self._on_toggle_form)

        self._act_save_form = QAction("💾 Save Form", self)
        self._act_save_form.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._act_save_form.setEnabled(False)
        self._act_save_form.triggered.connect(self._on_save_form)

        # ── Build Toolbar ──
        self._toolbar.addAction(self._act_open)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self._act_first)
        self._toolbar.addAction(self._act_prev)

        # Page spinner in toolbar
        self._page_spinner = QSpinBox()
        self._page_spinner.setRange(1, 1)
        self._page_spinner.setSuffix(f" / {1}")
        self._page_spinner.setFixedWidth(120)
        self._page_spinner.setAlignment(Qt.AlignCenter)
        self._page_spinner.valueChanged.connect(self._on_page_spinner_changed)
        self._toolbar.addWidget(self._page_spinner)

        self._toolbar.addAction(self._act_next)
        self._toolbar.addAction(self._act_last)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self._act_zoom_out)
        self._toolbar.addAction(self._act_zoom_in)
        self._toolbar.addAction(self._act_zoom_fit_width)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self._act_search)
        self._toolbar.addAction(self._act_fullscreen)
        self._toolbar.addAction(self._act_sidebar)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self._act_toggle_editor)
        self._toolbar.addAction(self._act_toggle_form)
        self._toolbar.addAction(self._act_save_form)

        # ── Build Menu Bar ──
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self._act_open)
        file_menu.addAction(self._act_close)
        file_menu.addSeparator()
        file_menu.addAction(self._act_print)
        file_menu.addSeparator()
        file_menu.addAction(self._act_quit)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self._act_search)
        edit_menu.addAction(self._act_select_text)
        edit_menu.addAction(self._act_copy)
        edit_menu.addSeparator()
        edit_menu.addAction(self._act_rotate_cw)
        edit_menu.addAction(self._act_rotate_ccw)

        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self._act_fullscreen)
        view_menu.addAction(self._act_sidebar)
        view_menu.addAction(self._act_dark_mode)
        view_menu.addSeparator()
        view_menu.addAction(self._act_zoom_in)
        view_menu.addAction(self._act_zoom_out)
        view_menu.addAction(self._act_zoom_fit_width)
        view_menu.addAction(self._act_zoom_fit_page)
        view_menu.addAction(self._act_zoom_actual)
        view_menu.addSeparator()
        view_menu.addAction(self._act_goto)

        # Navigation menu
        nav_menu = menubar.addMenu("&Navigation")
        nav_menu.addAction(self._act_first)
        nav_menu.addAction(self._act_prev)
        nav_menu.addAction(self._act_next)
        nav_menu.addAction(self._act_last)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("About Fenrir", self._on_about)
        help_menu.addAction("About Qt", QApplication.instance().aboutQt)

    def _setup_shortcuts(self) -> None:
        """Additional keyboard shortcuts not covered by actions."""
        pass  # All shortcuts are on actions above

    def _setup_connections(self) -> None:
        """Connect signals between components."""
        self._canvas.page_changed.connect(self._on_page_changed)
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._canvas.document_loaded.connect(self._on_document_loaded)

        self._sidebar.page_navigated.connect(self._canvas.go_to_page)
        self._canvas.search_result_clicked.connect(self._sidebar.highlight_page)

        # Editor toolbar connections
        self._editor_toolbar.tool_changed.connect(self._canvas.set_editor_tool)
        self._editor_toolbar.color_changed.connect(self._canvas.set_editor_color)
        self._editor_toolbar.opacity_changed.connect(self._canvas.set_editor_opacity)
        self._editor_toolbar.pen_width_changed.connect(self._canvas.set_editor_width)
        self._editor_toolbar.save_requested.connect(self._on_save_annotations)
        self._canvas.annotation_created.connect(self._on_annotation_created)
        self._canvas.annotation_deleted.connect(self._on_annotation_deleted)

    # ── State Persistence ───────────────────────────────────────

    def _restore_state(self) -> None:
        """Restore window geometry and settings from last session."""
        geo = AppSettings.window_geometry()
        state = AppSettings.window_state()
        if geo:
            self.restoreGeometry(geo)
        if state:
            self.restoreState(state)

        # Dark mode
        if AppSettings.dark_mode():
            self._apply_dark_mode()

        # Sidebar visibility
        self._sidebar.setVisible(AppSettings.sidebar_visible())
        sidebar_w = AppSettings.sidebar_width()
        self._sidebar.setMaximumWidth(sidebar_w + 20)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Save window state on close."""
        AppSettings.set_window_geometry(self.saveGeometry())
        AppSettings.set_window_state(self.saveState())
        AppSettings.set_sidebar_visible(self._sidebar.isVisible())
        AppSettings.set_sidebar_width(self._sidebar.width())
        AppSettings.set_zoom(self._canvas.zoom)

        if self._doc:
            self._doc.close()
        if self._search_dialog:
            self._search_dialog.close()

        super().closeEvent(event)

    # ── File Operations ─────────────────────────────────────────

    def open_file(self, filepath: str) -> None:
        """Open a PDF file."""
        if not os.path.isfile(filepath):
            self._status.showMessage(f"File not found: {filepath}", 5000)
            return

        # Check if it's a PDF
        if not filepath.lower().endswith(".pdf"):
            QMessageBox.warning(self, "Invalid File", "Please select a PDF file.")
            return

        try:
            if self._doc:
                self._doc.close()

            self._doc = FenrirDocument(filepath)

            # Check encryption
            if self._doc.is_encrypted:
                # Try empty password first
                if not self._doc.authenticate(""):
                    # Ask for password
                    from PySide6.QtWidgets import QInputDialog
                    pwd, ok = QInputDialog.getText(
                        self, "Password Required",
                        "This PDF is password-protected:",
                        echoMode=QInputDialog.PasswordEchoOnEdit,
                    )
                    if ok and pwd:
                        if not self._doc.authenticate(pwd):
                            QMessageBox.critical(self, "Error", "Incorrect password.")
                            self._doc = None
                            return
                    else:
                        self._doc = None
                        return

            self._canvas.load_document(self._doc)
            AppSettings.add_recent_file(filepath)
            self._update_title()

        except Exception as e:
            QMessageBox.critical(self, "Error Opening File", str(e))
            self._doc = None

    def _on_open(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf);;All Files (*)"
        )
        if filepath:
            self.open_file(filepath)

    def _on_close(self) -> None:
        if self._doc:
            self._canvas.close_document()
            self._doc = None
            self._update_title()
            self._update_page_spinner(0, 0)
            self._editor_toolbar.hide()
            self._act_toggle_editor.setChecked(False)
            self._act_toggle_editor.setEnabled(False)

    def _on_print(self) -> None:
        if not self._doc:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter()
        dialog = QPrintDialog(printer, self)
        if dialog.exec():
            # Simple print: render each page and draw it
            painter = QPainter(printer)
            for i in range(self._doc.page_count):
                if i > 0:
                    printer.newPage()
                img = self._doc.render_page(i, dpi=300)
                rect = painter.viewport()
                scaled = img.scaled(
                    rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                x = (rect.width() - scaled.width()) // 2
                y = (rect.height() - scaled.height()) // 2
                painter.drawImage(x, y, scaled)
            painter.end()

    # ── Navigation ──────────────────────────────────────────────

    def _on_goto(self) -> None:
        if not self._doc:
            return
        dialog = GotoPageDialog(
            self._canvas.current_page, self._doc.page_count, self
        )
        if dialog.exec():
            self._canvas.go_to_page(dialog.page)

    def _on_page_spinner_changed(self, value: int) -> None:
        """Handle page number change from the toolbar spinner."""
        if self._doc:
            self._canvas.go_to_page(value - 1)

    # ── View / Display ──────────────────────────────────────────

    def _on_toggle_fullscreen(self, checked: bool) -> None:
        self._canvas.toggle_fullscreen()
        self._act_fullscreen.setChecked(self.isFullScreen())

    def _on_toggle_sidebar(self, checked: bool) -> None:
        self._sidebar.setVisible(checked)

    def _on_toggle_dark_mode(self, checked: bool) -> None:
        if checked:
            self._apply_dark_mode()
        else:
            self._apply_light_mode()
        AppSettings.set_dark_mode(checked)

    def _apply_dark_mode(self) -> None:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(35, 35, 35))
        palette.setColor(QPalette.ToolTipBase, QColor(45, 45, 45))
        palette.setColor(QPalette.ToolTipText, QColor(220, 220, 220))
        palette.setColor(QPalette.Text, QColor(220, 220, 220))
        palette.setColor(QPalette.Button, QColor(45, 45, 45))
        palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
        palette.setColor(QPalette.BrightText, QColor(255, 100, 100))
        palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor(100, 100, 100))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(100, 100, 100))
        self.setPalette(palette)
        self._canvas.setBackgroundBrush(QBrush(QColor(45, 45, 45)))

    def _apply_light_mode(self) -> None:
        self.setPalette(self.style().standardPalette())
        self._canvas.setBackgroundBrush(QBrush(QColor(60, 60, 60)))

    # ── Text Selection ─────────────────────────────────────────

    def _on_select_text(self, checked: bool) -> None:
        self._canvas.set_selection_mode(checked)

    # ── Search ──────────────────────────────────────────────────

    def _on_search(self) -> None:
        if not self._doc:
            return
        if not self._search_dialog:
            self._search_dialog = SearchDialog(self)
            self._search_dialog.search_requested.connect(self._on_search_execute)
            self._search_dialog.next_requested.connect(self._canvas.go_to_next_search_result)
            self._search_dialog.prev_requested.connect(self._canvas.go_to_prev_search_result)
            self._search_dialog.result_selected.connect(self._on_search_result_selected)

        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.focus_input()

    def _on_search_execute(self, query: str, case_sensitive: bool) -> None:
        if not self._doc:
            return
        self._search_dialog.show_searching()

        # Run search (could be heavy on large docs - in a real app this would be threaded)
        results = self._canvas.search(query, case_sensitive=case_sensitive)
        self._search_results = [
            {"page": r.page, "text": r.text} for r in self._canvas._search_results
        ]

        self._search_dialog.hide_searching()
        self._search_dialog.show_results(self._search_results)

    def _on_search_result_selected(self, result_index: int, _) -> None:
        if result_index < len(self._search_results):
            result = self._search_results[result_index]
            self._canvas.go_to_page(result["page"])

    # ── Document Callbacks ──────────────────────────────────────

    def _on_document_loaded(self) -> None:
        """Called after a document finishes loading in the canvas."""
        if self._doc:
            self._update_page_spinner(
                self._canvas.current_page, self._doc.page_count
            )
            # Enable editor toolbar
            self._act_toggle_editor.setEnabled(True)

            # Enable form fill if the document has AcroForms
            self._act_toggle_form.setEnabled(self._canvas.has_form_fields())

    def _on_page_changed(self, page_num: int) -> None:
        """Update UI when the visible page changes."""
        self._update_page_spinner(page_num, self._doc.page_count if self._doc else 0)
        self._sidebar.highlight_page(page_num)
        self._page_label.setText(f"Page: {page_num + 1} / {self._doc.page_count if self._doc else '-'}")

    def _on_zoom_changed(self, zoom: float) -> None:
        """Update zoom display."""
        self._zoom_label.setText(f"Zoom: {int(zoom * 100)}%")

    def _update_page_spinner(self, current: int, total: int) -> None:
        """Update the page spinner in the toolbar."""
        self._page_spinner.blockSignals(True)
        if total > 0:
            self._page_spinner.setRange(1, total)
            self._page_spinner.setSuffix(f" / {total}")
            self._page_spinner.setValue(current + 1)
        else:
            self._page_spinner.setRange(0, 0)
            self._page_spinner.setValue(0)
            self._page_spinner.setSuffix(" / -")
        self._page_spinner.blockSignals(False)

    def _update_title(self) -> None:
        """Update window title with current filename."""
        if self._doc:
            name = os.path.basename(self._doc.filepath)
            self.setWindowTitle(f"{name} — Fenrir PDF Reader")
            self._file_label.setText(f"  📄 {name}")
        else:
            self.setWindowTitle("Fenrir PDF Reader")
            self._file_label.setText("")

    # ── Editor Callbacks ────────────────────────────────────────

    def _on_toggle_editor(self, checked: bool) -> None:
        """Toggle the editor toolbar on/off."""
        self._editor_toolbar.setVisible(checked)
        if not checked:
            # Return to select mode when hiding editor
            self._canvas.set_editor_tool(TOOL_SELECT)
            self._editor_toolbar.set_active_tool(TOOL_SELECT)

    # ── Form Fill Callbacks ─────────────────────────────────────

    def _on_toggle_form(self, checked: bool) -> None:
        """Toggle form fill mode on/off."""
        self._canvas.set_form_mode(checked)
        if checked:
            # Disable editor mode if form mode is on
            if self._act_toggle_editor.isChecked():
                self._act_toggle_editor.setChecked(False)
                self._on_toggle_editor(False)
            self._act_save_form.setEnabled(True)
        else:
            self._act_save_form.setEnabled(False)

    def _on_save_form(self) -> None:
        """Save filled form data back to the PDF."""
        if not self._canvas._doc:
            self._status.showMessage("No document open.", 3000)
            return
        # Save to same file (incremental save preserves everything)
        try:
            filepath = self._canvas._doc.filepath
            self._canvas._doc.save_form(filepath)
            self._status.showMessage("Form data saved to PDF ✓", 5000)
        except Exception as e:
            self._status.showMessage(f"Save error: {e}", 5000)


    def _on_save_annotations(self) -> None:
        """Save all annotations back to the PDF."""
        if not self._canvas.annot_manager:
            self._status.showMessage("No annotations to save.", 3000)
            return

        try:
            success = self._canvas.annot_manager.save()
            if success:
                self._status.showMessage("Annotations saved to PDF ✓", 5000)
            else:
                self._status.showMessage("Failed to save annotations.", 5000)
        except Exception as e:
            self._status.showMessage(f"Save error: {e}", 5000)

    def _on_annotation_created(self, annot) -> None:
        """Handle new annotation created."""
        count = self._canvas.annot_manager.count() if self._canvas.annot_manager else 0
        self._status.showMessage(
            f"Added {annot.type} annotation (total: {count})", 3000
        )

    def _on_annotation_deleted(self, annot_id: str) -> None:
        """Handle annotation deletion."""
        count = self._canvas.annot_manager.count() if self._canvas.annot_manager else 0
        self._status.showMessage(
            f"Deleted annotation (remaining: {count})", 3000
        )

    # ── About ───────────────────────────────────────────────────

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "About Fenrir",
            "<h2>Fenrir PDF Reader</h2>"
            "<p>Version 1.0</p>"
            "<p>A fast, native PDF reader built with PySide6 and PyMuPDF.</p>"
            "<p>Cross-platform: Linux & Windows.</p>"
            "<hr>"
            "<p style='font-size: 10px;'>Built by Aether for FlowRidge Solutions</p>"
        )
