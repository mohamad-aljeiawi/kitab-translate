"""Stage 6b: PDF, printed from the same HTML the EPUB is built from.

The PDF is a *render* of the book, not a separate pipeline. Both backends shape Arabic
with HarfBuzz and run the Unicode bidirectional algorithm; neither needs anything from
us beyond correct HTML and CSS.

``chromium`` (Playwright)
    The best-tested Arabic text rendering available, and it handles web fonts, ligature
    edge cases and mixed-direction runs without fuss. ~500 MB installed.
``weasyprint``
    Pango and HarfBuzz, no browser. ~200 MB, and it honours the CSS Paged Media margin
    boxes in ``style_ar.css`` that Chromium ignores. Its native dependencies are
    awkward on Windows, which is why it is not the default.

If neither is installed the HTML is still written, and that is said plainly rather than
failing the run: the EPUB is the primary output and it does not depend on this stage.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from kitab.errors import MissingDependency

logger = logging.getLogger(__name__)

BACKENDS = ("auto", "chromium", "weasyprint")

# Current Chromium *does* honour the CSS Paged Media margin boxes in style_ar.css,
# so its own header/footer templates are left off. Enabling both printed the page
# number twice, stacked ("83" over "83") on every page.


def available_backend() -> str | None:
    if importlib.util.find_spec("playwright") is not None:
        return "chromium"
    if importlib.util.find_spec("weasyprint") is not None:
        return "weasyprint"
    return None


def write_pdf(
    html_path: Path, out_path: Path, backend: str = "auto", page_size: str = "A5"
) -> Path:
    if backend == "auto":
        resolved = available_backend()
        if resolved is None:
            raise MissingDependency("playwright", "pdf", "PDF output")
        backend = resolved

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if backend == "chromium":
        return _write_chromium(html_path, out_path, page_size)
    if backend == "weasyprint":
        return _write_weasyprint(html_path, out_path)
    raise ValueError(f"unknown PDF backend {backend!r}; choose from {BACKENDS}")


def _write_chromium(html_path: Path, out_path: Path, page_size: str) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise MissingDependency("playwright", "pdf", "Chromium PDF output") from e

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as e:
            raise RuntimeError(
                "Chromium is not installed for Playwright. Run:  playwright install chromium"
            ) from e
        try:
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(out_path),
                format=page_size,
                print_background=True,
                # No header/footer template and no margins here: both come from
                # @page in style_ar.css, which WeasyPrint honours identically.
                prefer_css_page_size=True,
            )
        finally:
            browser.close()
    logger.info("wrote %s via chromium", out_path)
    return out_path


def _write_weasyprint(html_path: Path, out_path: Path) -> Path:
    try:
        from weasyprint import HTML
    except ImportError as e:
        raise MissingDependency("weasyprint", "pdf", "WeasyPrint PDF output") from e

    HTML(filename=str(html_path)).write_pdf(str(out_path))
    logger.info("wrote %s via weasyprint", out_path)
    return out_path
