"""The OCR engine layer, with a fake engine in place of RapidOCR.

Both supported packages return a different shape, and one of them returns numpy
scalars. Neither fact should be visible outside ``ingest/ocr.py``, so both are pinned
here without installing either package.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from kitab.ingest import ocr as ocrmod


class Modern:
    """What ``rapidocr`` >= 2 returns: parallel sequences of numpy values."""

    def __init__(self, boxes, txts, scores):
        self.boxes = boxes
        self.txts = txts
        self.scores = scores


def quad(x0, y0, x1, y1, dtype=np.float32):
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=dtype)


@pytest.fixture
def engine(monkeypatch):
    """Install a callable as the engine and hand back a setter for its result."""
    holder: dict = {}
    monkeypatch.setattr(ocrmod, "get_engine", lambda: (lambda image: holder["result"]))
    return holder


def test_modern_result_is_read(engine):
    engine["result"] = Modern(
        boxes=[quad(10, 20, 110, 45)],
        txts=["SUPPORT"],
        scores=[np.float32(0.91)],
    )
    (line,) = ocrmod.ocr_image("page.png")
    assert line.text == "SUPPORT"
    assert line.box == (10.0, 20.0, 110.0, 45.0)


def test_legacy_result_is_read(engine):
    """``rapidocr-onnxruntime`` returns ``(entries, elapsed)``."""
    engine["result"] = ([[quad(5, 5, 50, 25).tolist(), "RESISTANCE", 0.88]], 0.4)
    (line,) = ocrmod.ocr_image("page.png")
    assert line.text == "RESISTANCE"
    assert line.box == (5.0, 5.0, 50.0, 25.0)


def test_an_empty_page_is_not_an_error(engine):
    engine["result"] = Modern(boxes=None, txts=None, scores=None)
    assert ocrmod.ocr_image("page.png") == []
    engine["result"] = (None, None)
    assert ocrmod.ocr_image("page.png") == []


def test_low_confidence_lines_are_dropped(engine):
    engine["result"] = Modern(
        boxes=[quad(0, 0, 10, 10), quad(0, 20, 10, 30)],
        txts=["solid", "smudge"],
        scores=[np.float32(0.95), np.float32(0.2)],
    )
    assert [ln.text for ln in ocrmod.ocr_image("page.png")] == ["solid"]


def test_blank_text_is_dropped(engine):
    engine["result"] = Modern(
        boxes=[quad(0, 0, 10, 10)], txts=["   "], scores=[np.float32(0.99)]
    )
    assert ocrmod.ocr_image("page.png") == []


def test_boxes_survive_json(engine):
    """A figure's OCR lines are written to 02_document.json.

    numpy float32 is not JSON serialisable, and the failure lands *after* every page
    has been read -- so the coordinates are coerced as they leave the engine.
    """
    engine["result"] = Modern(
        boxes=[quad(1, 2, 3, 4)], txts=["LABEL"], scores=[np.float32(0.9)]
    )
    lines = ocrmod.ocr_image("page.png")
    assert all(type(v) is float for v in lines[0].box)

    entries = ocrmod.describe(lines, width=100, height=100)
    json.dumps(entries)  # must not raise
