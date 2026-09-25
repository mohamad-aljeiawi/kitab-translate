"""The document model: what gets segmented, what never reaches an engine, and that a
translated document still renders as the same structure."""

import pytest

from kitab.md.ast import MarkdownDocument, restore_escaped_literals
from kitab.md.mask import CURLY

SOURCE = """# Chapter 1: Ratios

The complexity is $O(n \\log n)$, see section 3.2.1 and `Fig. 4`.

- First *item* with [a link](http://x.io)
- Second item

> A quote about `code_style` things.

| Name | Value |
| ---- | ----- |
| Alpha | 1 |

```python
never_translated = True
```

![figure](images/f1.png)
"""


@pytest.fixture
def doc():
    document = MarkdownDocument(SOURCE)
    document.segments = document.build_segments(CURLY)
    return document


def test_kinds_are_labelled(doc):
    kinds = [s.kind for s in doc.segments]
    assert kinds[0] == "heading"
    assert "list_item" in kinds
    assert "blockquote" in kinds
    assert "table_cell" in kinds


def test_code_fence_is_never_a_segment(doc):
    assert all("never_translated" not in s.source for s in doc.segments)


def test_standalone_image_is_not_a_segment(doc):
    """Everything in that node is protected, so there is nothing to translate."""
    assert all("images/f1.png" not in s.source for s in doc.segments)


def test_numeric_table_cell_is_skipped(doc):
    assert all(s.source.strip() != "1" for s in doc.segments)


def test_translation_writes_back_and_preserves_structure(doc):
    for segment in doc.segments:
        segment.translation = "ترجمة " + segment.source
        segment.status = "translated"
    problems = doc.apply_translations(doc.segments, CURLY)
    assert problems == []

    out = restore_escaped_literals(
        doc.to_markdown(), [lit for s in doc.segments for lit in s.placeholders]
    )
    assert "ترجمة" in out
    assert "never_translated = True" in out  # fence untouched
    assert "![figure](images/f1.png)" in out  # image untouched
    assert "$O(n \\log n)$" in out  # formula restored
    assert "`code_style`" in out
    assert out.count("|") >= 6  # table still a table


def test_failed_placeholder_keeps_the_source(doc):
    target = next(s for s in doc.segments if "{{v" in s.source)
    target.translation = "ترجمة بدون عناصر محمية"  # every placeholder dropped
    target.status = "translated"
    problems = doc.apply_translations([target], CURLY)
    assert len(problems) == 1
    segment, missing, unexpected = problems[0]
    assert segment.id == target.id
    assert missing
    # The source survived: nothing was written back for this node.
    assert "ترجمة بدون" not in doc.to_markdown()


def test_bilingual_keeps_the_original(doc):
    target = doc.segments[0]
    target.translation = "الفصل الأول"
    target.status = "translated"
    doc.apply_translations([target], CURLY, bilingual=True)
    out = doc.to_markdown()
    assert "الفصل الأول" in out
    assert "kitab-orig" in out
    assert "Chapter 1: Ratios" in out


def test_html_output_is_rtl_and_isolates_code():
    from kitab.render.html import build_page

    page = build_page("# عنوان\n\nنص مع `code_here` بداخله.\n", title="اختبار")
    assert 'dir="rtl"' in page
    assert 'lang="ar"' in page
    assert "unicode-bidi: isolate" in page
    # Code is isolated by the stylesheet, so it must not also be wrapped in <bdi>.
    assert "<code>code_here</code>" in page


def test_wide_tables_get_a_scroll_container():
    from kitab.render.html import build_page

    page = build_page("| a | b |\n| - | - |\n| 1 | 2 |\n", title="t")
    assert 'class="table-wrap"' in page


def test_arabic_font_is_embedded_not_linked():
    """A linked Google font is served as WOFF2, which Chromium cannot embed in a PDF:
    it rasterises every glyph to Type 3 and the text layer comes out scrambled. The
    bundled TTF must therefore be inlined, and nothing may point at fonts.googleapis."""
    from kitab.render.html import build_page, font_face_css

    faces = font_face_css()
    assert "Noto Naskh Arabic" in faces
    assert "data:font/ttf;base64," in faces

    page = build_page("# عنوان\n\nنص عربي.\n", title="t")
    assert "fonts.googleapis.com" not in page
    assert "data:font/ttf;base64," in page


def test_fonts_can_be_left_out():
    from kitab.render.html import build_page

    page = build_page("# عنوان\n", title="t", embed_fonts=False)
    assert "data:font/ttf;base64," not in page
    assert "Noto Naskh Arabic" in page  # still first in the CSS stack


def test_sentence_final_punctuation_stays_with_the_arabic():
    """UAX #9 attaches a trailing full stop to the Latin run beside it, which puts it
    on the wrong side of an Arabic sentence. <bdi> around the Latin run fixes it."""
    from kitab.render.html import isolate_ltr_runs

    out = isolate_ltr_runs("<p>العنوان London EC1N 8TS.</p>")
    assert "<bdi>London EC1N 8TS</bdi>." in out  # stop outside the isolate


def test_bdi_is_not_added_inside_code():
    from kitab.render.html import isolate_ltr_runs

    out = isolate_ltr_runs("<p>نص <code>queue_size</code> نص</p>")
    assert "<code>queue_size</code>" in out


def test_bdi_does_not_touch_attributes():
    from kitab.render.html import isolate_ltr_runs

    out = isolate_ltr_runs('<img src="images/a.png" alt="" />')
    assert out == '<img src="images/a.png" alt="" />'


def test_entities_are_not_split_by_bdi():
    """'&quot;' is an ampersand plus the letters 'quot'. Wrapping the letters leaves
    '&<bdi>quot;</bdi>', which renders as the literal text &quot; -- the entity leak."""
    from kitab.render.html import isolate_ltr_runs

    out = isolate_ltr_runs("<p>نص &quot;see-in&quot; نص</p>")
    assert "&<bdi>" not in out
    assert out.count("&quot;") == 2
    for entity in ("&lt;", "&gt;", "&amp;", "&#8212;", "&#x2014;"):
        assert entity in isolate_ltr_runs(f"<p>عربي {entity} عربي</p>")


def test_strikethrough_survives_the_round_trip():
    """The parser reads ~~text~~, so the writer must write it back.

    mdformat has no renderer for the "s" token on its own; a PDF whose extracted
    text held a single ~~-~~ made the rebuild stage fail with KeyError: 's' after
    the whole book had been translated.
    """
    source = "~~-~~ University College\n\nKeep ~~this~~ and **that**.\n"
    doc = MarkdownDocument(source)
    out = doc.to_markdown()
    assert "~~-~~ University College" in out
    assert "Keep ~~this~~ and **that**." in out
