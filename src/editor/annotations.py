"""
Fenrir Annotation Engine — data models, PyMuPDF integration, and annotation I/O.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

import fitz

from src.engine.document import FenrirDocument


# ── Annotation Types ───────────────────────────────────────────

ANNOT_TYPES = {
    "highlight": fitz.PDF_ANNOT_HIGHLIGHT,
    "underline": fitz.PDF_ANNOT_UNDERLINE,
    "strikethrough": fitz.PDF_ANNOT_STRIKE_OUT,
    "note": fitz.PDF_ANNOT_TEXT,
    "ink": fitz.PDF_ANNOT_INK,
    "textbox": fitz.PDF_ANNOT_FREE_TEXT,
    "rectangle": fitz.PDF_ANNOT_SQUARE,
    "circle": fitz.PDF_ANNOT_CIRCLE,
}

DISPLAY_COLORS = {
    "highlight": (1.0, 0.9, 0.2),    # yellow
    "underline": (0.0, 0.6, 0.0),     # green
    "strikethrough": (1.0, 0.2, 0.2), # red
    "note": (1.0, 0.8, 0.0),         # gold
    "ink": (0.0, 0.4, 0.8),          # blue
    "textbox": (0.0, 0.4, 0.8),       # blue
    "rectangle": (0.0, 0.4, 0.8),     # blue
    "circle": (0.0, 0.4, 0.8),        # blue
}

# How each annot type renders on the canvas
RENDER_STYLES = {
    "highlight": "fill",
    "underline": "underline",
    "strikethrough": "strikethrough",
    "note": "icon",
    "ink": "stroke",
    "textbox": "text",
    "rectangle": "stroke",
    "circle": "stroke",
}


def _normalized_color(color) -> tuple[float, float, float]:
    """Ensure color is a normalized RGB tuple (0.0–1.0)."""
    if isinstance(color, str):
        c = fitz.utils.getColor(color)
        return (c[0], c[1], c[2])
    if isinstance(color, (list, tuple)):
        c = tuple(float(x) / 255.0 if x > 1.0 else float(x) for x in color[:3])
        return c
    return (1.0, 0.9, 0.2)


class Annotation:
    """In-memory representation of a PDF annotation."""

    __slots__ = (
        "id", "type", "page", "rect", "color", "opacity",
        "content", "author", "date_created", "paths",
        "font_size", "border_width", "pdf_annot",  # PyMuPDF annot reference
        "is_new",
    )

    def __init__(
        self,
        annot_type: str = "highlight",
        page: int = 0,
        rect: Optional[tuple] = None,
        color: Optional[tuple] = None,
        opacity: float = 0.3,
        content: str = "",
        author: str = "Fenrir",
        paths: Optional[list] = None,
        font_size: float = 12.0,
        border_width: float = 1.0,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.type = annot_type
        self.page = page
        self.rect = list(rect) if rect else [0, 0, 0, 0]
        self.color = _normalized_color(color or DISPLAY_COLORS.get(annot_type, (1, 1, 0)))
        self.opacity = opacity
        self.content = content
        self.author = author
        self.date_created = time.time()
        self.paths = paths or []
        self.font_size = font_size
        self.border_width = border_width
        self.pdf_annot = None
        self.is_new = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "page": self.page,
            "rect": self.rect,
            "color": list(self.color),
            "opacity": self.opacity,
            "content": self.content,
            "author": self.author,
            "date_created": self.date_created,
            "paths": self.paths,
            "font_size": self.font_size,
            "border_width": self.border_width,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Annotation":
        a = cls(
            annot_type=data["type"],
            page=data["page"],
            rect=data.get("rect"),
            color=tuple(data.get("color", (1, 1, 0))),
            opacity=data.get("opacity", 0.3),
            content=data.get("content", ""),
            author=data.get("author", "Fenrir"),
            paths=data.get("paths", []),
            font_size=data.get("font_size", 12.0),
            border_width=data.get("border_width", 1.0),
        )
        a.id = data.get("id", a.id)
        a.date_created = data.get("date_created", time.time())
        a.is_new = data.get("is_new", False)
        return a

    def __repr__(self) -> str:
        return f"Annot({self.type}, pg={self.page}, id={self.id})"


class AnnotationManager:
    """
    Manages annotations for a document.
    - Loads existing annotations from the PDF on open
    - Tracks new/modified annotations in memory
    - Writes annotations back to the PDF on save
    """

    def __init__(self, doc: FenrirDocument):
        self._doc = doc
        self._annotations: dict[str, Annotation] = {}  # id -> Annotation
        self._page_annotations: dict[int, list[Annotation]] = {}  # page -> list
        self._dirty = False
        self._load_existing()

    # ── Loading ─────────────────────────────────────────────────

    def _load_existing(self) -> None:
        """Load existing PDF annotations into memory."""
        if not self._doc:
            return
        pdf = self._doc._doc  # access raw fitz doc
        for page_num in range(pdf.page_count):
            page = pdf[page_num]
            for an in page.annots():
                annot = self._pymupdf_to_annotation(an, page_num)
                if annot:
                    annot.is_new = False
                    annot.pdf_annot = an
                    self._annotations[annot.id] = annot
                    self._page_annotations.setdefault(page_num, []).append(annot)

    def _pymupdf_to_annotation(self, an, page_num: int) -> Optional[Annotation]:
        """Convert a PyMuPDF annotation to our Annotation model."""
        try:
            atype = an.type
            if atype is None:
                return None

            type_name = None
            for name, val in ANNOT_TYPES.items():
                if val == atype[0]:
                    type_name = name
                    break

            if type_name is None:
                type_name = "note"

            rect = list(an.rect) if an.rect else [0, 0, 0, 0]
            color = an.colors.get("fill") or an.colors.get("stroke") or (1.0, 1.0, 0.0)
            opacity = an.opacity if an.opacity else 0.3
            info = an.info or {}
            content = info.get("content", "")
            author = info.get("title", "Fenrir")

            annot = Annotation(
                annot_type=type_name,
                page=page_num,
                rect=rect,
                color=color,
                opacity=opacity,
                content=content,
                author=author,
            )
            annot.id = str(hash(an.rect))[:8]
            annot.pdf_annot = an
            annot.is_new = False
            return annot

        except Exception:
            return None

    # ── Adding ──────────────────────────────────────────────────

    def add_highlight(self, page_num: int, rect: tuple) -> Annotation:
        """Add a highlight annotation."""
        annot = Annotation("highlight", page_num, rect, opacity=0.3)
        self._add(annot)
        return annot

    def add_underline(self, page_num: int, rect: tuple) -> Annotation:
        """Add an underline annotation."""
        annot = Annotation("underline", page_num, rect, opacity=0.5)
        self._add(annot)
        return annot

    def add_strikethrough(self, page_num: int, rect: tuple) -> Annotation:
        """Add a strikethrough annotation."""
        annot = Annotation("strikethrough", page_num, rect, opacity=0.5)
        self._add(annot)
        return annot

    def add_note(self, page_num: int, rect: tuple, content: str = "") -> Annotation:
        """Add a sticky note annotation."""
        annot = Annotation("note", page_num, rect, opacity=1.0, content=content)
        self._add(annot)
        return annot

    def add_ink(self, page_num: int, paths: list, color=None) -> Annotation:
        """Add a freehand ink annotation."""
        annot = Annotation(
            "ink", page_num, color=color,
            paths=paths, opacity=0.8, border_width=2.0,
        )
        # For ink, rect is computed from paths
        if paths:
            all_x = [p[0] for path in paths for p in path]
            all_y = [p[1] for path in paths for p in path]
            if all_x and all_y:
                annot.rect = [min(all_x), min(all_y), max(all_x), max(all_y)]
        self._add(annot)
        return annot

    def add_textbox(self, page_num: int, rect: tuple, content: str = "") -> Annotation:
        """Add a text box annotation."""
        annot = Annotation("textbox", page_num, rect, opacity=1.0, content=content, font_size=14)
        self._add(annot)
        return annot

    def _add(self, annot: Annotation) -> None:
        """Internal: register annotation."""
        self._annotations[annot.id] = annot
        self._page_annotations.setdefault(annot.page, []).append(annot)
        self._dirty = True

    # ── Removal ─────────────────────────────────────────────────

    def remove(self, annot_id: str) -> bool:
        """Remove an annotation by ID."""
        if annot_id not in self._annotations:
            return False
        annot = self._annotations[annot_id]
        # Remove from page list
        if annot.page in self._page_annotations:
            self._page_annotations[annot.page] = [
                a for a in self._page_annotations[annot.page]
                if a.id != annot_id
            ]
        # Delete from PDF if already committed
        if annot.pdf_annot:
            try:
                page = self._doc._doc[annot.page]
                page.delete_annot(annot.pdf_annot)
            except Exception:
                pass
        del self._annotations[annot_id]
        self._dirty = True
        return True

    # ── Query ───────────────────────────────────────────────────

    def for_page(self, page_num: int) -> list[Annotation]:
        """Get all annotations on a given page."""
        return list(self._page_annotations.get(page_num, []))

    def all_annotations(self) -> list[Annotation]:
        return list(self._annotations.values())

    def count(self) -> int:
        return len(self._annotations)

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ── Save ────────────────────────────────────────────────────

    def save(self, filepath: Optional[str] = None, incremental: bool = True) -> bool:
        """
        Write all new annotations to the PDF and save.
        Returns True on success.
        """
        if not self._doc:
            return False

        pdf = self._doc._doc

        try:
            for annot in self._annotations.values():
                if not annot.is_new:
                    continue
                if annot.pdf_annot:
                    continue  # already committed

                # Create annotation on the PDF page
                page = pdf[annot.page]
                rect = fitz.Rect(*annot.rect)

                try:
                    if annot.type == "highlight":
                        pdf_annot = page.add_highlight_annot(rect)
                        pdf_annot.set_colors(stroke=annot.color)
                        pdf_annot.set_opacity(annot.opacity)

                    elif annot.type == "underline":
                        pdf_annot = page.add_underline_annot(rect)
                        pdf_annot.set_colors(stroke=annot.color)
                        pdf_annot.set_opacity(annot.opacity)

                    elif annot.type == "strikethrough":
                        pdf_annot = page.add_strikeout_annot(rect)
                        pdf_annot.set_colors(stroke=annot.color)
                        pdf_annot.set_opacity(annot.opacity)

                    elif annot.type == "note":
                        pdf_annot = page.add_text_annot(rect.tl, annot.content or "")
                        pdf_annot.set_colors(stroke=annot.color)
                        pdf_annot.set_opacity(annot.opacity)
                        pdf_annot.set_info(content=annot.content, title=annot.author)

                    elif annot.type == "ink":
                        # Paths are in page coordinates
                        pdf_annot = page.add_ink_annot(annot.paths)
                        pdf_annot.set_colors(stroke=annot.color)
                        pdf_annot.set_opacity(annot.opacity)
                        pdf_annot.set_border(width=annot.border_width)

                    elif annot.type == "textbox":
                        pdf_annot = page.add_freetext_annot(
                            rect, annot.content or "",
                            fontsize=annot.font_size,
                        )
                        pdf_annot.set_colors(stroke=annot.color, fill=(1, 1, 1))
                        pdf_annot.set_opacity(annot.opacity)

                    else:
                        continue

                    # Common properties
                    pdf_annot.set_info(title=annot.author)
                    pdf_annot.update()

                    annot.pdf_annot = pdf_annot
                    annot.is_new = False

                except Exception as e:
                    print(f"Annotation creation error: {e}")
                    continue

            # Save the PDF
            target = filepath or self._doc.filepath
            if incremental and not filepath:
                pdf.save(target, incremental=True, encryption=0)
            else:
                pdf.save(target, incremental=False, encryption=0)

            self._dirty = False
            return True

        except Exception as e:
            print(f"Save error: {e}")
            return False