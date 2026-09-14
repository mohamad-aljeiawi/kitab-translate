"""Stage 1-3 dispatcher: any supported input to Markdown plus images."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from kitab.errors import UnsupportedInput

from .classify import SourceInfo, SourceKind, classify

logger = logging.getLogger(__name__)


@dataclass
class Extracted:
    markdown: str
    images_dir: Path
    info: SourceInfo
    backend: str
    meta: dict


def extract(
    path: str | Path,
    out_dir: Path,
    extractor: str = "auto",
    pages: str | None = None,
    ocr: bool = False,
) -> Extracted:
    """Produce the Markdown document model for ``path`` under ``out_dir``.

    ``ocr`` only matters for scanned PDFs; for a digital PDF it is ignored, because
    running OCR over a page that already has a text layer is slower and less accurate
    than reading the layer.
    """
    info = classify(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if info.kind is SourceKind.EPUB:
        from .epub import extract_epub

        markdown, images_dir, meta = extract_epub(info.path, out_dir)
        return Extracted(markdown, images_dir, info, "epub", meta)

    if info.kind is SourceKind.HTML:
        from .epub import extract_html

        markdown, images_dir, meta = extract_html(info.path, out_dir)
        return Extracted(markdown, images_dir, info, "html", meta)

    if info.kind in (SourceKind.MARKDOWN, SourceKind.TEXT):
        images_dir = out_dir / "images"
        images_dir.mkdir(exist_ok=True)
        # utf-8-sig, not utf-8: a byte-order mark ahead of "# " stops markdown-it
        # recognising the first heading, and Windows editors write BOMs by default.
        markdown = info.path.read_text(encoding="utf-8-sig", errors="replace")
        return Extracted(
            markdown, images_dir, info, "passthrough", {"title": info.title}
        )

    if info.kind in (SourceKind.PDF_DIGITAL, SourceKind.PDF_SCANNED):
        from .pdf import extract_pdf

        if info.kind is SourceKind.PDF_SCANNED:
            if not ocr:
                logger.warning(
                    "%s looks scanned (%.0f chars/page). Without --ocr the text layer "
                    "is all there is, and it is nearly empty.",
                    info.path.name,
                    info.chars_per_page,
                )
            else:
                from .ocr import ocr_pdf_to_markdown

                markdown, images_dir = ocr_pdf_to_markdown(info.path, out_dir, pages)
                return Extracted(
                    markdown, images_dir, info, "ocr", {"title": info.title}
                )

        result = extract_pdf(info.path, out_dir, backend=extractor, pages=pages)
        return Extracted(
            result.markdown,
            result.images_dir,
            info,
            result.backend,
            {"title": info.title, "pages": info.pages},
        )

    raise UnsupportedInput(f"cannot extract {info.kind.value}")
