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
import os
import shutil
import sys
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


# Chromium-family browsers Playwright can drive through ``executable_path``. The
# desktop build ships Playwright's driver but not its 150 MB browser download, so it
# prints with whichever of these the machine already has -- Edge on every Windows 11,
# and usually Chrome or Chromium on Linux.
_BROWSER_COMMANDS = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "microsoft-edge",
    "microsoft-edge-stable",
    "brave-browser",
    "brave",
    "msedge",
    "chrome",
)
_WINDOWS_BROWSERS = (
    r"Microsoft\Edge\Application\msedge.exe",
    r"Google\Chrome\Application\chrome.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
)


def system_browser() -> str | None:
    """Path to an installed Chromium-family browser, or None."""
    for name in _BROWSER_COMMANDS:
        found = shutil.which(name)
        if found:
            return found
    if sys.platform == "win32":
        roots = [
            os.environ.get(var)
            for var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")
        ]
        for root in filter(None, roots):
            for relative in _WINDOWS_BROWSERS:
                candidate = Path(root) / relative
                if candidate.is_file():
                    return str(candidate)
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
            executable = system_browser()
            if executable is None:
                raise RuntimeError(
                    "No Chromium browser found. Install Chrome, Chromium or Edge, "
                    "or run:  playwright install chromium"
                ) from e
            logger.info("printing with %s", executable)
            browser = playwright.chromium.launch(executable_path=executable)
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
