"""``kitab --check``: does each optional part actually work here?

Each part is exercised, not just imported: OCR reads a rendered line of text, and
the fast extractor converts a PDF that holds a picture, from a folder whose name
has spaces and Arabic in it. Every fault the packaged app has shipped with so far
-- a model file left out of the bundle, a folder name the extractor mangled --
fails here, which is why the release workflow runs it on each build before
anything is published.

A part that is not installed is reported and does not fail the check; a part
that is installed and broken does.
"""

from __future__ import annotations

import importlib.util
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Result:
    name: str
    status: str  # ok | missing | failed
    detail: str = ""


def _sample_pdf(folder: Path, name: str) -> Path:
    """A one-page PDF with a heading, a paragraph and a picture."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter One", fontsize=18)
    for i in range(6):
        page.insert_text((72, 110 + 16 * i), "Antibodies bind antigens.", fontsize=11)
    picture = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 120), False)
    picture.set_rect(picture.irect, (200, 60, 60))
    page.insert_image(pymupdf.Rect(72, 250, 272, 370), pixmap=picture)
    path = folder / name
    doc.save(path)
    return path


def check_ocr() -> Result:
    from kitab.ingest.ocr import available, ocr_image

    if not available():
        return Result("OCR", "missing", "install kitab[ocr]")
    try:
        import pymupdf

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            doc = pymupdf.open()
            page = doc.new_page(width=420, height=80)
            page.insert_text((20, 50), "Serology and Immunology", fontsize=24)
            image = Path(tmp) / "line.png"
            page.get_pixmap(dpi=150).save(image)
            lines = ocr_image(image)
        text = " ".join(line.text for line in lines)
        if "Immun" not in text:
            return Result("OCR", "failed", f"read {text!r}")
        return Result("OCR", "ok", text)
    except Exception as e:
        return Result("OCR", "failed", f"{type(e).__name__}: {e}")


def check_fast_extractor() -> Result:
    if importlib.util.find_spec("pymupdf4llm") is None:
        return Result("Fast PDF extractor", "missing", "install kitab[fast]")
    try:
        from kitab.ingest.pdf import extract_pdf

        # ignore_cleanup_errors: on Windows a file that a failed step still holds
        # open cannot be deleted, and that PermissionError would hide the reason.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            folder = Path(tmp) / "My Books (check) علم"
            folder.mkdir()
            pdf = _sample_pdf(folder, "sample book.pdf")
            out = folder / "work dir"
            result = extract_pdf(pdf, out, backend="fast")
            images = list((out / "images").glob("*"))
        if "Chapter" not in result.markdown:
            return Result("Fast PDF extractor", "failed", "no text came out")
        if not images:
            return Result("Fast PDF extractor", "failed", "the picture was not saved")
        return Result("Fast PDF extractor", "ok", f"{len(images)} picture(s)")
    except Exception as e:
        return Result("Fast PDF extractor", "failed", f"{type(e).__name__}: {e}")


def check_pdf_output() -> Result:
    from kitab.render.pdf_out import available_backend, system_browser

    backend = available_backend()
    if backend is None:
        return Result("PDF output", "missing", "install kitab[pdf]")
    if backend == "chromium":
        browser = system_browser()
        if browser is None:
            return Result(
                "PDF output", "missing", "no Edge, Chrome or Chromium installed"
            )
        return Result("PDF output", "ok", browser)
    return Result("PDF output", "ok", backend)


def run_checks() -> list[Result]:
    return [check_ocr(), check_fast_extractor(), check_pdf_output()]
