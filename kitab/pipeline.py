"""The pipeline.

Six stages, each writing its output to the work directory before the next one starts:

    1-3  ingest    source          -> work/01_extract/document.md + images/
      -  figures   document.md     -> work/02_document.json   (segments + figure tiers)
      4  translate segments        -> work/03_translated.json
      5  rebuild   segments        -> work/04_translated.md, work/05_book.html
      6  emit      html            -> out/<name>.ar.epub, out/<name>.ar.pdf

Two properties follow from that shape and both are the point of the design:

*Resumable.* A stage whose output already exists is skipped unless ``force`` says
otherwise. A 400-page book whose PDF step fails does not re-translate.

*Inspectable.* Every boundary is a file a human can open, correct and feed back in.
Extraction gets headings wrong on complex layouts -- every tool does -- so the
translated Markdown being a real, editable artifact is not a nicety, it is how the
output becomes good.
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from kitab.figures import annotate
from kitab.ingest import extract
from kitab.md.ast import MarkdownDocument, restore_escaped_literals
from kitab.models import Document, Report, Segment
from kitab.render.epub_out import write_epub
from kitab.render.html import build_page
from kitab.render.pdf_out import write_pdf
from kitab.translate import get_translator
from kitab.translate.base import BaseTranslator
from kitab.translate.glossary import (
    build_glossary,
    load as load_glossary,
    save as save_glossary,
)

logger = logging.getLogger(__name__)


@dataclass
class Options:
    """Everything the pipeline can be told to do. One object, so the CLI, a future GUI
    and the tests all configure it the same way."""

    service: str = "google"
    model: str = ""
    lang_in: str = "auto"
    extractor: str = "auto"
    pages: str | None = None
    ocr: bool = False
    tier1: bool = True
    bilingual: bool = False
    glossary: bool = True
    glossary_min_count: int = 4
    protect_glossary_terms: bool = False
    epub: bool = True
    pdf: bool = False
    pdf_backend: str = "auto"
    page_size: str = "A5"
    split_level: int = 1
    extra_css: str | None = None
    #: Inline the bundled Noto Naskh Arabic into the HTML, EPUB and PDF.
    embed_fonts: bool = True
    #: Prepend a generated title heading. The book normally has its own.
    title_page: bool = False
    ignore_cache: bool = False
    force: bool = False
    api_key: str | None = None
    base_url: str | None = None
    #: Requests in flight. None uses the engine's own default.
    workers: int | None = None
    #: Requests started per second across all workers. None uses the engine's
    #: default; 0 disables the limiter entirely.
    qps: float | None = None


@dataclass
class Result:
    document: Document
    report: Report
    markdown_path: Path
    html_path: Path
    epub_path: Path | None = None
    pdf_path: Path | None = None


def translate_book(
    source: str | Path,
    out_dir: str | Path,
    work_dir: str | Path | None = None,
    options: Options | None = None,
) -> Result:
    options = options or Options()
    source = Path(source)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir) if work_dir else out_dir / ".kitab" / source.stem
    work.mkdir(parents=True, exist_ok=True)

    report = Report(
        input_path=str(source),
        service=options.service,
        model=options.model,
        lang_in=options.lang_in,
    )

    extract_dir = work / "01_extract"
    document_path = work / "02_document.json"
    translated_path = work / "03_translated.json"
    markdown_path = work / "04_translated.md"
    html_path = work / "05_book.html"
    glossary_path = work / "glossary.json"

    # ---- stages 1-3: ingest, and figure tiers -------------------------
    started = time.monotonic()
    if document_path.exists() and not options.force:
        document = Document.load(document_path)
        logger.info(
            "reusing %s (%d segments)", document_path.name, len(document.segments)
        )
        translator = _build_translator(options, document, glossary_path)
    else:
        extracted = extract(
            source,
            extract_dir,
            extractor=options.extractor,
            pages=options.pages,
            ocr=options.ocr,
        )
        lang_in = options.lang_in
        report.stages["extract"] = {
            "backend": extracted.backend,
            "kind": extracted.info.kind.value,
            "seconds": round(time.monotonic() - started, 1),
        }
        logger.info(
            "extracted %d characters of Markdown with the %s backend",
            len(extracted.markdown),
            extracted.backend,
        )

        markdown, figures = annotate(
            extracted.markdown, extract_dir, tier1=options.tier1
        )
        report.figures_tier0 = sum(1 for f in figures if f.tier == 0)
        report.figures_tier1 = sum(1 for f in figures if f.tier == 1)

        document = Document(
            title=str(extracted.meta.get("title") or source.stem),
            lang_in=lang_in,
            markdown=markdown,
            figures=figures,
            meta=extracted.meta,
        )
        (extract_dir / "document.md").write_text(markdown, encoding="utf-8")

        translator = _build_translator(options, document, glossary_path)

        parsed = MarkdownDocument(markdown)
        protected = list(translator.glossary) if options.protect_glossary_terms else []
        document.segments = parsed.build_segments(
            translator.mask_style, protected_terms=protected
        )
        document.save(document_path)
        logger.info("%d translatable segments", len(document.segments))

    report.figures_tier0 = sum(1 for f in document.figures if f.tier == 0)
    report.figures_tier1 = sum(1 for f in document.figures if f.tier == 1)
    report.segments_total = len(document.segments)

    # ---- stage 4: translate -------------------------------------------
    if translated_path.exists() and not options.force:
        document = Document.load(translated_path)
        logger.info("reusing %s", translated_path.name)
    else:
        started = time.monotonic()
        _translate_segments(document.segments, translator)
        document.save(translated_path)
        report.stages["translate"] = {
            "seconds": round(time.monotonic() - started, 1),
            "engine": str(translator),
            "workers": translator.workers,
            "qps": round(translator.limiter.qps, 2),
            "qps_configured": round(translator.limiter.base_qps, 2),
        }

    report.segments_translated = sum(
        1 for s in document.segments if s.status == "translated"
    )
    report.segments_cached = sum(1 for s in document.segments if s.status == "cached")
    report.segments_failed = sum(1 for s in document.segments if s.status == "failed")

    # ---- stage 5: rebuild ---------------------------------------------
    parsed = MarkdownDocument(document.markdown)
    parsed.build_segments(
        translator.mask_style,
        protected_terms=(
            list(translator.glossary) if options.protect_glossary_terms else []
        ),
    )
    problems = parsed.apply_translations(
        document.segments, translator.mask_style, bilingual=options.bilingual
    )
    for segment, missing, unexpected in problems:
        segment.status = "failed"
        segment.note = (
            f"placeholders missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )
        report.failures.append(
            {"id": segment.id, "kind": segment.kind, "reason": segment.note}
        )
    if problems:
        report.segments_failed += len(problems)
        report.warn(
            f"{len(problems)} segment(s) kept their source text because protected "
            f"content did not survive translation; see failures[]"
        )
        logger.warning(
            "%d segment(s) failed placeholder verification and were left untranslated",
            len(problems),
        )

    translated_markdown = restore_escaped_literals(
        parsed.to_markdown(),
        [lit for s in document.segments for lit in s.placeholders],
    )
    markdown_path.write_text(translated_markdown, encoding="utf-8")

    # The HTML references images as "images/<name>", relative to itself. They are
    # extracted into 01_extract/images/, so without this copy every figure in the
    # HTML and the PDF is a broken link -- the EPUB was fine because it packs its
    # own copy, which is exactly why the gap went unnoticed.
    _publish_images(extract_dir / "images", work / "images")

    html = build_page(
        translated_markdown,
        title=document.title,
        source_language=document.lang_in,
        extra_css=options.extra_css,
        embed_fonts=options.embed_fonts,
        show_title=options.title_page,
    )
    html_path.write_text(html, encoding="utf-8")

    # ---- stage 6: emit -------------------------------------------------
    result = Result(
        document=document,
        report=report,
        markdown_path=markdown_path,
        html_path=html_path,
    )

    stem = f"{source.stem}.ar"
    if options.epub:
        try:
            result.epub_path = write_epub(
                translated_markdown,
                out_dir / f"{stem}.epub",
                title=document.title,
                images_dir=extract_dir / "images",
                source_language=document.lang_in,
                split_level=options.split_level,
                extra_css=options.extra_css,
                embed_fonts=options.embed_fonts,
            )
        except Exception as e:
            report.warn(f"EPUB output failed: {e}")
            logger.error("EPUB output failed: %s", e)

    if options.pdf:
        try:
            result.pdf_path = write_pdf(
                html_path,
                out_dir / f"{stem}.pdf",
                backend=options.pdf_backend,
                page_size=options.page_size,
            )
        except Exception as e:
            report.warn(f"PDF output failed: {e}")
            logger.error("PDF output failed: %s", e)

    report.save(out_dir / f"{stem}.report.json")
    return result


# ---------------------------------------------------------------- helpers


def _publish_images(source: Path, target: Path) -> int:
    """Copy extracted images next to the rendered HTML. Returns how many."""
    if not source.is_dir():
        return 0
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for image in source.iterdir():
        if not image.is_file():
            continue
        destination = target / image.name
        if destination.exists() and destination.stat().st_size == image.stat().st_size:
            copied += 1
            continue
        shutil.copy2(image, destination)
        copied += 1
    return copied


def _build_translator(
    options: Options, document: Document, glossary_path: Path
) -> BaseTranslator:
    """Build the engine, and the glossary it will carry through the whole book."""
    kwargs = {}
    if options.api_key:
        kwargs["api_key"] = options.api_key
    if options.base_url:
        kwargs["base_url"] = options.base_url

    translator = get_translator(
        options.service,
        lang_in=document.lang_in,
        lang_out="ar",
        model=options.model,
        ignore_cache=options.ignore_cache,
        glossary=None,
        workers=options.workers,
        qps=options.qps,
        **kwargs,
    )

    if not options.glossary or not translator.supports_glossary:
        return translator

    glossary = load_glossary(glossary_path)
    if not glossary and document.markdown:
        logger.info("building the glossary (one pass over the whole book)")
        glossary = build_glossary(
            document.markdown, translator, min_count=options.glossary_min_count
        )
        save_glossary(glossary_path, glossary)
        logger.info("glossary: %d terms -> %s", len(glossary), glossary_path)
    translator.glossary = glossary
    translator.add_cache_impact_parameters("glossary", sorted(glossary.items()))
    return translator


def _translate_segments(segments: list[Segment], translator: BaseTranslator) -> None:
    """Translate every pending segment, in place, in document order.

    Order matters for more than tidiness: an engine batching adjacent paragraphs sees
    them in reading order, which is the only context it gets.
    """
    pending = [s for s in segments if not s.translated]
    if not pending:
        return

    sources = [s.source for s in pending]
    translations = translator.translate_many(sources)

    for segment, translation in zip(pending, translations):
        if translation and translation.strip():
            segment.translation = translation.strip()
            segment.status = "translated"
        else:
            segment.status = "failed"
            segment.note = "engine returned nothing"
