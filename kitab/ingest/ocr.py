"""Stage 3: OCR.

Used in two places, and it is the same engine both times:

* a scanned PDF, where OCR produces the document itself;
* a Tier-1 figure, where OCR produces the labels that become an Arabic legend.

RapidOCR on ONNX Runtime is the default because it runs on a CPU laptop in seconds per
page. Surya (inside marker) is more accurate and wants a GPU; on CPU it is minutes per
page, which is a different product. Neither is a hard dependency: without the ``ocr``
extra installed, scanned input is refused with an explanation and every figure stays
Tier 0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kitab.errors import MissingDependency

logger = logging.getLogger(__name__)

#: Rendering DPI for OCR. 200 is the accuracy/speed knee for printed book pages.
RENDER_DPI = 200

_engine = None


@dataclass
class OcrLine:
    text: str
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in image pixels
    confidence: float = 0.0


def available() -> bool:
    import importlib.util

    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def get_engine():
    """Load RapidOCR once. Model loading dominates a short run."""
    global _engine
    if _engine is not None:
        return _engine
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as e:
        raise MissingDependency(
            "rapidocr-onnxruntime", "ocr", "OCR (scanned pages and figure legends)"
        ) from e
    _engine = RapidOCR()
    return _engine


def ocr_image(path: Path, min_confidence: float = 0.5) -> list[OcrLine]:
    """Read one image. Returns lines in reading order as the engine found them."""
    engine = get_engine()
    result, _elapsed = engine(str(path))
    lines: list[OcrLine] = []
    for entry in result or []:
        box, text, score = entry[0], entry[1], float(entry[2])
        if score < min_confidence or not str(text).strip():
            continue
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        lines.append(
            OcrLine(
                text=str(text).strip(),
                box=(min(xs), min(ys), max(xs), max(ys)),
                confidence=score,
            )
        )
    return lines


def ocr_pdf_to_markdown(
    path: Path, out_dir: Path, pages: str | None = None
) -> tuple[str, Path]:
    """OCR a scanned PDF into flat Markdown.

    Deliberately flat: without a layout model there is no reliable heading signal in a
    scan, and inventing one produces a wrong table of contents, which is worse than
    none. Pages become ``## Page N`` so a human can navigate and fix the structure in
    the intermediate Markdown before translation.
    """
    import pymupdf

    from .pdf import _clamp_pages, _page_list

    engine = get_engine()  # fail early, before rendering anything
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    scratch = out_dir / "_ocr_pages"
    scratch.mkdir(exist_ok=True)

    wanted = _page_list(pages)
    parts: list[str] = []

    with pymupdf.open(path) as doc:
        indices = _clamp_pages(wanted, doc.page_count, path)
        for page_no in indices:
            page = doc[page_no]
            pixmap = page.get_pixmap(dpi=RENDER_DPI)
            image_path = scratch / f"page_{page_no:04d}.png"
            pixmap.save(image_path)

            result, _elapsed = engine(str(image_path))
            texts = [str(entry[1]).strip() for entry in (result or [])]
            texts = [t for t in texts if t]
            logger.info("page %d: %d lines", page_no + 1, len(texts))

            parts.append(f"## Page {page_no + 1}")
            if texts:
                parts.append(" ".join(texts))
            image_path.unlink(missing_ok=True)

    scratch.rmdir()
    return "\n\n".join(parts), images_dir


def position_label(
    box: tuple[float, float, float, float], width: int, height: int
) -> str:
    """Coarse 3x3 position, used to key a figure legend entry.

    A reader needs to find the label on the untouched image; "top-left" does that and
    survives any later change to how the figure is rendered.
    """
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2 / max(width, 1)
    cy = (y0 + y1) / 2 / max(height, 1)
    row = "top" if cy < 1 / 3 else ("middle" if cy < 2 / 3 else "bottom")
    col = "left" if cx < 1 / 3 else ("centre" if cx < 2 / 3 else "right")
    return f"{row}-{col}"


ARABIC_POSITION: dict[str, str] = {
    "top-left": "أعلى اليسار",
    "top-centre": "أعلى الوسط",
    "top-right": "أعلى اليمين",
    "middle-left": "الوسط الأيسر",
    "middle-centre": "الوسط",
    "middle-right": "الوسط الأيمن",
    "bottom-left": "أسفل اليسار",
    "bottom-centre": "أسفل الوسط",
    "bottom-right": "أسفل اليمين",
}


def describe(lines: list[OcrLine], width: int, height: int) -> list[dict[str, Any]]:
    """Turn OCR lines into legend entries, ordered top-to-bottom then left-to-right."""
    entries = [
        {
            "text": line.text,
            "pos": position_label(line.box, width, height),
            "box": list(line.box),
            "confidence": round(line.confidence, 3),
        }
        for line in lines
    ]
    entries.sort(key=lambda e: (e["box"][1], e["box"][0]))
    return entries
