"""End-to-end, with a fake engine.

The engine is fake on purpose: these tests are about the pipeline's contracts --
ordering, batch-shape recovery, placeholder verification, resumability and the EPUB's
RTL metadata -- none of which should depend on a network or a key.
"""

import json
import zipfile
from pathlib import Path

import pytest

from kitab.md.mask import CURLY
from kitab.pipeline import Options, translate_book
from kitab.translate.base import BaseTranslator
from kitab.translate.registry import ENGINES

BOOK = """# The Ratio Chapter

A paragraph about `queue_size` and the bound $O(n \\log n)$ in section 3.2.1.

- One item
- Another item

## Second Heading

More text here for the second chapter.
"""


class FakeTranslator(BaseTranslator):
    """Prefixes each segment, keeping placeholders. Records what it was asked."""

    name = "fake"
    mask_style = CURLY
    batch_size = 4
    supports_glossary = True

    calls: list[list[str]] = []

    def __init__(self, *args, **kwargs):
        kwargs.pop("glossary", None)
        super().__init__(*args, glossary={}, **kwargs)
        self.calls = []

    def do_translate(self, text: str) -> str:
        return "AR " + text

    def do_translate_batch(self, texts):
        self.calls.append(list(texts))
        return ["AR " + t for t in texts]


class DroppingTranslator(FakeTranslator):
    """Loses every placeholder -- the failure the verifier exists to catch."""

    name = "dropping"

    def do_translate(self, text: str) -> str:
        return CURLY.pattern.sub("", "AR " + text)

    def do_translate_batch(self, texts):
        return [self.do_translate(t) for t in texts]


class WrongLengthTranslator(FakeTranslator):
    """Returns a short array once, to exercise the per-segment fallback."""

    name = "wronglen"

    def do_translate_batch(self, texts):
        return ["AR " + t for t in texts][:-1] if len(texts) > 1 else ["AR " + texts[0]]


@pytest.fixture(autouse=True)
def register_fakes():
    for cls in (FakeTranslator, DroppingTranslator, WrongLengthTranslator):
        ENGINES[cls.name] = cls
    yield
    for cls in (FakeTranslator, DroppingTranslator, WrongLengthTranslator):
        ENGINES.pop(cls.name, None)


@pytest.fixture
def book(tmp_path: Path) -> Path:
    path = tmp_path / "sample.md"
    path.write_text(BOOK, encoding="utf-8")
    return path


def _options(**kwargs) -> Options:
    base = dict(service="fake", glossary=False, epub=True, pdf=False, ignore_cache=True)
    base.update(kwargs)
    return Options(**base)


def test_end_to_end_produces_an_epub(book, tmp_path):
    result = translate_book(book, tmp_path / "out", options=_options())

    assert result.epub_path and result.epub_path.exists()
    assert result.report.segments_failed == 0
    assert result.report.segments_total > 0

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "AR " in markdown
    assert "`queue_size`" in markdown  # protected content survived
    assert "$O(n \\log n)$" in markdown
    assert "3.2.1" in markdown


def test_epub_declares_rtl_page_progression(book, tmp_path):
    result = translate_book(book, tmp_path / "out", options=_options())
    with zipfile.ZipFile(result.epub_path) as archive:
        opf = next(n for n in archive.namelist() if n.endswith(".opf"))
        content = archive.read(opf).decode("utf-8")
        assert 'page-progression-direction="rtl"' in content
        assert "<dc:language>ar</dc:language>" in content

        chapter = next(n for n in archive.namelist() if n.endswith("ch0000.xhtml"))
        xhtml = archive.read(chapter).decode("utf-8")
        assert 'dir="rtl"' in xhtml
        assert 'lang="ar"' in xhtml


def test_report_is_written_and_complete(book, tmp_path):
    out = tmp_path / "out"
    translate_book(book, out, options=_options())
    report = json.loads((out / "sample.ar.report.json").read_text(encoding="utf-8"))
    assert report["service"] == "fake"
    assert report["segments_total"] == report["segments_translated"]
    assert report["segments_failed"] == 0


def test_lost_placeholders_keep_the_source_and_are_reported(book, tmp_path):
    result = translate_book(
        book, tmp_path / "out", options=_options(service="dropping")
    )
    assert result.report.segments_failed > 0
    assert result.report.failures
    assert any("missing" in f["reason"] for f in result.report.failures)

    # The paragraph with protected content was left in the source language rather
    # than published with a formula missing.
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "`queue_size`" in markdown
    assert "$O(n \\log n)$" in markdown


def test_short_batch_falls_back_to_single_segments(book, tmp_path):
    result = translate_book(
        book, tmp_path / "out", options=_options(service="wronglen")
    )
    assert result.report.segments_failed == 0
    assert result.report.segments_translated == result.report.segments_total


def test_run_is_resumable(book, tmp_path):
    out = tmp_path / "out"
    work = tmp_path / "work"
    translate_book(book, out, work_dir=work, options=_options())
    assert (work / "03_translated.json").exists()

    # A second run with an engine that would fail must not translate anything: the
    # stage output already exists.
    result = translate_book(
        book, out, work_dir=work, options=_options(service="dropping")
    )
    assert result.report.segments_failed == 0


def test_force_reruns_every_stage(book, tmp_path):
    out = tmp_path / "out"
    work = tmp_path / "work"
    translate_book(book, out, work_dir=work, options=_options())
    result = translate_book(
        book, out, work_dir=work, options=_options(service="dropping", force=True)
    )
    assert result.report.segments_failed > 0


def test_bilingual_output_keeps_the_original(book, tmp_path):
    result = translate_book(book, tmp_path / "out", options=_options(bilingual=True))
    html = result.html_path.read_text(encoding="utf-8")
    assert "kitab-orig" in html
    assert "The Ratio Chapter" in html


def test_split_level_makes_one_chapter_per_heading(book, tmp_path):
    result = translate_book(book, tmp_path / "out", options=_options(split_level=2))
    with zipfile.ZipFile(result.epub_path) as archive:
        chapters = [n for n in archive.namelist() if n.endswith(".xhtml") and "ch" in n]
    assert len(chapters) >= 2


def test_batching_preserves_order_and_count(book, tmp_path):
    """The worst failure this pipeline can have is a batch coming back misaligned."""
    from kitab.translate.registry import get_translator

    translator = get_translator("fake", lang_in="en", ignore_cache=True)
    sources = [f"segment number {i}" for i in range(11)]
    out = translator.translate_many(sources)
    assert len(out) == len(sources)
    assert out == ["AR " + s for s in sources]


def test_images_are_published_next_to_the_html(tmp_path):
    """The HTML says images/<name>, relative to itself; the extractor writes them to
    01_extract/images/. Without the copy every figure in the HTML and PDF is broken."""
    src = tmp_path / "book.md"
    src.write_text("# Title\n\nSome text.\n\n![](images/fig1.png)\n", encoding="utf-8")

    work = tmp_path / "work"
    (work / "01_extract" / "images").mkdir(parents=True)
    out = tmp_path / "out"
    translate_book(src, out, work_dir=work, options=_options())

    # Extraction rewrote the reference; whatever it produced must resolve from the HTML.
    html = (work / "05_book.html").read_text(encoding="utf-8")
    import re

    for target in re.findall(r'<img[^>]*src="([^"]+)"', html):
        assert (
            work / target
        ).parent.exists(), f"{target} has no directory beside the HTML"
