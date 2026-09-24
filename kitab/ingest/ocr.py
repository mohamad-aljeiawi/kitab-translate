"""Stage 3: the OCR engine.

Used in two places, and it is the same engine both times:

* a page of a scanned book, where OCR produces the document itself (``scanned.py``);
* a Tier-1 figure, where OCR produces the labels that become an Arabic legend.

RapidOCR on ONNX Runtime is the engine because it runs on a CPU laptop in a couple of
seconds per page and its bundled PP-OCR model reads both of kitab's input languages --
English and Japanese -- without a separate download. Surya (inside marker) is more
accurate and wants a GPU; on CPU it is minutes per page, which is a different product.

Two package generations are supported. ``rapidocr`` is the current one and the only
one installable on Python 3.13+; ``rapidocr_onnxruntime`` is its predecessor, still
common in existing environments, and it returns a different shape. Both are normalised
to :class:`OcrLine` here so nothing downstream has to know which is installed.

Neither is a hard dependency: without the ``ocr`` extra, scanned input is refused with
an explanation and every figure stays Tier 0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kitab.errors import MissingDependency

logger = logging.getLogger(__name__)

#: Rendering DPI for OCR, and the accuracy/speed knee for printed book pages.
#: Measured on a 131 dpi scan: 200 and 400 read the body text equally well and 400
#: read the small diagram labels slightly *worse*, so rendering above this buys
#: nothing but time. ``scanned.py`` never exceeds it.
RENDER_DPI = 200

#: Below this, a recognised line is noise. RapidOCR scores a confident line ~0.9.
MIN_CONFIDENCE = 0.5

_engine = None

#: Newest first: the successor package wins where both are installed.
_PACKAGES = ("rapidocr", "rapidocr_onnxruntime")


@dataclass
class OcrLine:
    text: str
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in image pixels
    confidence: float = 0.0


def available() -> bool:
    import importlib.util

    return any(importlib.util.find_spec(name) is not None for name in _PACKAGES)


def get_engine():
    """Load RapidOCR once. Model loading dominates a short run."""
    global _engine
    if _engine is not None:
        return _engine

    for name in _PACKAGES:
        try:
            module = __import__(name, fromlist=["RapidOCR"])
        except ImportError:
            continue
        _engine = module.RapidOCR()
        logger.debug("OCR engine: %s", name)
        return _engine

    raise MissingDependency("rapidocr", "ocr", "OCR (scanned pages and figure legends)")


def _recognise(image, min_confidence: float) -> list[OcrLine]:
    """Run the engine on a path or an array and normalise whatever comes back.

    ``rapidocr`` returns an object with parallel ``boxes``/``txts``/``scores``
    sequences, any of which is ``None`` when the page held no text.
    ``rapidocr_onnxruntime`` returns ``(entries, elapsed)`` where each entry is
    ``[box, text, score]``, or ``(None, None)`` for an empty page.
    """
    engine = get_engine()
    result = engine(image)

    if hasattr(result, "txts"):  # rapidocr >= 2
        # These arrive as numpy arrays, so `or []` would ask a whole array for its
        # truth value; only `is None` is a safe emptiness test here.
        empty: list = []
        boxes = empty if result.boxes is None else result.boxes
        texts = empty if result.txts is None else result.txts
        scores = empty if result.scores is None else result.scores
        entries = zip(boxes, texts, scores)
    else:  # rapidocr-onnxruntime
        entries = ((e[0], e[1], e[2]) for e in (result[0] or []))

    lines: list[OcrLine] = []
    for box, text, score in entries:
        text = str(text).strip()
        score = float(score)
        if not text or score < min_confidence:
            continue
        # float(), not just min(): rapidocr hands back numpy float32, and a figure's
        # OCR lines are written into 02_document.json -- where a float32 stops the
        # whole run with "Object of type float32 is not JSON serializable", after the
        # pages have already been read. Normalising here keeps numpy inside this
        # module, which is where the engine lives.
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        lines.append(
            OcrLine(
                text=text,
                box=(min(xs), min(ys), max(xs), max(ys)),
                confidence=score,
            )
        )
    return lines


def ocr_image(path: Path, min_confidence: float = MIN_CONFIDENCE) -> list[OcrLine]:
    """Read one image file. Lines come back in the order the engine found them."""
    return _recognise(str(path), min_confidence)


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
