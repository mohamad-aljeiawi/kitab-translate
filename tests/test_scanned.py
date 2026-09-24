"""The scanned backend's geometry, without an OCR engine.

Everything here works on synthetic boxes and arrays. That is deliberate: the parts
that decide whether a book comes out readable -- what counts as a figure, which lines
are its labels, where the picture lands in the text -- are pure measurement, and they
should be testable on a machine that has never installed the ``ocr`` extra.
"""

from __future__ import annotations

import numpy as np
import pytest

from kitab.ingest.ocr import OcrLine, position_label
from kitab.ingest.scanned import (
    AXIS_TICK,
    NOMINAL_BODY,
    WATERMARK,
    _anchor,
    _body_height,
    _find_figures,
    _is_stray_tick,
    _partition,
    _text_column,
    _to_lines,
)
from kitab.ingest.pdf import _END_OF_PAGE


def line(text: str, x0: float, y0: float, x1: float, y1: float) -> OcrLine:
    return OcrLine(text=text, box=(x0, y0, x1, y1), confidence=0.9)


# ------------------------------------------------------------------ furniture


@pytest.mark.parametrize(
    "text", ["AnyScanner", "CamScanner", "scan", "Adobe Scan", "TapScanner"]
)
def test_watermark_matches_scanner_branding(text):
    assert WATERMARK.search(text)


@pytest.mark.parametrize("text", ["Scanning the market", "SCAN THE LEVELS", "scanner"])
def test_watermark_leaves_prose_alone(text):
    """'scan' as a whole line is furniture; 'scan' inside a sentence is content."""
    assert not WATERMARK.search(text) or text.lower() != "scan"


@pytest.mark.parametrize(
    "text", ["183.980", "-182.31", "1 900.00", "10 Jul 04:00", "16 Sep 20:45"]
)
def test_axis_tick_matches_chart_furniture(text):
    assert AXIS_TICK.match(text)


@pytest.mark.parametrize("text", ["SUPPORT", "PIN BAR", "Figure 3", "H4 GAP"])
def test_axis_tick_leaves_labels_alone(text):
    assert not AXIS_TICK.match(text)


def test_stray_tick_only_outside_the_text_column():
    column = (100.0, 500.0)
    inside = line("1998", 120, 40, 160, 55)
    outside = line("1998", 600, 40, 640, 55)
    assert not _is_stray_tick(inside, column)
    assert _is_stray_tick(outside, column)


# ------------------------------------------------------------------ columns


def test_text_column_picks_the_dominant_one():
    """Prose left, a captioned diagram right: the column is the left block alone.

    Taking the extent of every long line would span the whole page and make each
    figure look as though it interrupted the text.
    """
    body = "a sentence long enough to count as prose on this page"
    lines = [line(body, 90, y, 700, y + 20) for y in range(100, 400, 40)]
    lines.append(line(body, 900, 120, 1500, 140))
    column = _text_column(lines, scale=1.0)
    assert column == (90, 700)


def test_text_column_is_none_without_prose():
    assert _text_column([line("SELL", 10, 10, 60, 25)], scale=1.0) is None


# ------------------------------------------------------------------ figures


def blank(height=1000, width=800) -> np.ndarray:
    return np.full((height, width), 255, dtype=np.uint8)


def test_find_figures_reports_drawn_ink():
    page = blank()
    page[400:600, 200:600] = 0
    boxes = _find_figures(page, [])
    assert len(boxes) == 1
    x0, y0, x1, y1 = boxes[0]
    assert 190 <= x0 <= 210 and 590 <= x1 <= 610
    assert 390 <= y0 <= 410 and 590 <= y1 <= 610


def test_find_figures_ignores_ink_a_line_already_claimed():
    """Text is not a drawing: whatever OCR read is masked out before projecting."""
    page = blank()
    page[400:600, 200:600] = 0
    boxes = _find_figures(page, [line("claimed", 200, 400, 600, 600)])
    assert boxes == []


def test_find_figures_ignores_a_thin_rule():
    page = blank()
    page[500:503, 100:700] = 0
    assert _find_figures(page, []) == []


# ------------------------------------------------------------------ labels


def test_figure_claims_a_label_standing_just_below_it():
    """``BEARISH ENGULFING`` sits in the white gap under a chart.

    Left in the body flow it is merged onto the baseline of the prose beside it, and
    the translator receives a sentence with a chart callout spliced into it.
    """
    drawing = (400.0, 200.0, 800.0, 400.0)
    label = line("BEARISH ENGULFING", 500, 410, 700, 430)
    prose = line("a sentence of ordinary body text running across", 50, 300, 380, 320)
    flow, claimed, grown = _partition([label, prose], [drawing], scale=1.0)

    assert flow == [prose]
    assert claimed[0] == [label]
    assert grown[0][3] >= 430  # the crop grew to include its own label


def test_prose_in_the_facing_column_is_never_claimed():
    drawing = (400.0, 200.0, 800.0, 400.0)
    prose = line("a sentence of ordinary body text running across", 50, 250, 380, 270)
    flow, claimed, _ = _partition([prose], [drawing], scale=1.0, column=(50.0, 380.0))
    assert flow == [prose]
    assert claimed == {}


# ------------------------------------------------------------------ placement


def test_figure_over_the_text_column_is_anchored_where_it_sits():
    box = (100.0, 500.0, 700.0, 900.0)
    assert _anchor(box, column=(90.0, 720.0), scale=1.0) == 900.0


def test_figure_beside_the_text_column_goes_after_the_text():
    """Anchoring it by position would cut the facing paragraph in half."""
    box = (900.0, 500.0, 1500.0, 900.0)
    assert _anchor(box, column=(90.0, 700.0), scale=1.0) == _END_OF_PAGE


# ------------------------------------------------------------------ sizing


def test_body_height_prefers_the_page_and_falls_back_to_the_book():
    body = "a sentence long enough to be counted as prose here"
    page = [line(body, 0, y, 400, y + 12) for y in range(0, 120, 30)]
    assert _body_height(page, fallback=99.0) == 12
    assert _body_height([line("SELL", 0, 0, 40, 30)], fallback=99.0) == 99.0


def test_line_sizes_are_bucketed_not_measured():
    """Two body lines differing only by a descender must rank as one size.

    Measured heights alone produce a fresh "heading size" for every such wobble, and
    whole paragraphs come out as ``######``.
    """
    found = [
        line("ordinary text", 0, 0, 300, 11),
        line("ordinary (text)", 0, 20, 300, 32.9),
        line("A Real Heading", 0, 60, 300, 82),
    ]
    sizes = [ln.size for ln in _to_lines(found, typical=11.0)]
    assert sizes[0] == sizes[1] == NOMINAL_BODY
    assert sizes[2] > NOMINAL_BODY


def test_a_long_line_is_prose_however_tall_it_measures():
    text = "x" * 200
    (built,) = _to_lines([line(text, 0, 0, 900, 19)], typical=11.0)
    assert built.size == NOMINAL_BODY


def test_a_drawing_boxed_as_a_word_is_dropped():
    found = [line("|", 0, 0, 12, 200), line("ordinary text", 0, 0, 300, 11)]
    assert [ln.text for ln in _to_lines(found, typical=11.0)] == ["ordinary text"]


def test_sizes_do_not_depend_on_the_page_they_were_measured_on():
    """A page set in larger type still reports body text as body text.

    Body height is measured per page, so an absolute size would rank every sentence
    on a 13pt page above a book whose commonest size is 11pt.
    """
    small = _to_lines([line("ordinary text", 0, 0, 300, 11)], typical=11.0)
    large = _to_lines([line("ordinary text", 0, 0, 300, 15)], typical=15.0)
    assert small[0].size == large[0].size == NOMINAL_BODY


# ------------------------------------------------------------------ legend keys


def test_label_positions_are_relative_to_the_figure():
    assert position_label((10, 10, 30, 30), 300, 300) == "top-left"
    assert position_label((140, 140, 160, 160), 300, 300) == "middle-centre"
    assert position_label((270, 270, 290, 290), 300, 300) == "bottom-right"
