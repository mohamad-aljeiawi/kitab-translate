"""EPUB (and bare HTML) to Markdown.

An EPUB already *is* a document model, so this is the cheapest path in the whole
pipeline -- no layout model, no OCR, no page reconstruction. Japanese light novels and
a good share of technical books arrive this way, and for them stages 2 and 3 do not run
at all.

Two Japanese details are handled here because they are lossy if left until later:

* ``<ruby>`` furigana is reduced to its base text. Keeping the reading would put a
  phonetic gloss into the translation input, where it only confuses the engine.
* ``<br/>`` inside a paragraph becomes a space rather than a hard break, because
  vertical-writing EPUBs use it for line control, not for meaning.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from kitab.errors import ExtractionError

logger = logging.getLogger(__name__)

_RUBY_RT = re.compile(r"<rt\b[^>]*>.*?</rt>", re.DOTALL | re.IGNORECASE)
_RUBY_RP = re.compile(r"<rp\b[^>]*>.*?</rp>", re.DOTALL | re.IGNORECASE)
_RUBY_TAGS = re.compile(r"</?(?:ruby|rb)\b[^>]*>", re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _to_markdown(html: str) -> str:
    from markdownify import markdownify

    html = _RUBY_RT.sub("", html)
    html = _RUBY_RP.sub("", html)
    html = _RUBY_TAGS.sub("", html)
    html = _BR.sub(" ", html)
    text = markdownify(html, heading_style="ATX", strip=["script", "style"])
    # markdownify leaves long runs of blank lines where the source had empty divs.
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_epub(path: Path, out_dir: Path) -> tuple[str, Path, dict]:
    """Returns ``(markdown, images_dir, metadata)``."""
    try:
        from ebooklib import ITEM_DOCUMENT, ITEM_IMAGE, epub
    except ImportError as e:  # pragma: no cover - EbookLib is a hard dependency
        raise ExtractionError("EbookLib is required to read EPUB files") from e

    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)

    book = epub.read_epub(str(path))

    # Save images under their base name so Markdown references stay flat.
    for item in book.get_items_of_type(ITEM_IMAGE):
        name = Path(item.get_name()).name
        try:
            (images_dir / name).write_bytes(item.get_content())
        except OSError as e:
            logger.debug("image %s skipped: %s", name, e)

    # Spine order is reading order; get_items() order is not.
    documents = {item.get_id(): item for item in book.get_items_of_type(ITEM_DOCUMENT)}
    chapters: list[str] = []
    for spine_id, _linear in book.spine:
        item = documents.get(spine_id)
        if item is None:
            continue
        html = item.get_content().decode("utf-8", errors="replace")
        markdown = _to_markdown(html)
        if markdown:
            chapters.append(markdown)

    if not chapters:  # a malformed spine: fall back to document order
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            markdown = _to_markdown(item.get_content().decode("utf-8", "replace"))
            if markdown:
                chapters.append(markdown)

    if not chapters:
        raise ExtractionError(f"{path.name}: no readable documents in the EPUB")

    markdown = _flatten_image_paths("\n\n".join(chapters))

    titles = book.get_metadata("DC", "title")
    languages = book.get_metadata("DC", "language")
    meta = {
        "title": titles[0][0] if titles else path.stem,
        "language": languages[0][0] if languages else "",
        "chapters": len(chapters),
    }
    return markdown, images_dir, meta


def extract_html(path: Path, out_dir: Path) -> tuple[str, Path, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)
    html = path.read_text(encoding="utf-8-sig", errors="replace")
    return _flatten_image_paths(_to_markdown(html)), images_dir, {"title": path.stem}


_IMAGE_LINK = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _flatten_image_paths(markdown: str) -> str:
    def fix(match: re.Match) -> str:
        alt, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "data:")):
            return match.group(0)
        return f"![{alt}](images/{Path(target).name})"

    return _IMAGE_LINK.sub(fix, markdown)
