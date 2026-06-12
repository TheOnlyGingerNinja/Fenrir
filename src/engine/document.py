"""
Fenrir PDF Engine — document loading and rendering via PyMuPDF.
"""
from __future__ import annotations

import fitz  # PyMuPDF
from PySide6.QtCore import QRectF, QPointF, QSizeF
from PySide6.QtGui import QImage, QColor
from typing import Optional, Iterator


class FenrirDocument:
    """Thread-safe wrapper around a PyMuPDF document."""

    def __init__(self, filepath: str) -> None:
        self._doc: fitz.Document = fitz.open(filepath)
        self._filepath = filepath
        self._rotation: dict[int, int] = {}  # page_num -> degrees

    # ── properties ──────────────────────────────────────────────

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    @property
    def metadata(self) -> dict:
        return dict(self._doc.metadata or {})

    @property
    def title(self) -> str:
        t = self.metadata.get("title", "")
        if not t:
            t = self._filepath.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return t

    @property
    def is_encrypted(self) -> bool:
        return self._doc.is_encrypted

    def authenticate(self, password: str) -> bool:
        return self._doc.authenticate(password) == 0  # 0 = success

    # ── page dimensions ─────────────────────────────────────────

    def page_size(self, page_num: int, dpi: float = 72.0) -> QSizeF:
        """Get the page size in points (1 pt = 1/72 inch)."""
        page = self._doc[page_num]
        rect = page.rect
        rot = self._rotation.get(page_num, 0)
        if rot in (90, 270):
            return QSizeF(rect.height, rect.width)
        return QSizeF(rect.width, rect.height)

    def page_rect(self, page_num: int) -> fitz.Rect:
        """Get the raw page rectangle in points."""
        return self._doc[page_num].rect

    # ── rendering ───────────────────────────────────────────────

    def render_page(
        self, page_num: int, dpi: float = 150.0, clip: Optional[fitz.Rect] = None
    ) -> QImage:
        """
        Render a page to a QImage at the given DPI.
        Returns an ARGB32 image suitable for display.
        """
        page = self._doc[page_num]
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        rot = self._rotation.get(page_num, 0)
        if rot:
            mat *= fitz.Matrix(fitz.Identity).prerotate(rot)

        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        if pix.n == 4:
            fmt = QImage.Format_RGBA8888
        else:
            fmt = QImage.Format_RGB888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
        return img

    def render_thumbnail(self, page_num: int, max_size: int = 200) -> QImage:
        """Render a small thumbnail of the page."""
        page = self._doc[page_num]
        rect = page.rect
        # Calculate DPI so the longest side fits within max_size
        longest = max(rect.width, rect.height)
        dpi = (max_size / longest) * 72.0
        return self.render_page(page_num, dpi=dpi)

    # ── text extraction ─────────────────────────────────────────

    def page_text(self, page_num: int) -> str:
        """Get all text from a page."""
        return self._doc[page_num].get_text("text")

    def page_text_blocks(self, page_num: int) -> list[dict]:
        """
        Get text blocks with positions.
        Returns list of dicts: {text, rect, type, block_no, lines}
        where rect is a fitz.Rect in page coordinates (points).
        """
        blocks = self._doc[page_num].get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
        result = []
        for block in blocks:
            if block["type"] == 0:  # text block
                lines = []
                for line in block["lines"]:
                    spans = []
                    for span in line["spans"]:
                        spans.append({
                            "text": span["text"],
                            "rect": span["bbox"],
                            "font": span["font"],
                            "size": span["size"],
                            "color": span["color"],
                        })
                    lines.append({"rect": line["bbox"], "spans": spans})
                result.append({
                    "text": "".join(s["text"] for line in lines for s in line["spans"]),
                    "rect": block["bbox"],
                    "type": "text",
                    "block_no": block["number"],
                    "lines": lines,
                })
            elif block["type"] == 1:  # image block
                result.append({
                    "text": "",
                    "rect": block["bbox"],
                    "type": "image",
                    "block_no": block["number"],
                    "image": block.get("image"),
                })
        return result

    def page_words(self, page_num: int) -> list[dict]:
        """Get individual words with precise positions."""
        words = self._doc[page_num].get_text("words")
        return [
            {
                "text": w[4],
                "rect": fitz.Rect(w[0], w[1], w[2], w[3]),
                "x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3],
            }
            for w in words
        ]

    def text_under_rect(self, page_num: int, rect: fitz.Rect) -> str:
        """Get the text contained within a given rectangle (in page coords)."""
        return self._doc[page_num].get_text("text", clip=rect)

    # ── search ──────────────────────────────────────────────────

    def search_page(
        self, page_num: int, query: str, *, case_sensitive: bool = False
    ) -> list[dict]:
        """
        Search for text on a page.
        Returns list of {text, rect} where rect is a fitz.Rect.
        """
        flags = 0 if case_sensitive else fitz.TEXT_PRESERVE_WHITESPACE
        results = self._doc[page_num].search_for(query, flags=flags)
        parsed = []
        for r in results:
            # PyMuPDF returns Quad objects (when quads=True default) or Rect objects
            # Quad has .rect, Rect is a rect itself
            if hasattr(r, "rect"):
                rect = r.rect
            else:
                rect = r
            parsed.append({"text": query, "rect": rect, "quads": r})
        return parsed

    def search_all_pages(
        self, query: str, *, case_sensitive: bool = False
    ) -> list[dict]:
        """Search across all pages. Returns list of {page, text, rect}."""
        results = []
        for i in range(self.page_count):
            page_results = self.search_page(i, query, case_sensitive=case_sensitive)
            for r in page_results:
                results.append({"page": i, **r})
        return results

    # ── table of contents / outline ─────────────────────────────

    def get_toc(self) -> list[dict]:
        """Get the table of contents as a flat/structured list."""
        raw = self._doc.get_toc()
        items = []
        for level, title, page, _ in raw:
            items.append({
                "level": level,
                "title": title,
                "page": max(0, page - 1),  # fitz uses 1-based, we use 0-based
            })
        return items

    # ── links & annotations ─────────────────────────────────────

    def get_links(self, page_num: int) -> list[dict]:
        """Get links on a page."""
        links = self._doc[page_num].get_links()
        return [
            {
                "kind": l.get("kind", -1),
                "uri": l.get("uri", ""),
                "page": l.get("page", 0),
                "rect": l.get("from", fitz.Rect(0, 0, 0, 0)),
            }
            for l in links
        ]

    def get_annotations(self, page_num: int) -> list[dict]:
        """Get annotations (highlights, notes, etc.) on a page."""
        page = self._doc[page_num]
        anots = []
        for an in page.annots():
            anots.append({
                "type": an.type[1] if an.type else "unknown",
                "info": dict(an.info) if an.info else {},
                "rect": an.rect,
            })
        return anots

    # ── rotation ────────────────────────────────────────────────

    def set_page_rotation(self, page_num: int, degrees: int) -> None:
        """Set view rotation for a single page (increments of 90)."""
        degrees = ((degrees % 360) // 90) * 90
        if degrees == 0:
            self._rotation.pop(page_num, None)
        else:
            self._rotation[page_num] = degrees

    def get_page_rotation(self, page_num: int) -> int:
        return self._rotation.get(page_num, 0)

    def rotate_all(self, degrees: int) -> None:
        """Rotate all pages by the given degrees (cumulative as view-only)."""
        for i in range(self.page_count):
            current = self._rotation.get(i, 0)
            self._rotation[i] = (current + degrees) % 360

    # ── form fields (AcroForms) ──────────────────────────────────

    FORM_FIELD_TYPES = {
        1: "button",        # PDF_WIDGET_TYPE_BUTTON
        2: "checkbox",      # PDF_WIDGET_TYPE_CHECKBOX
        3: "combo_box",     # PDF_WIDGET_TYPE_COMBOBOX
        4: "list_box",      # PDF_WIDGET_TYPE_LISTBOX
        5: "radio_button",  # PDF_WIDGET_TYPE_RADIOBUTTON
        6: "signature",     # PDF_WIDGET_TYPE_SIGNATURE
        7: "text",          # PDF_WIDGET_TYPE_TEXT
    }

    def has_forms(self) -> bool:
        """Check if the document has any interactive form fields."""
        for i in range(self.page_count):
            try:
                page = self._doc[i]
                # Force widget parsing by accessing the page
                if page.first_widget or list(page.widgets()):
                    return True
            except Exception:
                continue
        return False

    def get_form_fields(self, page_num: int) -> list[dict]:
        """Get all form field widgets on a page."""
        fields = []
        for widget in self._doc[page_num].widgets():
            choices = []
            if hasattr(widget, "choices") and widget.choices:
                choices = list(widget.choices)
            fields.append({
                "page": page_num,
                "name": widget.field_name or "",
                "type": self.FORM_FIELD_TYPES.get(widget.field_type, "unknown"),
                "type_num": widget.field_type,
                "rect": widget.rect,
                "value": widget.field_value or "",
                "label": widget.field_label or widget.field_name or "",
                "flags": widget.field_flags,
                "is_readonly": bool(widget.field_flags & 1),
                "is_required": bool(widget.field_flags & 2),
                "choices": choices,
            })
        return fields

    def set_form_field(self, page_num: int, field_name: str, value) -> None:
        """Set the value of a form field and update it."""
        page = self._doc[page_num]
        for widget in page.widgets():
            if widget.field_name == field_name or widget.field_label == field_name:
                widget.field_value = value
                widget.update()
                return

    def save_form(self, filepath: str) -> None:
        """Save filled form data back to the PDF (incremental save)."""
        self._doc.save(filepath, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        self._filepath = filepath

    # ── cleanup ─────────────────────────────────────────────────

    def close(self) -> None:
        if self._doc:
            self._doc.close()

    def __enter__(self) -> "FenrirDocument":
        return self

    def __exit__(self, *args) -> None:
        self.close()