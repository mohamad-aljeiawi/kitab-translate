"""Stage 2: PDF to Markdown.

Three backends behind one interface, chosen by the ``--extractor`` flag:

``marker``
    Best structure fidelity, best image and table handling. Heavy (torch) and wants
    Python 3.11/3.12. Optional extra.
``fast``
    ``pymupdf4llm``. Pure CPU, no model beyond PyMuPDF's own layout work. Optional extra.
``builtin``
    Implemented here on PyMuPDF alone, which is already a hard dependency. Heading
    detection by relative font size, images exported per page. Less accurate than the
    other two on complex layouts, but it always works -- so the pipeline has no
    installation cliff, and a first run needs nothing extra.

The interface is deliberately narrow: a file in, Markdown plus an images directory out.
That is what makes stage 2 replaceable, which matters because the licence terms and the
accuracy ranking of these tools will both keep moving.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from kitab.errors import ExtractionError, MissingDependency

logger = logging.getLogger(__name__)

BACKENDS = ("auto", "marker", "fast", "builtin")


@dataclass
class Extraction:
    markdown: str
    images_dir: Path
    backend: str
    pages: int = 0


# ---------------------------------------------------------------- dispatch


def extract_pdf(
    path: Path, out_dir: Path, backend: str = "auto", pages: str | None = None
) -> Extraction:
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)

    if backend == "auto":
        for candidate in ("marker", "fast", "builtin"):
            if _available(candidate):
                backend = candidate
                break
    if backend not in BACKENDS or backend == "auto":
        raise ExtractionError(f"no usable PDF backend (asked for {backend!r})")

    logger.info("extracting %s with the %s backend", path.name, backend)
    if backend == "marker":
        return _extract_marker(path, out_dir, images_dir)
    if backend == "fast":
        return _extract_pymupdf4llm(path, out_dir, images_dir, pages)
    return _extract_builtin(path, images_dir, pages)


def _available(backend: str) -> bool:
    import importlib.util

    if backend == "builtin":
        return True
    module = {"marker": "marker", "fast": "pymupdf4llm"}[backend]
    return importlib.util.find_spec(module) is not None


# ---------------------------------------------------------------- backends


def _extract_marker(path: Path, out_dir: Path, images_dir: Path) -> Extraction:
    try:
        from marker.config.parser import ConfigParser
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered
    except ImportError as e:
        raise MissingDependency("marker-pdf", "marker", "The marker backend") from e

    config = ConfigParser({"output_format": "markdown"})
    converter = PdfConverter(
        config=config.generate_config_dict(),
        artifact_dict=create_model_dict(),
        processor_list=config.get_processors(),
        renderer=config.get_renderer(),
    )
    rendered = converter(str(path))
    markdown, _meta, images = text_from_rendered(rendered)

    for name, image in (images or {}).items():
        target = images_dir / Path(name).name
        image.save(target)
    markdown = _rewrite_image_paths(markdown)
    return Extraction(markdown=markdown, images_dir=images_dir, backend="marker")


def _extract_pymupdf4llm(
    path: Path, out_dir: Path, images_dir: Path, pages: str | None
) -> Extraction:
    try:
        import pymupdf4llm
    except ImportError as e:
        raise MissingDependency("pymupdf4llm", "fast", "The fast backend") from e

    # Images come back embedded and are written here, not by pymupdf4llm: its
    # md_path() uses one string as both the link and the save path after replacing
    # spaces, brackets and dashes in the *whole* path, so any folder with a space
    # in its name -- "My Books", or a work directory named after the book -- sent
    # every image to a directory that does not exist.
    markdown = pymupdf4llm.to_markdown(
        str(path),
        pages=_page_list(pages),
        embed_images=True,
        image_format="png",
    )
    markdown = _write_embedded_images(markdown, images_dir)
    return Extraction(markdown=markdown, images_dir=images_dir, backend="fast")


_EMBEDDED_IMAGE = re.compile(
    r"!\[([^\]]*)\]\(data:image/([A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)\)"
)


def _write_embedded_images(markdown: str, images_dir: Path) -> str:
    """Save every ``data:`` image to ``images_dir`` and link to the file instead."""
    import base64

    count = 0

    def save(match: re.Match) -> str:
        nonlocal count
        count += 1
        alt, kind, data = match.group(1), match.group(2).lower(), match.group(3)
        extension = {"jpeg": "jpg", "svg+xml": "svg"}.get(kind, kind)
        name = f"img-{count:04d}.{extension}"
        (images_dir / name).write_bytes(base64.b64decode(data))
        return f"![{alt}](images/{name})"

    return _EMBEDDED_IMAGE.sub(save, markdown)


def _extract_builtin(path: Path, images_dir: Path, pages: str | None) -> Extraction:
    """PyMuPDF only: spans -> sized lines -> headings, paragraphs and images.

    The heuristic is that body text is whichever font size occupies the most
    characters in the document; anything meaningfully larger and short is a heading,
    and heading levels come from ranking the sizes above body. That is crude next to a
    layout model, and it is exactly why ``report.json`` records which backend ran.
    """
    import pymupdf

    wanted = _page_list(pages)
    page_lines: list[list[_Line]] = []
    page_heights: list[float] = []
    image_refs: dict[int, list[str]] = {}

    with pymupdf.open(path) as doc:
        page_numbers = _clamp_pages(wanted, doc.page_count, path)
        for page_no in page_numbers:
            page = doc[page_no]
            lines: list[_Line] = []
            # sort=True orders blocks top-to-bottom, which is right for a single
            # column and merely not-worse for two. Multi-column papers want the
            # 'fast' or 'marker' backend; this one is for ordinary books.
            data = page.get_text("dict", sort=True)
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    built = _build_line(line)
                    if built is None:
                        continue
                    lines.append(built)
            lines = _assemble_lines(lines, page.rect.width)
            page_lines.append(lines)
            page_heights.append(page.rect.height)
            image_refs[page_no] = _export_images(doc, page, page_no, images_dir)

        pages_done = len(page_lines)

    page_lines = _strip_furniture(page_lines, page_heights)
    extras = {
        page_no: [(_END_OF_PAGE, f"![]({ref})") for ref in refs]
        for page_no, refs in image_refs.items()
    }
    parts = assemble_pages(page_lines, page_numbers, extras)
    markdown = "\n\n".join(p for p in parts if p.strip())
    return Extraction(
        markdown=markdown,
        images_dir=images_dir,
        backend="builtin",
        pages=pages_done,
    )


#: An extra with this y position is emitted after everything else on its page.
_END_OF_PAGE = float("inf")


def assemble_pages(
    page_lines: list[list["_Line"]],
    page_numbers: list[int],
    extras: dict[int, list[tuple[float, str]]] | None = None,
) -> list[str]:
    """Sized, positioned lines -> Markdown parts.

    Shared by the builtin backend and the OCR backend, which is the whole point: a
    scanned page and a digital one differ in how their lines are *found*, not in how
    headings, paragraphs, columns and lists are recovered from them. Everything below
    works off geometry and size, so OCR boxes feed it as well as font spans do.

    ``extras`` injects ready-made Markdown -- an image, a figure legend -- at a y
    position on a page, so a figure lands between the paragraphs it sits between
    rather than at the end of the page.
    """
    parts: list[str] = []
    size_chars: Counter[int] = Counter()
    for lines in page_lines:
        for line in lines:
            # Code is excluded: a page of listings would otherwise make the 8pt
            # monospace face the "body" size and turn the prose around it into
            # headings.
            if not line.is_code:
                size_chars[int(round(line.size))] += len(line.text)

    body_size = size_chars.most_common(1)[0][0] if size_chars else 10
    heading_sizes = sorted({s for s in size_chars if s > body_size + 0.5}, reverse=True)

    for offset, lines in enumerate(page_lines):
        page_no = page_numbers[offset]
        lines = _merge_orphan_bullets(lines)
        pending = sorted((extras or {}).get(page_no, []), key=lambda e: e[0])
        buffer: list[_Line] = []
        code: list[_Line] = []
        heading: list[_Line] = []
        heading_level = 0

        def flush_buffer() -> None:
            nonlocal buffer
            if buffer:
                parts.append(_join_paragraph(buffer))
                buffer = []

        def flush_code() -> None:
            if code:
                parts.append(_fence(code))
                code.clear()

        def flush_heading() -> None:
            if heading:
                parts.append(f"{'#' * heading_level} {_join_paragraph(heading)}")
                heading.clear()

        def flush_extras(before: float) -> None:
            """Emit every extra that belongs above ``before``.

            An extra closes whatever is open: a figure between two paragraphs
            separates them, and joining across it would be wrong.
            """
            while pending and pending[0][0] <= before:
                flush_buffer()
                flush_heading()
                flush_code()
                parts.append(pending.pop(0)[1])

        for line in lines:
            flush_extras(line.bbox[1])
            # Code first, and unconditionally: a listing line can be short, bold and
            # large enough to look like a heading, and misreading one as a heading
            # sends it to the translation engine.
            if line.is_code or (code and line.is_bare_number):
                flush_buffer()
                flush_heading()
                code.append(line)
                continue
            flush_code()

            level = _heading_level(
                line.size, line.bold, body_size, heading_sizes, line.text
            )
            if level:
                flush_buffer()
                # A chapter title set over two lines is one heading, not two. Emitted
                # separately they become two <h1>s, and with a page break before each
                # the first is stranded alone on an otherwise empty page.
                if (
                    heading
                    and heading_level == level
                    and _continues_heading(heading[-1], line, body_size)
                ):
                    heading.append(line)
                else:
                    flush_heading()
                    heading.append(line)
                    heading_level = level
                continue
            flush_heading()

            if _BULLET_LEAD.match(line.text):
                # A real list item: close the paragraph and emit Markdown, so the
                # renderer produces a <li> instead of a stray glyph in the prose.
                flush_buffer()
                parts.append(f"- {_BULLET_LEAD.sub('', line.text)}")
                continue
            if buffer and (
                line.fielded
                or buffer[-1].fielded
                or _starts_new_paragraph(buffer[-1], line, body_size)
            ):
                flush_buffer()
            buffer.append(line)
        flush_buffer()
        flush_heading()
        flush_code()
        flush_extras(_END_OF_PAGE)

    return _promote_chapter_lines(parts, len(page_lines))


# ---------------------------------------------------------------- helpers


def _heading_level(
    size: float,
    bold: bool,
    body_size: int,
    heading_sizes: list[int],
    text: str,
) -> int:
    """0 for body text, otherwise a Markdown heading level."""
    if len(text) > 120:  # a long line is a paragraph however it is set
        return 0
    rounded = int(round(size))
    if rounded in heading_sizes:
        rank = heading_sizes.index(rounded)
        return min(rank + 1, 6)
    if bold and rounded > body_size and len(text) < 80:
        return min(len(heading_sizes) + 1, 6)
    return 0


@dataclass
class _Line:
    text: str
    size: float
    bold: bool
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    #: Assembled from several runs on one baseline -- a contents entry, an index
    #: row, a caption beside a label. Such a row is a record, not a sentence, so it
    #: never joins the paragraph above or below it.
    fielded: bool = False
    #: The line with no inline code marks, for emitting inside a fenced block.
    raw: str = ""
    #: Characters set in a monospaced face, and characters in total.
    mono_chars: int = 0
    total_chars: int = 0
    #: Everything on the line that was *not* monospaced, for the ornament test.
    non_mono: str = ""

    @property
    def code_ratio(self) -> float:
        return self.mono_chars / self.total_chars if self.total_chars else 0.0

    @property
    def is_code(self) -> bool:
        """Mostly monospaced: a listing line, or a line of program output.

        Not simply "all monospaced". A printed listing line carries a line number set
        in the body face, so ``20 }`` is only one monospaced character out of three
        and a ratio test alone would send it to the translator. So a line also counts
        as code when everything *not* monospaced is just that ornament -- digits,
        spaces and separators.
        """
        if not self.mono_chars:
            return False
        if self.code_ratio >= _CODE_RATIO:
            return True
        return not _ORNAMENT.sub("", self.non_mono)

    @property
    def is_bare_number(self) -> bool:
        """A listing's line number with no code on it -- a blank line in the source."""
        return bool(self.text.strip()) and self.text.strip().isdigit()


#: Fraction of a line that must be monospaced for the line to be code.
_CODE_RATIO = 0.6
#: Line numbers, spaces and separators -- the furniture around a printed listing.
_ORNAMENT = re.compile(r"[\d\s.:|)(\[\]-]")

# PyMuPDF exposes a "monospaced" flag (bit 3), but plenty of real code faces do not
# set it -- this book sets its listings in LucidaSans-Typewriter with flags=0. So the
# font name is checked as well, and that is what actually does the work in practice.
_MONO_FLAG = 1 << 3
_MONO_NAME = re.compile(
    r"mono|courier|consol|typewriter|menlo|inconsolata|sourcecodepro|"
    r"dejavusansmono|liberationmono|hack|fira\s*code|jetbrains|andale|"
    r"lucidasanstypewriter|lucidaconsole|nimbusmono|ibmplexmono",
    re.IGNORECASE,
)


def _is_mono(span: dict) -> bool:
    """Is this span set in a monospaced face?"""
    if int(span.get("flags", 0)) & _MONO_FLAG:
        return True
    return bool(_MONO_NAME.search(str(span.get("font", "")).replace(" ", "")))


def _build_line(line: dict) -> "_Line | None":
    """Assemble one line from its spans, restoring the spaces PDF drops.

    A PDF has no words. Text is drawn as positioned runs, and a run boundary very
    often falls between two words with no space character anywhere -- concatenating
    the spans naively yields "Readoutofsuperconductingqubits". So a space is inserted
    wherever the horizontal gap between consecutive spans is wide enough to be one.

    Monospaced runs are also tracked and, where they are a minority of the line, are
    wrapped in backticks. That is the case that matters most in a programming book:
    "uses six ``if`` statements to compare two numbers" is one line mixing prose and
    code, and without the backticks the engine cheerfully translates ``if``.
    """
    parts: list[str] = []
    raw_parts: list[str] = []
    sizes: Counter[float] = Counter()
    bolds: list[bool] = []
    previous_x1: float | None = None
    x0 = y0 = x1 = y1 = 0.0
    mono_chars = total_chars = 0
    non_mono: list[str] = []
    in_mono = False

    for span in line.get("spans", []):
        text = span.get("text", "")
        if not text.strip():
            continue
        size = float(span.get("size", 0.0) or 0.0)
        bbox = span.get("bbox", (0.0, 0.0, 0.0, 0.0))
        mono = _is_mono(span)

        if parts:
            gap = bbox[0] - (previous_x1 or bbox[0])
            needs_space = (
                not raw_parts[-1].endswith((" ", "-", "‐"))
                and not text.startswith(" ")
                and gap > 0.2 * max(size, 1.0)
            )
            if needs_space:
                if in_mono and not mono:
                    parts.append("`")
                    in_mono = False
                parts.append(" ")
                raw_parts.append(" ")
        else:
            x0, y0 = bbox[0], bbox[1]

        # Adjacent monospaced runs stay inside a single pair of backticks.
        if mono and not in_mono:
            parts.append("`")
            in_mono = True
        elif in_mono and not mono:
            parts.append("`")
            in_mono = False

        parts.append(text)
        raw_parts.append(text)
        stripped = len(text.strip())
        total_chars += stripped
        if mono:
            mono_chars += stripped
        else:
            non_mono.append(text)
        sizes[round(size, 1)] += max(stripped, 1)
        bolds.append(bool(span.get("flags", 0) & 2**4))
        previous_x1 = bbox[2]
        x1, y1 = bbox[2], max(y1, bbox[3])

    if in_mono:
        parts.append("`")

    text = "".join(parts).strip()
    if not text:
        return None
    return _Line(
        text=text,
        raw="".join(raw_parts).strip(),
        mono_chars=mono_chars,
        total_chars=total_chars,
        non_mono="".join(non_mono),
        # Dominant size, not the largest: a drop cap is one 30pt character on a
        # 15pt line, and taking the maximum turned every drop-capped paragraph
        # into a heading -- which then forced a page break and left it stranded.
        size=sizes.most_common(1)[0][0] if sizes else 0.0,
        bold=any(bolds),
        bbox=(x0, y0, x1, y1),
    )


#: A gap this wide (as a fraction of page width) with no text crossing it is a
#: column boundary rather than word spacing.
_COLUMN_GAP = 0.06
#: Below this many lines a page has no reliable column structure to detect.
_MIN_COLUMN_LINES = 6
#: A column narrower than this fraction of the page is a field, not a column.
_MIN_COLUMN_WIDTH = 0.20


def _assemble_lines(lines: list["_Line"], page_width: float) -> list["_Line"]:
    """Turn PyMuPDF's positioned runs into logical lines, in reading order.

    Two different problems, and they have to be solved in this order.

    **Columns.** Sorting by vertical position reads a genuine two-column page across
    the gutter and interleaves it. So the page is split on any vertical band no line
    crosses, and each column is assembled independently.

    **Fields on one baseline.** Within a column, PyMuPDF returns each positioned run
    as its own "line". A contents entry is drawn as three runs at the same y --
    ``1.15`` at x=72, ``Boost C++ Libraries`` at x=101, ``79`` at x=418 -- so it
    arrives as three separate lines. Read top-to-bottom that produces the wreckage in
    the contents: the page number of one entry glued to the section number of the
    next ("42 1.2"), and every title stranded on a line of its own. Runs sharing a
    baseline are therefore merged left-to-right into one line.
    """
    if not lines:
        return lines
    return [
        merged
        for column in _split_columns(lines, page_width)
        for merged in _merge_baselines(column)
    ]


def _split_columns(lines: list["_Line"], page_width: float) -> list[list["_Line"]]:
    """Split into columns on a vertical band no line crosses, else return one column."""
    if len(lines) < _MIN_COLUMN_LINES or page_width <= 0:
        return [lines]

    # Occupancy histogram across the page width, one bucket per percent.
    buckets = 100
    occupied = [False] * buckets
    for line in lines:
        start = max(0, min(buckets - 1, int(line.bbox[0] / page_width * buckets)))
        end = max(0, min(buckets - 1, int(line.bbox[2] / page_width * buckets)))
        for i in range(start, end + 1):
            occupied[i] = True

    # Widest empty band that is not the page margin.
    best_start = best_len = 0
    run_start = None
    for i in range(buckets):
        if not occupied[i]:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and i - run_start > best_len:
                best_start, best_len = run_start, i - run_start
            run_start = None

    if best_len < _COLUMN_GAP * buckets:
        return [lines]
    split_at = (best_start + best_len / 2) / buckets * page_width

    left, right = [], []
    for line in lines:
        centre = (line.bbox[0] + line.bbox[2]) / 2
        (left if centre < split_at else right).append(line)

    # A heading spanning both columns lands wholly on one side; if either side is a
    # sliver this is not really a two-column page, so leave it as one.
    if min(len(left), len(right)) < 3:
        return [lines]

    # A real text column is wide. A narrow band of short entries at a fixed x is a
    # *field* -- the page-number column of a contents page, a marginal note -- and
    # splitting there separates every entry from its own page number, which is the
    # very thing baseline merging exists to put back together.
    for side in (left, right):
        extent = max(ln.bbox[2] for ln in side) - min(ln.bbox[0] for ln in side)
        if extent < _MIN_COLUMN_WIDTH * page_width:
            return [lines]

    # The source is left-to-right, so the left column is the earlier text.
    return [left, right]


def _merge_baselines(lines: list["_Line"]) -> list["_Line"]:
    """Join runs that share a baseline into one line, ordered left to right."""
    if len(lines) < 2:
        return lines

    heights = sorted(max(ln.bbox[3] - ln.bbox[1], 1.0) for ln in lines)
    median_height = heights[len(heights) // 2]
    # Under half a line height: catches a chapter number set slightly higher than its
    # title, without ever swallowing the next line of a paragraph.
    tolerance = max(2.0, 0.45 * median_height)

    ordered = sorted(lines, key=lambda ln: (ln.bbox[1], ln.bbox[0]))
    groups: list[list[_Line]] = []
    for line in ordered:
        if groups and abs(line.bbox[1] - groups[-1][0].bbox[1]) <= tolerance:
            groups[-1].append(line)
        else:
            groups.append([line])

    merged: list[_Line] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        group.sort(key=lambda ln: ln.bbox[0])
        merged.append(
            _Line(
                text=" ".join(ln.text for ln in group),
                raw=" ".join(ln.raw or ln.text for ln in group),
                mono_chars=sum(ln.mono_chars for ln in group),
                total_chars=sum(ln.total_chars for ln in group),
                non_mono="".join(ln.non_mono for ln in group),
                size=max(group, key=lambda ln: ln.total_chars).size,
                bold=any(ln.bold for ln in group),
                fielded=True,
                bbox=(
                    min(ln.bbox[0] for ln in group),
                    min(ln.bbox[1] for ln in group),
                    max(ln.bbox[2] for ln in group),
                    max(ln.bbox[3] for ln in group),
                ),
            )
        )
    return merged


def _fence(lines: list["_Line"]) -> str:
    """Emit consecutive code lines as one fenced block.

    A fence is a block token with no inline children, so ``md/ast.py`` never produces
    a segment for it and no translation engine ever sees it. That is the whole point:
    in a programming book, code handed to a translator comes back as
    ``if (رقم > 1؛ رقم2) {`` -- syntactically dead and silently wrong.

    The fence length adapts so a listing containing backticks still closes correctly.

    Indentation is deliberately *not* reconstructed. A PDF stores no leading spaces --
    an indented line is simply drawn further right -- so it would have to come from
    geometry, and measured against a real book the geometry contradicts the nesting:
    a statement inside an ``if`` reported a smaller x than the ``if`` itself.
    Confidently wrong indentation misleads about code structure far more than
    flush-left code does, so the listing keeps its line numbers and no invented shape.
    """
    body = "\n".join(ln.raw or ln.text for ln in lines)
    longest = 0
    run = 0
    for char in body:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{body}\n{fence}"


_BULLET_CHARS = "•●○▪▫◦‣·∙"
_BULLET_ONLY = re.compile(rf"^[{_BULLET_CHARS}]\s*$")
_BULLET_LEAD = re.compile(rf"^[{_BULLET_CHARS}]\s*")


def _merge_orphan_bullets(lines: list["_Line"]) -> list["_Line"]:
    """Attach a bullet glyph drawn as its own text run to the item it introduces.

    A PDF frequently draws the bullet and the item text as separate positioned runs,
    far enough apart that they never join into one line. Extracted naively they become
    a paragraph containing nothing but "•", which is what those lone dots floating
    above each list item were.
    """
    out: list[_Line] = []
    pending: _Line | None = None
    for line in lines:
        if _BULLET_ONLY.match(line.text):
            pending = line
            continue
        if pending is not None:
            line = _Line(
                text=f"{pending.text.strip()} {line.text}",
                raw=f"{pending.raw or pending.text} {line.raw or line.text}".strip(),
                mono_chars=line.mono_chars,
                total_chars=line.total_chars + len(pending.text.strip()),
                size=line.size,
                bold=line.bold,
                fielded=line.fielded,
                # Keep the bullet's own left edge so indentation logic still works.
                bbox=(
                    min(pending.bbox[0], line.bbox[0]),
                    min(pending.bbox[1], line.bbox[1]),
                    max(pending.bbox[2], line.bbox[2]),
                    max(pending.bbox[3], line.bbox[3]),
                ),
            )
            pending = None
        out.append(line)
    if pending is not None:  # a trailing bullet with nothing after it: drop it
        pass
    return out


def _continues_heading(previous: _Line, current: _Line, body_size: int) -> bool:
    """Is this line the rest of the heading above it?

    Only the vertical gap is consulted. The paragraph test cannot be reused here
    because display type is usually centred: "Filling Out the Forms and the" /
    "Problem of Universals" is one title whose second line starts 43pt further right,
    which the indent rule reads as a new paragraph. The leading scales with the
    heading's own size, so the threshold does too.
    """
    gap = current.bbox[1] - previous.bbox[3]
    return gap <= 0.6 * max(previous.size, current.size, body_size)


def _starts_new_paragraph(previous: _Line, current: _Line, body_size: int) -> bool:
    """A vertical gap or a first-line indent ends the previous paragraph.

    Without this every page collapses into one enormous block, which destroys both the
    reading experience and the translation: an engine given 4000 characters at once
    produces markedly worse Arabic than one given a paragraph.
    """
    gap = current.bbox[1] - previous.bbox[3]
    if gap > 0.55 * max(body_size, 1):
        return True
    # A line indented well past the previous one starts a paragraph in most book
    # typography; a line that starts further left is a new column or a hanging indent.
    if current.bbox[0] - previous.bbox[0] > 0.9 * max(body_size, 1):
        return True
    return False


_HYPHEN_BREAK = re.compile(r"(\w)[-‐]$")


def _join_paragraph(lines: list[_Line]) -> str:
    """Undo PDF line wrapping, including hyphenated breaks."""
    out = ""
    for line in lines:
        text = line.text
        if not out:
            out = text
            continue
        if _HYPHEN_BREAK.search(out):
            out = out[:-1] + text
        else:
            out = out + " " + text
    return re.sub(r"\s{2,}", " ", out).strip()


def _export_images(doc, page, page_no: int, images_dir: Path) -> list[str]:
    """Save every embedded raster on the page. Tiny images are ignored as furniture."""
    import pymupdf

    refs: list[str] = []
    for index, info in enumerate(page.get_images(full=True)):
        xref = info[0]
        try:
            pix = pymupdf.Pixmap(doc, xref)
            if pix.width < 48 or pix.height < 48:
                continue  # rules, bullets, logos in a running head
            if pix.n - pix.alpha >= 4:  # CMYK
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            name = f"p{page_no:04d}_img{index:02d}.png"
            pix.save(images_dir / name)
            refs.append(f"images/{name}")
        except Exception as e:  # a bad image must not stop the book
            logger.debug("page %d image %d skipped: %s", page_no, index, e)
    return refs


_IMAGE_LINK = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _rewrite_image_paths(markdown: str) -> str:
    """Normalise every image reference to ``images/<name>``."""

    def fix(match: re.Match) -> str:
        alt, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "data:")):
            return match.group(0)
        return f"![{alt}](images/{Path(target).name})"

    return _IMAGE_LINK.sub(fix, markdown)


#: Fraction of the page height at top and bottom where furniture lives.
_BAND = 0.12
#: A line must recur on this share of pages before it counts as a running head.
_FURNITURE_SHARE = 0.25
_DIGITS = re.compile(r"\d+")


def _strip_furniture(
    page_lines: list[list["_Line"]], page_heights: list[float]
) -> list[list["_Line"]]:
    """Drop running heads, running feet and page numbers.

    A running head is not content. Left in, "100 Chapter 2 Introduction to C++
    Programming, Input/Output and Operators" is extracted from every page, translated
    every time, and lands as a stray paragraph at the top of each one.

    Detection is by repetition, not position alone: a line in the top or bottom band
    of the page whose text -- with digits removed, so the page number does not make
    each instance unique -- recurs across at least a quarter of the pages. A real
    heading appears once, so it cannot be caught by this. Below three pages nothing is
    dropped, because repetition means nothing in a short sample.
    """
    if not page_lines:
        return page_lines

    def key(text: str) -> str:
        return " ".join(_DIGITS.sub("", text).split()).lower()

    counts: Counter[str] = Counter()
    for lines, height in zip(page_lines, page_heights):
        for text in {
            key(ln.text) for ln in lines if _in_band(ln, height) and key(ln.text)
        }:
            counts[text] += 1

    threshold = max(3, int(_FURNITURE_SHARE * len(page_lines)))
    furniture = {text for text, count in counts.items() if count >= threshold}

    stripped: list[list[_Line]] = []
    dropped = 0
    for lines, height in zip(page_lines, page_heights):
        kept = []
        for line in lines:
            if _in_band(line, height):
                marker = key(line.text)
                # An empty key means the line was only digits: a page number.
                if not marker or marker in furniture:
                    dropped += 1
                    continue
            kept.append(line)
        stripped.append(kept)

    if dropped:
        logger.info("dropped %d running head/foot line(s)", dropped)
    return stripped


def _in_band(line: "_Line", height: float) -> bool:
    if height <= 0:
        return False
    return line.bbox[3] < _BAND * height or line.bbox[1] > (1 - _BAND) * height


_CHAPTER_LINE = re.compile(
    r"^(chapter|part|appendix|section|book|walk)\s+"
    r"(\d{1,3}|[ivxlcdm]{1,7}|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)


def _promote_chapter_lines(parts: list[str], pages_done: int) -> list[str]:
    """Name chapters by their text when the typography says nothing.

    Some ebook PDFs are set in a single font at a single size with no bold anywhere
    -- every span in "Social Engineering" is ArialRegular 9pt, flags 0. There is no
    typographic signal to find, so the size heuristic correctly finds nothing, and the
    result is a 400-page book that is one unnavigable chapter with no breaks.

    Only then, and only then, are short lines that name a chapter promoted. A document
    whose typography does distinguish headings is left alone, because this rule is
    weaker evidence and English-specific.
    """
    headings = sum(1 for part in parts if part.startswith("#"))
    if headings >= max(3, pages_done // 40):
        return parts

    promoted = 0
    out: list[str] = []
    for part in parts:
        if (
            not part.startswith(("#", "```", "-", "!"))
            and len(part) < 90
            and _CHAPTER_LINE.match(part)
            # A title does not end in a full stop. Without this, an ordinary
            # sentence that happens to open with "Chapter 4 explains ..." becomes a
            # heading and forces a page break in the middle of the prose.
            and not part.rstrip().endswith(
                (".", "!", "?", chr(1548), chr(1563), chr(1567))
            )
        ):
            out.append(f"# {part}")
            promoted += 1
        else:
            out.append(part)
    if promoted:
        logger.info(
            "no typographic headings found; promoted %d chapter line(s) by name",
            promoted,
        )
    return out


def _clamp_pages(wanted: list[int] | None, page_count: int, path: Path) -> list[int]:
    """Restrict a requested page range to what the document actually has.

    ``--pages 60-110`` on a 108-page book used to raise IndexError from deep inside
    PyMuPDF. Asking for more pages than exist is an ordinary thing to do -- you rarely
    know the length in advance -- so it is clamped and reported, not fatal.
    """
    if wanted is None:
        return list(range(page_count))
    inside = [p for p in wanted if 0 <= p < page_count]
    if len(inside) != len(wanted):
        logger.warning(
            "%s has %d pages; %d requested page(s) outside that range were ignored",
            path.name,
            page_count,
            len(wanted) - len(inside),
        )
    return inside


def _page_list(pages: str | None) -> list[int] | None:
    """Parse "1-5,8" into zero-based page indices."""
    if not pages:
        return None
    out: list[int] = []
    for chunk in pages.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, end = chunk.split("-", 1)
            out.extend(range(int(start) - 1, int(end)))
        else:
            out.append(int(chunk) - 1)
    return sorted({p for p in out if p >= 0})
