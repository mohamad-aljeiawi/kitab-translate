"""Stage 1: decide what the input is.

One boolean decides the hardware budget for the whole run: does this PDF have a text
layer, or does it need OCR? Everything downstream -- which extractor, whether the OCR
extra is required, how long to tell the user it will take -- follows from it, so it is
worth measuring rather than assuming.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from pathlib import Path

from kitab.errors import UnsupportedInput

logger = logging.getLogger(__name__)

#: Below this many extracted characters per page, a PDF is a picture of a book.
SCANNED_THRESHOLD_CHARS = 120
#: How many pages to sample. Front matter is often image-heavy in a digital book, so
#: sample across the whole document rather than the first N pages.
SAMPLE_PAGES = 12


class SourceKind(enum.Enum):
    EPUB = "epub"
    PDF_DIGITAL = "pdf_digital"
    PDF_SCANNED = "pdf_scanned"
    MARKDOWN = "markdown"
    TEXT = "text"
    HTML = "html"


@dataclass
class SourceInfo:
    kind: SourceKind
    path: Path
    pages: int = 0
    chars_per_page: float = 0.0
    title: str = ""

    @property
    def needs_ocr(self) -> bool:
        return self.kind is SourceKind.PDF_SCANNED


_SUFFIX_KINDS = {
    ".epub": SourceKind.EPUB,
    ".md": SourceKind.MARKDOWN,
    ".markdown": SourceKind.MARKDOWN,
    ".txt": SourceKind.TEXT,
    ".html": SourceKind.HTML,
    ".htm": SourceKind.HTML,
}


def classify(path: str | Path) -> SourceInfo:
    """Identify the input and, for a PDF, measure its text layer."""
    path = Path(path)
    if not path.exists():
        raise UnsupportedInput(f"no such file: {path}")

    suffix = path.suffix.lower()
    if suffix in _SUFFIX_KINDS:
        return SourceInfo(kind=_SUFFIX_KINDS[suffix], path=path, title=path.stem)
    if suffix != ".pdf":
        raise UnsupportedInput(
            f"unsupported input {suffix or '(no extension)'}; "
            f"kitab reads .pdf, .epub, .md, .txt and .html"
        )

    import pymupdf

    with pymupdf.open(path) as doc:
        pages = doc.page_count
        if pages == 0:
            raise UnsupportedInput(f"{path} has no pages")
        step = max(1, pages // SAMPLE_PAGES)
        sampled = list(range(0, pages, step))[:SAMPLE_PAGES]
        total = sum(len(doc[i].get_text("text").strip()) for i in sampled)
        per_page = total / len(sampled)
        title = (doc.metadata or {}).get("title") or path.stem

    kind = (
        SourceKind.PDF_SCANNED
        if per_page < SCANNED_THRESHOLD_CHARS
        else SourceKind.PDF_DIGITAL
    )
    logger.info(
        "%s: %d pages, %.0f chars/page sampled -> %s",
        path.name,
        pages,
        per_page,
        kind.value,
    )
    return SourceInfo(
        kind=kind,
        path=path,
        pages=pages,
        chars_per_page=per_page,
        title=str(title).strip() or path.stem,
    )
