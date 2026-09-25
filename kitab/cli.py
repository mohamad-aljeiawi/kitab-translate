"""Command line interface.

    kitab book.pdf                       # -> book.ar.epub, using free Google
    kitab book.epub --service deepseek   # -> book.ar.epub, better quality
    kitab book.pdf --pdf --bilingual     # -> EPUB + PDF, original kept for review
    kitab book.pdf --inspect             # what is this file, and what will it need?

One direction only: English or Japanese in, Arabic out. There is no ``--to`` flag, and
that is the product decision the whole design rests on.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from kitab import __version__
from kitab.errors import KitabError
from kitab.ingest.classify import classify
from kitab.pipeline import Options, translate_book
from kitab.translate.openai_like import REASONING_EFFORTS
from kitab.translate.registry import DEFAULT_ENGINE, ENGINES


def _add_translate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "input", type=Path, nargs="?", help="PDF, EPUB, HTML, Markdown or text"
    )
    parser.add_argument(
        "-o", "--out", type=Path, default=Path("out"), help="output directory"
    )
    parser.add_argument("--work", type=Path, default=None, help="work directory")

    engine = parser.add_argument_group("engine")
    engine.add_argument(
        "-s",
        "--service",
        default=DEFAULT_ENGINE,
        choices=sorted(ENGINES),
        help=f"translation engine (default: {DEFAULT_ENGINE}, needs no key)",
    )
    engine.add_argument("-m", "--model", default="", help="model name for LLM engines")
    engine.add_argument("--api-key", default=None, help="override the configured key")
    engine.add_argument("--base-url", default=None, help="override the endpoint")
    engine.add_argument(
        "-r",
        "--reasoning",
        dest="reasoning_effort",
        default=None,
        choices=REASONING_EFFORTS,
        help="reasoning effort for reasoning models (openai, openailiked); the model "
        "decides which levels it accepts. Default: the model's own",
    )
    engine.add_argument(
        "--workers",
        type=int,
        default=None,
        help="requests in flight (default: per engine, 4 for google)",
    )
    engine.add_argument(
        "--qps",
        type=float,
        default=None,
        help="requests started per second across all workers; 0 disables the limit",
    )
    engine.add_argument(
        "-f",
        "--from",
        dest="lang_in",
        default="auto",
        choices=["auto", "en", "ja"],
        help="source language (default: auto)",
    )

    ingest = parser.add_argument_group("ingest")
    ingest.add_argument(
        "--extractor",
        default="auto",
        choices=["auto", "marker", "fast", "builtin"],
        help="PDF to Markdown backend",
    )
    ingest.add_argument("--pages", default=None, help='page range, e.g. "1-20,35"')
    ingest.add_argument(
        "--ocr",
        action="store_true",
        help="force OCR (used automatically on scanned PDFs when kitab[ocr] is "
        "installed)",
    )
    ingest.add_argument(
        "--no-tier1",
        dest="tier1",
        action="store_false",
        help="do not OCR figures for Arabic legends",
    )

    quality = parser.add_argument_group("quality")
    quality.add_argument(
        "--bilingual",
        action="store_true",
        help="keep the original beneath each translated block, for review",
    )
    quality.add_argument(
        "--no-glossary",
        dest="glossary",
        action="store_false",
        help="skip the termbase pass",
    )
    quality.add_argument(
        "--protect-terms",
        dest="protect_glossary_terms",
        action="store_true",
        help="mask glossary terms so they are never translated inline",
    )
    quality.add_argument(
        "--ignore-cache", action="store_true", help="re-translate everything"
    )
    quality.add_argument(
        "--force", action="store_true", help="re-run every stage, ignoring work files"
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "--no-epub", dest="epub", action="store_false", help="skip the EPUB"
    )
    output.add_argument("--pdf", action="store_true", help="also print a PDF")
    output.add_argument(
        "--pdf-backend", default="auto", choices=["auto", "chromium", "weasyprint"]
    )
    output.add_argument("--page-size", default="A5")
    output.add_argument(
        "--title-page",
        action="store_true",
        help="prepend a generated title heading (the book usually has its own)",
    )
    output.add_argument(
        "--split-level",
        type=int,
        default=1,
        help="heading level that starts a new EPUB chapter (default: 1)",
    )
    output.add_argument("--css", default=None, help="extra stylesheet, file or literal")
    output.add_argument(
        "--no-embed-fonts",
        dest="embed_fonts",
        action="store_false",
        help="do not embed Noto Naskh Arabic; use installed fonts only",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kitab",
        description="Translate English and Japanese books into Arabic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"kitab {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")

    # Flags rather than subcommands, so "kitab book.pdf" is the whole interface for
    # the common case and nothing has to be remembered to use it.
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="classify the input, report what it will need, and stop",
    )
    parser.add_argument(
        "--engines", action="store_true", help="list translation engines and exit"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check that OCR, the fast PDF extractor and PDF output work here",
    )
    _add_translate_arguments(parser)
    return parser


def _options(args: argparse.Namespace) -> Options:
    return Options(
        service=args.service,
        model=args.model,
        lang_in=args.lang_in,
        extractor=args.extractor,
        pages=args.pages,
        ocr=args.ocr,
        tier1=args.tier1,
        bilingual=args.bilingual,
        glossary=args.glossary,
        protect_glossary_terms=args.protect_glossary_terms,
        epub=args.epub,
        pdf=args.pdf,
        pdf_backend=args.pdf_backend,
        page_size=args.page_size,
        split_level=args.split_level,
        extra_css=args.css,
        embed_fonts=args.embed_fonts,
        title_page=args.title_page,
        ignore_cache=args.ignore_cache,
        force=args.force,
        api_key=args.api_key,
        base_url=args.base_url,
        workers=args.workers,
        qps=args.qps,
        reasoning_effort=args.reasoning_effort,
    )


def _run_inspect(path: Path) -> int:
    info = classify(path)
    print(f"file      {info.path}")
    print(f"kind      {info.kind.value}")
    if info.pages:
        print(f"pages     {info.pages}")
        print(f"text      {info.chars_per_page:.0f} characters per page (sampled)")
    print(f"title     {info.title}")
    if info.needs_ocr:
        print()
        from kitab.ingest.ocr import available as ocr_available

        if ocr_available():
            print("This looks scanned; kitab will OCR it, find its figures and")
            print("read their labels into Arabic legends.")
        else:
            print("This looks scanned. Translating it needs the OCR extra:")
            print("    pip install 'kitab[ocr]'")
        print("Expect seconds per page rather than a whole book in a minute.")
    return 0


def _run_check() -> int:
    from kitab.check import run_checks

    results = run_checks()
    marks = {"ok": "ok     ", "missing": "missing", "failed": "FAILED "}
    for result in results:
        print(f"{marks[result.status]}  {result.name:<20} {result.detail}")
    # Missing parts are optional; a part that is there but broken is a failure.
    return 1 if any(r.status == "failed" for r in results) else 0


def _run_engines() -> int:
    for name in sorted(ENGINES):
        cls = ENGINES[name]
        keys = ", ".join(k for k in cls.envs if "KEY" in k) or "no key required"
        default = " (default)" if name == DEFAULT_ENGINE else ""
        print(f"{name:<14}{keys}{default}")
    return 0


def _safe_output() -> None:
    """Never let printing a book's name end the program.

    Output piped on Windows is encoded as cp1252, which has no Arabic letters, so
    printing "علم المناعة.pdf" raised UnicodeEncodeError. Characters the stream
    cannot encode are replaced instead; a UTF-8 terminal still shows them all.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _safe_output()
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=(
            logging.DEBUG
            if args.verbose
            else (logging.WARNING if args.quiet else logging.INFO)
        ),
        format="%(levelname)s %(name)s: %(message)s" if args.verbose else "%(message)s",
    )

    if args.engines:
        return _run_engines()
    if args.check:
        return _run_check()
    if args.input is None:
        parser.print_help()
        return 2
    if args.inspect:
        return _run_inspect(args.input)

    try:
        result = translate_book(
            args.input, args.out, work_dir=args.work, options=_options(args)
        )
    except KitabError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    report = result.report
    print()
    print(
        f"segments   {report.segments_total} total, "
        f"{report.segments_translated} translated, "
        f"{report.segments_cached} cached, "
        f"{report.segments_failed} failed"
    )
    print(
        f"figures    {report.figures_tier0} passed through, "
        f"{report.figures_tier1} with an Arabic legend"
    )
    print(f"markdown   {result.markdown_path}")
    print(f"html       {result.html_path}")
    if result.epub_path:
        print(f"epub       {result.epub_path}")
    if result.pdf_path:
        print(f"pdf        {result.pdf_path}")
    for warning in report.warnings:
        print(f"warning    {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
