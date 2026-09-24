"""Stage 2 for books that are pictures of books.

A scanned page has no spans, no font sizes and no image list -- it is one flat
bitmap in which prose, diagrams and chart screenshots are the same pixels. Reading
it back means doing by measurement what a digital PDF gets for free:

1. *Render* the page at the resolution its own scan actually carries.
2. *Recognise* the text, which gives a box and a confidence per line.
3. *Separate drawing from prose.* Ink that no recognised line covers is a diagram.
   Its extent becomes a figure; the labels standing inside it are its legend, not
   sentences in the body text.
4. *Rebuild the page* by handing the recognised lines to ``pdf.assemble_pages``, the
   same function the digital backend uses. An OCR box and a font span carry the same
   two facts -- where the line is and how tall it is -- so headings, paragraphs,
   columns and lists are recovered by exactly one implementation.

Step 3 is the reason this module exists. Joining every recognised line on a page into
one string, which is what the previous implementation did, splices axis ticks and
diagram callouts into the middle of sentences: the translator then receives prose that
has been cut in half by the words ``PRICE REJECTS HIGHER``, and the diagram those words
belong to is nowhere in the output at all.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from kitab import progress
from kitab.models import Figure

from .ocr import MIN_CONFIDENCE, RENDER_DPI, OcrLine, describe, get_engine, ocr_image
from .pdf import (
    _END_OF_PAGE,
    _assemble_lines,
    _Line,
    _strip_furniture,
    assemble_pages,
)

logger = logging.getLogger(__name__)

#: Phone-scanner branding, burnt into the bitmap on every page. It is not content,
#: and unlike a running head it can sit inside a figure, where the repetition test in
#: ``_strip_furniture`` will not look for it.
WATERMARK = re.compile(
    r"anyscanner|camscanner|tapscanner|scanner\s*pro|genius\s*scan|adobe\s*scan"
    r"|^scan$|^cs$",
    re.IGNORECASE,
)

#: A chart axis tick: a price, a level, a timestamp. A candlestick screenshot carries
#: dozens, they are identical in every language, and translating them costs money and
#: returns noise.
AXIS_TICK = re.compile(r"^[-+]?[\d\s.,:;']+$|^[\d\s]+\w{0,4}\s*[\d']{1,4}\s*[:.]\d{2}$")

#: A recognised line this tall, relative to body text, is a drawing artefact rather
#: than a word -- OCR occasionally boxes a candlestick as a character.
MAX_LINE_HEIGHT_RATIO = 4.0

#: Ink darker than this counts as a mark on the page.
INK_LEVEL = 200
#: A row of the page is part of a drawing if this share of it is ink.
INK_ROW_SHARE = 0.01
#: A column counts towards a figure's width on the same basis. Masking a recognised
#: line blanks its box, not its glyphs, so a little ink survives under the prose;
#: without a threshold here that residue stretches every figure to the full width of
#: the page and a diagram standing beside a column of text looks like one crossing it.
INK_COLUMN_SHARE = 0.02
#: Vertical white space, as a share of page height, that ends one figure.
FIGURE_GAP_SHARE = 0.02
#: A band shorter than this is a rule or a speck, not a figure.
FIGURE_MIN_HEIGHT_SHARE = 0.04
#: Slack around a figure when deciding whether a label stands inside it, in points.
FIGURE_MARGIN = 10.0
#: How far above or below its drawn extent a figure will reach to claim a label that
#: stands in its own columns, in points -- about two lines of body text.
ABSORB_GAP = 26.0
#: Share of a figure's width that must sit over the prose column before the figure
#: counts as interrupting the text rather than standing beside it.
FIGURE_COLUMN_OVERLAP = 0.5
#: Width of the buckets that lines are grouped into when looking for the main text
#: column, in points. Wide enough to absorb a ragged left edge, narrow enough to keep
#: two real columns apart.
COLUMN_BUCKET = 18.0

#: Never render below this; never render above it either, because the measurements in
#: ``ocr.RENDER_DPI`` show extra pixels past this point make small labels worse.
DPI_FLOOR = RENDER_DPI
DPI_CEILING = 300


@dataclass
class ScannedExtraction:
    markdown: str
    images_dir: Path
    figures: list[Figure] = field(default_factory=list)
    pages: int = 0
    dpi: int = RENDER_DPI


def extract_scanned(
    path: Path,
    out_dir: Path,
    pages: str | None = None,
    tier1: bool = True,
    min_confidence: float = MIN_CONFIDENCE,
) -> ScannedExtraction:
    """OCR an image-only PDF into Markdown, figures and figure legends."""
    import pymupdf

    from .pdf import _clamp_pages, _page_list

    get_engine()  # fail early, before rendering anything

    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    scratch = out_dir / "_ocr_pages"
    scratch.mkdir(exist_ok=True)

    page_flow: list[list[OcrLine]] = []
    page_widths: list[float] = []
    page_heights: list[float] = []
    extras: dict[int, list[tuple[float, str]]] = {}
    figures: list[Figure] = []

    with pymupdf.open(path) as doc:
        numbers = _clamp_pages(_page_list(pages), doc.page_count, path)
        progress.stage("ocr", len(numbers))
        for page_no in numbers:
            progress.check()
            page = doc[page_no]
            dpi = _render_dpi(page)
            scale = dpi / 72.0

            render = page.get_pixmap(dpi=dpi)
            image_path = scratch / f"page_{page_no:04d}.png"
            render.save(image_path)
            lines = [
                ln
                for ln in ocr_image(image_path, min_confidence)
                if not WATERMARK.search(ln.text)
            ]
            grey = _grey(pymupdf, render)

            column = _text_column(lines, scale)
            drawings = _find_figures(grey, lines)
            flow, labelled, drawings = _partition(lines, drawings, scale, column)

            page_extras: list[tuple[float, str]] = []
            for index, box in enumerate(drawings):
                labels = labelled.get(index, [])
                figure, markdown = _emit_figure(
                    page, page_no, index, box, labels, scale, images_dir, dpi, tier1
                )
                figures.append(figure)
                page_extras.append((_anchor(box, column, scale), markdown))

            if not drawings and not flow and _has_ink(grey):
                # Nothing was recognised and nothing was measured, but the page is not
                # blank. Emit it whole rather than silently dropping a page.
                figure, markdown = _whole_page(page, page_no, images_dir, dpi)
                figures.append(figure)
                page_extras.append((0.0, markdown))

            flow = [ln for ln in flow if not _is_stray_tick(ln, column)]
            page_flow.append([_in_points(ln, scale) for ln in flow])
            page_widths.append(page.rect.width)
            page_heights.append(page.rect.height)
            extras[page_no] = page_extras
            logger.info(
                "page %d: %d line(s), %d figure(s) at %d dpi",
                page_no + 1,
                len(flow),
                len(drawings),
                dpi,
            )
            image_path.unlink(missing_ok=True)
            progress.advance()

        pages_done = len(page_flow)

    _remove_quietly(scratch)

    # Body height is measured per page where the page says enough to measure it, and
    # falls back to the whole book where it does not. Neither alone works: one figure
    # for the book turns every page set in slightly larger type into a run of
    # headings, and one figure per page makes the lone title on a chapter opener
    # "body size" so the heading vanishes.
    book_height = _typical_height(page_flow)
    page_lines = [
        _assemble_lines(_to_lines(flow, _body_height(flow, book_height)), width)
        for flow, width in zip(page_flow, page_widths)
    ]
    page_lines = _strip_furniture(page_lines, page_heights)
    parts = assemble_pages(page_lines, numbers, extras)
    markdown = "\n\n".join(p for p in parts if p.strip())

    tier1_count = sum(1 for f in figures if f.tier == 1)
    logger.info(
        "scanned: %d page(s), %d figure(s), %d with legends",
        pages_done,
        len(figures),
        tier1_count,
    )
    return ScannedExtraction(
        markdown=markdown,
        images_dir=images_dir,
        figures=figures,
        pages=pages_done,
    )


# ------------------------------------------------------------------ rendering


def _render_dpi(page) -> int:
    """Render at the resolution the scan actually holds.

    A phone scan of a book is often 130 dpi. Rendering it at 600 invents pixels and,
    measurably, makes small labels *worse* rather than better, so the native figure is
    a floor to aim at and :data:`DPI_CEILING` is a hard stop.
    """
    width_inches = page.rect.width / 72.0
    if width_inches <= 0:
        return DPI_FLOOR
    native = 0.0
    for info in page.get_images(full=True):
        native = max(native, info[2] / width_inches)
    if native <= 0:
        return DPI_FLOOR
    return int(min(max(native, DPI_FLOOR), DPI_CEILING))


def _grey(pymupdf, render):
    """The page as a 2-D array of grey levels, for measuring ink."""
    import numpy as np

    flat = pymupdf.Pixmap(pymupdf.csGRAY, render)
    return np.frombuffer(flat.samples, dtype=np.uint8).reshape(flat.height, flat.width)


def _has_ink(grey) -> bool:
    return bool((grey < INK_LEVEL).mean() > 0.001)


# ------------------------------------------------------------------ figures


def _find_figures(
    grey, lines: list[OcrLine]
) -> list[tuple[float, float, float, float]]:
    """Ink that no recognised line covers: charts, candlesticks, arrows, hand drawing.

    Row projection only. A book page stacks its figures vertically, and a full-width
    band is the unit a caption and a legend attach to; splitting side-by-side panels
    apart would scatter one diagram's labels across several legends.
    """
    import numpy as np

    height, width = grey.shape
    ink = grey < INK_LEVEL
    for line in lines:
        x0, y0, x1, y1 = (int(v) for v in line.box)
        ink[max(0, y0) : y1 + 1, max(0, x0) : x1 + 1] = False

    rows = ink.sum(axis=1)
    busy = rows > INK_ROW_SHARE * width
    max_gap = FIGURE_GAP_SHARE * height
    min_height = FIGURE_MIN_HEIGHT_SHARE * height

    boxes: list[tuple[float, float, float, float]] = []
    start: int | None = None
    gap = 0
    for y, is_busy in enumerate(busy):
        if is_busy:
            if start is None:
                start = y
            gap = 0
        elif start is not None:
            gap += 1
            if gap > max_gap:
                _close(boxes, ink, start, y - gap, min_height, np)
                start = None
    if start is not None:
        _close(boxes, ink, start, height - 1, min_height, np)
    return boxes


def _close(boxes, ink, y0: int, y1: int, min_height: float, np) -> None:
    if y1 - y0 < min_height:
        return
    band = ink[y0 : y1 + 1]
    floor = max(2.0, INK_COLUMN_SHARE * band.shape[0])
    columns = np.nonzero(band.sum(axis=0) > floor)[0]
    if columns.size == 0:
        return
    boxes.append((float(columns[0]), float(y0), float(columns[-1]), float(y1)))


def _partition(
    lines: list[OcrLine],
    drawings: list[tuple[float, float, float, float]],
    scale: float,
    column: tuple[float, float] | None = None,
) -> tuple[list[OcrLine], dict[int, list[OcrLine]], list[tuple[float, ...]]]:
    """Split recognised lines into body text and per-figure labels.

    A figure grows as it claims labels. Row projection finds the *drawn* part of a
    diagram, but a callout like ``BEARISH ENGULFING`` is recognised text, so it was
    masked out of the ink and can sit in the white gap between two drawn bands. Left
    in the body flow it is merged onto the baseline of whatever prose runs beside it,
    and the translator receives "The market tries to move to an area, but it
    'rejected' by the BEARISH". Claimed by the figure, it becomes a legend entry and
    the crop widens to include it.

    Only a line that sits *within the figure's own columns* can be claimed, which is
    what keeps a paragraph in the facing column out of it.
    """
    margin = FIGURE_MARGIN * scale
    reach = ABSORB_GAP * scale
    boxes = [list(box) for box in drawings]
    claimed: dict[int, list[OcrLine]] = {}
    flow = list(lines)

    growing = True
    while growing:
        growing = False
        for index, box in enumerate(boxes):
            for line in list(flow):
                if not _vertically_near(line, box, reach):
                    continue
                # Either the label stands in the figure's own columns, or it stands
                # clear of the prose altogether -- a callout floating beside a
                # diagram belongs to the diagram, not to the paragraph it happens to
                # share a row with.
                if not _within_columns(line, box, margin) and not _outside(
                    line, column
                ):
                    continue
                claimed.setdefault(index, []).append(line)
                flow.remove(line)
                box[0] = min(box[0], line.box[0])
                box[1] = min(box[1], line.box[1])
                box[2] = max(box[2], line.box[2])
                box[3] = max(box[3], line.box[3])
                growing = True

    return flow, claimed, [tuple(box) for box in boxes]


def _text_column(lines: list[OcrLine], scale: float) -> tuple[float, float] | None:
    """The horizontal extent of the page's *main* column of prose.

    Taking the extent of every long line would be wrong on the layout this is here to
    handle: a page with prose on the left and a captioned diagram on the right has
    long lines in both halves, and their union is the whole page -- which would make
    every figure look like it interrupts the text. So the lines are grouped by where
    they begin and the largest group wins. Short lines are ignored throughout; a
    stranded label is not evidence of a column.
    """
    prose = [ln for ln in lines if len(ln.text) > 40]
    if not prose:
        return None
    bucket = max(1.0, COLUMN_BUCKET * scale)
    groups: dict[int, list[OcrLine]] = {}
    for line in prose:
        groups.setdefault(int(line.box[0] // bucket), []).append(line)
    main = max(groups.values(), key=len)
    return min(ln.box[0] for ln in main), max(ln.box[2] for ln in main)


def _anchor(
    box: tuple[float, ...], column: tuple[float, float] | None, scale: float
) -> float:
    """Where on the page this figure's Markdown belongs.

    A figure that shares the prose's columns interrupts it, so it is anchored at its
    own bottom edge and lands between the paragraphs it separates. A figure set
    *beside* the prose does not interrupt anything -- it merely overlaps the same
    rows -- so anchoring it by position would cut a sentence in half. That one goes
    after the text on its page, which keeps every paragraph whole at the cost of
    placing the picture a little lower than the page does.
    """
    if column is None:
        return box[3] / scale
    overlap = min(box[2], column[1]) - max(box[0], column[0])
    width = max(1.0, box[2] - box[0])
    return box[3] / scale if overlap / width > FIGURE_COLUMN_OVERLAP else _END_OF_PAGE


def _within_columns(line: OcrLine, box: list[float], margin: float) -> bool:
    """The line lies inside the figure's horizontal extent, not merely across it."""
    return line.box[0] >= box[0] - margin and line.box[2] <= box[2] + margin


def _vertically_near(line: OcrLine, box: list[float], reach: float) -> bool:
    """The gap between the line and the figure, not the line's containment in it.

    Requiring the whole line to fall inside ``box`` plus the slack rejects a caption
    set in larger type purely for being tall, however close to the figure it sits.
    """
    gap = max(box[1] - line.box[3], line.box[1] - box[3], 0.0)
    return gap <= reach


def _is_stray_tick(line: OcrLine, column: tuple[float, float] | None) -> bool:
    """An axis tick that no figure claimed.

    Only outside the text column, where a bare number cannot be a numbered list item
    or a sentence that happens to begin with a figure.
    """
    return _outside(line, column) and bool(AXIS_TICK.match(line.text))


def _outside(line: OcrLine, column: tuple[float, float] | None) -> bool:
    """The line does not touch the main text column at all."""
    if column is None:
        return False
    return line.box[2] < column[0] or line.box[0] > column[1]


def _emit_figure(
    page,
    page_no: int,
    index: int,
    box: tuple[float, float, float, float],
    labels: list[OcrLine],
    scale: float,
    images_dir: Path,
    dpi: int,
    tier1: bool,
) -> tuple[Figure, str]:
    """Crop the drawing out of the page and write its Markdown.

    The crop keeps the labels where the illustrator put them; the legend repeats them
    in reading order so they reach the translator. The image itself is never altered,
    which is the same bargain ``figures.py`` strikes for digital PDFs.
    """
    import pymupdf

    from kitab.figures import MIN_LEGEND_CHARS, MIN_LEGEND_LINES, _legend_markdown

    clip = (
        pymupdf.Rect(box[0] / scale, box[1] / scale, box[2] / scale, box[3] / scale)
        & page.rect
    )
    name = f"p{page_no:04d}_fig{index:02d}.png"
    page.get_pixmap(dpi=dpi, clip=clip).save(images_dir / name)

    target = f"images/{name}"
    figure = Figure(id=f"p{page_no:04d}f{index:02d}", path=target, tier=0)
    markdown = f"![]({target})"

    keep = [ln for ln in labels if not AXIS_TICK.match(ln.text)]
    dropped = len(labels) - len(keep)
    if dropped:
        logger.debug(
            "page %d figure %d: dropped %d axis tick(s)", page_no + 1, index, dropped
        )

    if not tier1 or not keep:
        return figure, markdown

    # Label positions are relative to the crop, not the page: a legend says where to
    # look on the picture the reader is actually shown.
    width = max(1.0, box[2] - box[0])
    height = max(1.0, box[3] - box[1])
    local = [
        OcrLine(
            text=ln.text,
            box=(
                ln.box[0] - box[0],
                ln.box[1] - box[1],
                ln.box[2] - box[0],
                ln.box[3] - box[1],
            ),
            confidence=ln.confidence,
        )
        for ln in keep
    ]
    entries = describe(local, int(width), int(height))
    if len(entries) < MIN_LEGEND_LINES:
        return figure, markdown
    if sum(len(e["text"]) for e in entries) < MIN_LEGEND_CHARS:
        return figure, markdown

    figure.tier = 1
    figure.ocr_lines = entries
    return figure, f"{markdown}\n\n{_legend_markdown(entries)}"


def _whole_page(page, page_no: int, images_dir: Path, dpi: int) -> tuple[Figure, str]:
    name = f"p{page_no:04d}_page.png"
    page.get_pixmap(dpi=dpi).save(images_dir / name)
    target = f"images/{name}"
    return Figure(id=f"p{page_no:04d}page", path=target, tier=0), f"![]({target})"


# ------------------------------------------------------------------ lines


def _in_points(line: OcrLine, scale: float) -> OcrLine:
    """The same line with its box in PDF points, so pages at different render
    resolutions can be compared against one set of thresholds."""
    return OcrLine(
        text=line.text,
        box=tuple(v / scale for v in line.box),  # type: ignore[arg-type]
        confidence=line.confidence,
    )


def _typical_height(page_flow: list[list[OcrLine]]) -> float:
    heights = sorted(
        ln.box[3] - ln.box[1] for flow in page_flow for ln in flow if ln.text
    )
    return heights[len(heights) // 2] if heights else 0.0


#: Long lines needed before a page is trusted to state its own body height.
MIN_LINES_FOR_LOCAL_HEIGHT = 3

#: A recognised line longer than this is prose whatever its measured height says.
#: ``_heading_level`` applies the same rule at 120 characters, but it sees one line
#: at a time and consecutive heading lines are joined afterwards -- so a lead
#: paragraph set two points larger than the body arrives as four 85-character
#: "headings" and leaves as one 340-character ``###``.
HEADING_MAX_CHARS = 80


def _body_height(flow: list[OcrLine], fallback: float) -> float:
    """This page's body height, measured from the only lines that must be prose.

    A line of sixty characters is a sentence, whatever size it is set in, so the
    median height of this page's long lines is its body height -- and anything
    standing well above it is a heading.
    """
    heights = sorted(ln.box[3] - ln.box[1] for ln in flow if len(ln.text) > 40)
    if len(heights) < MIN_LINES_FOR_LOCAL_HEIGHT:
        return fallback
    return heights[len(heights) // 2]


#: Line height as a multiple of body height, and the size bucket it falls in. A scan
#: gives a noisy size signal -- the same 11pt sentence measures 11.0 or 12.3 points
#: depending on whether it happens to contain a parenthesis or a descender -- so only
#: coarse distinctions are trusted. Without this, that noise alone produces four
#: "heading sizes" above body and whole paragraphs are emitted as ``######``.
_SIZE_BUCKETS = ((1.25, 1.0), (1.6, 1.35), (2.2, 1.8), (float("inf"), 2.6))

#: The size a body line is reported as, in nominal points. The number is arbitrary and
#: only the ratios matter -- but it has to be the *same* number on every page. Body
#: height is measured per page, so reporting the measured height directly would put a
#: page set in 13pt type above a book whose commonest size is 11pt, and every sentence
#: on that page would rank as a heading.
NOMINAL_BODY = 10.0


def _to_lines(found: list[OcrLine], typical: float) -> list[_Line]:
    """Adapt OCR boxes to the line type the layout engine already understands.

    ``size`` is the box height, bucketed. On a scan that is the only size signal
    there is, and coarsely it is a good one: a chapter title is physically two or
    three times the height of body text, which is what ``_heading_level`` ranks.
    """
    lines: list[_Line] = []
    for line in found:
        x0, y0, x1, y1 = line.box
        height = y1 - y0
        if typical <= 0:
            size = NOMINAL_BODY
        elif height > MAX_LINE_HEIGHT_RATIO * typical:
            continue  # a candlestick or a frame boxed as if it were a word
        elif len(line.text) > HEADING_MAX_CHARS:
            size = NOMINAL_BODY
        else:
            ratio = height / typical
            size = NOMINAL_BODY * next(m for limit, m in _SIZE_BUCKETS if ratio < limit)
        lines.append(
            _Line(
                text=line.text,
                size=size,
                bold=False,
                bbox=(x0, y0, x1, y1),
                raw=line.text,
                total_chars=len(line.text),
                non_mono=line.text,
            )
        )
    return lines


def _remove_quietly(directory: Path) -> None:
    try:
        directory.rmdir()
    except OSError:
        pass
