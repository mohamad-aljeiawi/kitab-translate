"""The builtin PDF extractor.

These build small PDFs with PyMuPDF and read them back, because every bug this file
guards against was invisible in unit terms and obvious in the output: words run
together, a whole page collapsed into one paragraph, a contents page shredded into
fragments.
"""

import pymupdf
import pytest

from kitab.ingest.pdf import extract_pdf


def _pdf(tmp_path, draw) -> "pymupdf.Document":
    path = tmp_path / "in.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=504, height=720)
    draw(page)
    doc.save(path)
    doc.close()
    return path


def _markdown(tmp_path, draw) -> str:
    path = _pdf(tmp_path, draw)
    return extract_pdf(path, tmp_path / "out", backend="builtin").markdown


def test_contents_row_becomes_one_line(tmp_path):
    """A contents entry is three runs on one baseline: number, title, page.

    Read top-to-bottom they arrive as three separate lines, and the page number of one
    entry ends up glued to the section number of the next ("42 1.2").
    """

    def draw(page):
        for i, y in enumerate((100, 130, 160)):
            page.insert_text((72, y), f"1.{i + 1}", fontsize=10)
            page.insert_text((102, y), f"Section Number {i + 1} Title", fontsize=10)
            page.insert_text((418, y), str(40 + i), fontsize=10)

    md = _markdown(tmp_path, draw)
    assert "1.1 Section Number 1 Title 40" in md
    assert "1.2 Section Number 2 Title 41" in md
    # Each row stands alone rather than running into the next.
    assert "40 1.2" not in md


def test_words_are_not_run_together(tmp_path):
    """A PDF has no words; runs must be rejoined with the spaces the format drops."""

    def draw(page):
        page.insert_text((72, 100), "Readout of", fontsize=11)
        page.insert_text((130, 100), "superconducting qubits", fontsize=11)

    md = _markdown(tmp_path, draw)
    assert "Readout of superconducting qubits" in md
    assert "ofsuperconducting" not in md


def test_paragraphs_are_split_on_vertical_gaps(tmp_path):
    """Without this a page collapses into one block, which ruins the translation."""

    def draw(page):
        for y in (100, 114, 128):
            page.insert_text(
                (72, y), "First paragraph line of running text.", fontsize=11
            )
        for y in (180, 194):
            page.insert_text(
                (72, y), "Second paragraph after a clear gap.", fontsize=11
            )

    md = _markdown(tmp_path, draw)
    blocks = [b for b in md.split("\n\n") if b.strip()]
    assert len(blocks) >= 2


def test_orphan_bullet_joins_its_item(tmp_path):
    """PDFs draw the bullet as its own run, which otherwise becomes a lone dot."""

    def draw(page):
        page.insert_text((72, 100), "•", fontsize=11)
        page.insert_text((90, 100), "The first list item", fontsize=11)
        page.insert_text((72, 130), "•", fontsize=11)
        page.insert_text((90, 130), "The second list item", fontsize=11)

    md = _markdown(tmp_path, draw)
    assert "- The first list item" in md
    assert "- The second list item" in md
    # No paragraph consisting only of a bullet glyph.
    assert not any(b.strip() == "•" for b in md.split("\n\n"))


def test_headings_come_from_relative_size(tmp_path):
    def draw(page):
        page.insert_text((72, 100), "A Real Heading", fontsize=20)
        for y in (140, 154, 168, 182):
            page.insert_text(
                (72, y), "Body text that is much longer than the heading.", fontsize=10
            )

    md = _markdown(tmp_path, draw)
    assert "# A Real Heading" in md


def test_two_column_page_is_not_read_across_the_gutter(tmp_path):
    def draw(page):
        # Realistically wide columns: a narrow band of short entries is a *field*
        # (a contents page's page numbers), not a column, and must not split.
        for i, y in enumerate(range(100, 220, 15)):
            page.insert_text(
                (40, y), f"left column line {i} with real width", fontsize=10
            )
            page.insert_text(
                (270, y), f"right column line {i} with real width", fontsize=10
            )

    md = _markdown(tmp_path, draw)
    left = md.index("left column line 5")
    right = md.index("right column line 0")
    assert left < right, "the right column was interleaved into the left"


@pytest.mark.parametrize("pages,expected", [("1", 1), (None, 1)])
def test_page_selection(tmp_path, pages, expected):
    def draw(page):
        page.insert_text((72, 100), "Only page content here.", fontsize=11)

    path = _pdf(tmp_path, draw)
    result = extract_pdf(path, tmp_path / "out", backend="builtin", pages=pages)
    assert "Only page content here." in result.markdown


def _mono(page, point, text, size=8):
    page.insert_text(point, text, fontsize=size, fontname="cour")


def test_code_listing_becomes_a_fence(tmp_path):
    """The one that matters in a programming book: code handed to a translator comes
    back as 'if (رقم > 1؛ رقم2) {' -- syntactically dead and silently wrong."""

    def draw(page):
        page.insert_text(
            (72, 90), "The following example compares numbers.", fontsize=11
        )
        for i, line in enumerate(
            ["int main() {", '  cout << "hello";', "  return 0;", "}"]
        ):
            _mono(page, (72, 120 + i * 12), line)

    md = _markdown(tmp_path, draw)
    assert "```" in md
    assert 'cout << "hello";' in md
    # The prose is still prose.
    assert "The following example compares numbers." in md
    fence_body = md.split("```")[1]
    assert "int main() {" in fence_body
    assert "return 0;" in fence_body


def test_inline_code_inside_a_sentence_is_backticked(tmp_path):
    """Prose and code on the same line -- the mixed case, and the common one."""

    def draw(page):
        page.insert_text((72, 100), "The example uses six", fontsize=11)
        _mono(page, (170, 100), "if", size=11)
        page.insert_text((185, 100), "statements to compare numbers.", fontsize=11)

    md = _markdown(tmp_path, draw)
    assert "`if`" in md
    assert "```" not in md  # a single word is inline code, not a block


def test_listing_line_numbers_do_not_break_the_fence(tmp_path):
    """A blank line in a listing is a bare line number set in the body face."""

    def draw(page):
        rows = [("1", "int main() {"), ("2", ""), ("3", "  return 0;"), ("4", "}")]
        for i, (num, code) in enumerate(rows):
            y = 100 + i * 12
            page.insert_text((60, y), num, fontsize=9)
            if code:
                _mono(page, (80, y), code)

    md = _markdown(tmp_path, draw)
    assert md.count("```") == 2, "the listing was split into several fences"


def test_page_range_beyond_the_document_is_clamped(tmp_path):
    """Asking for more pages than exist is ordinary; it must not be fatal."""

    def draw(page):
        page.insert_text((72, 100), "The only page.", fontsize=11)

    path = _pdf(tmp_path, draw)
    result = extract_pdf(path, tmp_path / "out", backend="builtin", pages="1-50")
    assert "The only page." in result.markdown


def test_running_heads_and_page_numbers_are_dropped(tmp_path):
    """A running head is furniture, not content: left in, it is extracted from every
    page, translated every time, and lands as a stray paragraph on each one."""
    path = tmp_path / "book.pdf"
    doc = pymupdf.open()
    for n in range(8):
        page = doc.new_page(width=504, height=720)
        page.insert_text((72, 30), f"{100 + n} Chapter 2 Introduction", fontsize=9)
        for i, y in enumerate(range(120, 300, 15)):
            page.insert_text(
                (72, y), f"Body sentence {n}-{i} of the chapter.", fontsize=11
            )
        page.insert_text((250, 700), str(100 + n), fontsize=9)
    doc.save(path)
    doc.close()

    md = extract_pdf(path, tmp_path / "out", backend="builtin").markdown
    assert "Chapter 2 Introduction" not in md
    assert "Body sentence 3-2 of the chapter." in md


def test_a_short_document_keeps_everything(tmp_path):
    """Repetition means nothing in a two-page sample, so nothing may be dropped."""

    def draw(page):
        page.insert_text((72, 30), "Chapter 2 Introduction", fontsize=9)
        page.insert_text((72, 200), "The only body line.", fontsize=11)

    md = _markdown(tmp_path, draw)
    assert "Chapter 2 Introduction" in md


def test_wrapped_title_is_one_heading(tmp_path):
    """Centred display type: line two starts further right, which the paragraph
    indent rule reads as a new block. Emitted separately the two <h1>s each force a
    page break and the first is stranded on an empty page."""

    def draw(page):
        page.insert_text((119, 190), "Filling Out the Forms and the", fontsize=30)
        page.insert_text((162, 225), "Problem of Universals", fontsize=30)
        for y in range(300, 420, 15):
            page.insert_text(
                (72, y), "Body text that sets the base size here.", fontsize=15
            )

    md = _markdown(tmp_path, draw)
    assert "# Filling Out the Forms and the Problem of Universals" in md
    assert md.count("#") == 1


def test_drop_cap_does_not_make_a_heading(tmp_path):
    """A drop cap is one 30pt character on a 15pt line; taking the maximum span size
    turned every drop-capped paragraph into a heading."""

    def draw(page):
        page.insert_text((72, 120), "O", fontsize=30)
        page.insert_text(
            (95, 120), "n our second walk we discuss the Forms.", fontsize=15
        )
        for y in range(150, 260, 15):
            page.insert_text(
                (72, y), "More ordinary body text continues here.", fontsize=15
            )

    md = _markdown(tmp_path, draw)
    assert not md.lstrip().startswith("#")


def test_chapter_lines_are_promoted_when_typography_says_nothing(tmp_path):
    """Some ebook PDFs are one font at one size with no bold: the size heuristic
    correctly finds nothing, and the book becomes one unnavigable chapter."""
    path = tmp_path / "flat.pdf"
    doc = pymupdf.open()
    for n in range(6):
        page = doc.new_page(width=504, height=720)
        page.insert_text((72, 100), f"Chapter {n + 1}: A Title Here", fontsize=9)
        for i, y in enumerate(range(150, 400, 14)):
            page.insert_text(
                (72, y), f"Flat body text {n}-{i} at one single size.", fontsize=9
            )
    doc.save(path)
    doc.close()

    md = extract_pdf(path, tmp_path / "out", backend="builtin").markdown
    assert "# Chapter 1: A Title Here" in md
    assert "# Chapter 6: A Title Here" in md


def test_promotion_is_skipped_when_headings_exist(tmp_path):
    """A book with real typography must not get a second, weaker heading rule."""

    def draw(page):
        page.insert_text((72, 80), "A Genuine Big Heading", fontsize=22)
        page.insert_text(
            (72, 130), "Chapter 4 mentioned inside prose here.", fontsize=10
        )
        for y in range(160, 300, 14):
            page.insert_text(
                (72, y), "Body text at the ordinary size for this book.", fontsize=10
            )

    md = _markdown(tmp_path, draw)
    assert "# A Genuine Big Heading" in md
    assert "# Chapter 4" not in md
