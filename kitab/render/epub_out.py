"""Stage 6a: EPUB.

EPUB is the primary artifact, not a consolation prize. Arabic reflows; a fixed page
does not, and the whole reason for the Markdown route is that we stopped trying to fit
Arabic into someone else's page box.

Two settings decide whether an Arabic EPUB opens correctly, and general-purpose
translation tools routinely miss both:

* ``page-progression-direction="rtl"`` on the spine -- pages turn the right way;
* ``dir="rtl"`` and ``lang="ar"`` on every XHTML document -- text runs the right way.

Get either wrong and the book opens backwards, which is the single most visible defect
in a translated Arabic ebook.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from kitab.render.html import load_css, markdown_to_fragment, split_chapters

logger = logging.getLogger(__name__)

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      lang="ar" xml:lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="style.css" />
</head>
<body dir="rtl">
{body}
</body>
</html>
"""


def write_epub(
    markdown: str,
    out_path: Path,
    title: str,
    images_dir: Path | None = None,
    source_language: str = "",
    split_level: int = 1,
    extra_css: str | Path | None = None,
    identifier: str | None = None,
    embed_fonts: bool = True,
) -> Path:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(identifier or f"urn:uuid:{uuid.uuid4()}")
    book.set_title(title)
    book.set_language("ar")
    book.add_metadata("DC", "contributor", "kitab")
    if source_language:
        book.add_metadata("DC", "source", source_language)

    # Pages turn right-to-left. Without this the reader treats the book as LTR.
    book.set_direction("rtl")

    style = epub.EpubItem(
        uid="style",
        file_name="style.css",
        media_type="text/css",
        content=load_css(extra_css, embed_fonts=embed_fonts).encode("utf-8"),
    )
    book.add_item(style)

    used_images = _collect_images(markdown)
    if images_dir:
        for name in sorted(used_images):
            source = Path(images_dir) / Path(name).name
            if not source.exists():
                logger.warning("image referenced but missing: %s", name)
                continue
            book.add_item(
                epub.EpubItem(
                    uid=f"img_{Path(name).stem}",
                    file_name=f"images/{Path(name).name}",
                    media_type=_MIME.get(source.suffix.lower(), "image/png"),
                    content=source.read_bytes(),
                )
            )

    chapters = split_chapters(markdown, level=split_level)
    items = []
    for index, (chapter_title, chapter_md) in enumerate(chapters):
        name = chapter_title or f"{title} - {index + 1}"
        item = epub.EpubHtml(
            title=name,
            file_name=f"ch{index:04d}.xhtml",
            lang="ar",
            uid=f"ch{index:04d}",
            direction="rtl",
        )
        item.set_content(
            _XHTML.format(
                title=_escape(name), body=markdown_to_fragment(chapter_md)
            ).encode("utf-8")
        )
        item.add_item(style)
        book.add_item(item)
        items.append(item)

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
    logger.info(
        "wrote %s (%d chapters, %d images)", out_path, len(items), len(used_images)
    )
    return out_path


_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def _collect_images(markdown: str) -> set[str]:
    return {
        target
        for target in _IMAGE.findall(markdown)
        if not target.startswith(("http://", "https://", "data:"))
    }


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
