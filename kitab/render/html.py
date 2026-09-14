"""Stage 5: Markdown to Arabic HTML.

This is the step where the bidi problem stops being ours. We emit semantic HTML with
``dir="rtl"`` and hand it to a rendering engine that already implements UAX #9 and
HarfBuzz shaping. No embedding levels, no level-run/font-run intersection, no
direction-aware pen placement.

Two post-processing passes on the rendered fragment earn their keep:

* wide tables get a scroll container, so a table never forces the page sideways;
* the Tier-1 figure legend gets a class, so it can be styled apart from an ordinary
  blockquote.
"""

from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path

from jinja2 import Template

from kitab import __version__
from kitab.md.ast import render_html

ASSETS = Path(__file__).parent / "assets"
FONTS = ASSETS / "fonts"

# Noto Naskh Arabic, SIL Open Font License 1.1. Bundled rather than linked.
#
# Linking Google Fonts looked like the obvious answer and is actively wrong here:
# Google serves WOFF2, Chromium cannot embed WOFF2 into a PDF, so it rasterises
# every glyph into a Type 3 font. The page *looks* right and the text underneath
# is destroyed -- extraction came back as "عمدا ةفار غ تترك ةالص ف ح ه ذه"
# instead of "هذه الصفحة تركت فارغة عمدا". Unsearchable, uncopyable, and invisible
# unless you check. A real TTF inlined as a data: URI embeds properly, works
# offline, and keeps the text layer intact.
_FONT_FACES = (
    ("Noto Naskh Arabic", 400, "NotoNaskhArabic-Regular.ttf"),
    ("Noto Naskh Arabic", 700, "NotoNaskhArabic-Bold.ttf"),
)


@lru_cache(maxsize=1)
def font_face_css() -> str:
    """@font-face rules with the TTFs inlined, or "" if the fonts are not bundled."""
    rules = []
    for family, weight, filename in _FONT_FACES:
        path = FONTS / filename
        if not path.exists():
            continue
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        rules.append(
            "@font-face {\n"
            f"  font-family: '{family}';\n"
            f"  font-weight: {weight};\n"
            "  font-style: normal;\n"
            "  font-display: swap;\n"
            f"  src: url(data:font/ttf;base64,{encoded}) format('truetype');\n"
            "}"
        )
    return "\n".join(rules)


def load_css(extra_css: str | Path | None = None, embed_fonts: bool = True) -> str:
    css = (ASSETS / "style_ar.css").read_text(encoding="utf-8")
    if embed_fonts:
        faces = font_face_css()
        if faces:
            css = faces + "\n\n" + css
    if extra_css:
        path = Path(extra_css)
        if path.exists():
            css += "\n\n/* --- user stylesheet --- */\n" + path.read_text(
                encoding="utf-8"
            )
        else:
            css += "\n\n/* --- user stylesheet --- */\n" + str(extra_css)
    return css


def markdown_to_fragment(markdown: str, isolate_latin: bool = True) -> str:
    """Markdown to an HTML body fragment, with the RTL-specific fixups applied."""
    html = render_html(markdown)
    if isolate_latin:
        html = isolate_ltr_runs(html)
    html = _wrap_tables(html)
    html = _tag_figure_keys(html)
    html = _group_chapter_openings(html)
    return html


# A run of Latin script: letters, and any digits/punctuation/spaces *between* them.
# It must start and end on a letter or digit, so the sentence-final full stop after
# an English phrase is left outside the run.
_LTR_RUN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9À-ɏ@#$%^&*_+=/\\|~`'\"()\[\]{}<>.,:;!?‐-― -]*"
    r"[A-Za-z0-9)\]}])?"
)
_HAS_LATIN = re.compile(r"[A-Za-z]")

# Tags *and* character references. An entity has to be atomic here: "&quot;" is
# ampersand followed by the letters "quot", so a naive Latin-run match wraps the
# letters and leaves the ampersand outside -- "&<bdi>quot;</bdi>" -- which the browser
# then renders as the literal text &quot;. That is how HTML entities started leaking
# into the Arabic.
_TAG = re.compile(
    r"(<[^>]+>|&[A-Za-z][A-Za-z0-9]{1,30};|&#[0-9]{1,7};|&#[xX][0-9A-Fa-f]{1,6};)"
)
_TAG_NAME = re.compile(r"<(/?)\s*([A-Za-z][A-Za-z0-9]*)")
_ALREADY_ISOLATED = {"code", "pre", "kbd", "samp"}


def isolate_ltr_runs(html: str) -> str:
    """Wrap Latin runs in ``<bdi>`` so neutral characters resolve to the paragraph.

    The rendering engine implements UAX #9 correctly, and correct is not the same as
    right here. In an Arabic paragraph ending "... London EC1N 8TS." the final full
    stop is a *neutral* character sitting between an LTR run and the end of the
    paragraph, so the algorithm attaches it to the Latin run and it appears on the
    wrong side: ".Saffron House, 6-10 Kirby Street, London EC1N 8TS".

    Wrapping the Latin span in ``<bdi>`` isolates it, so the neutrals on either side
    take the paragraph's direction and the stop lands where an Arabic reader expects
    it. This is the one place where handing everything to the browser is not enough:
    the browser cannot know which run the punctuation belongs to, and in a translated
    technical book -- full of identifiers, URLs and product names -- it is on almost
    every page.

    Runs are wrapped only outside tags, so attribute values and URLs are untouched.
    """
    out: list[str] = []
    depth = 0  # inside <code>/<pre>/<kbd>/<samp>, which the stylesheet already isolates
    for part in _TAG.split(html):
        if not part:
            continue
        if part.startswith("&"):  # a character reference: pass through intact
            out.append(part)
            continue
        if part.startswith("<"):
            name = _TAG_NAME.match(part)
            if name and name.group(2).lower() in _ALREADY_ISOLATED:
                depth += -1 if name.group(1) else 1
                depth = max(depth, 0)
            out.append(part)
            continue
        if depth:
            out.append(part)
            continue
        out.append(
            _LTR_RUN.sub(
                lambda m: (
                    f"<bdi>{m.group(0)}</bdi>"
                    if _HAS_LATIN.search(m.group(0))
                    else m.group(0)
                ),
                part,
            )
        )
    return "".join(out)


def build_page(
    markdown: str,
    title: str,
    source_language: str = "",
    extra_css: str | Path | None = None,
    show_title: bool = False,
    embed_fonts: bool = True,
) -> str:
    """A complete RTL HTML document.

    ``show_title`` prepends an <h1> built from the file name. Off by default: a
    real book already opens with its own title page, and a synthetic heading made
    from something like "preview-9781292153414_A37747456" pushes the actual first
    page down and reads as a defect.

    ``embed_fonts`` inlines the bundled Noto Naskh Arabic. On by default: almost no
    machine has a Naskh face installed, and without it a 300-page book is set in a
    UI typeface. Pass ``False`` to use only fonts installed on the system.
    """
    template = Template(
        (ASSETS / "template.html.j2").read_text(encoding="utf-8"),
        keep_trailing_newline=True,
    )
    return template.render(
        title=title,
        css=load_css(extra_css, embed_fonts=embed_fonts),
        body=markdown_to_fragment(markdown),
        source_language=source_language,
        show_title=show_title,
        generator=f"kitab {__version__}",
    )


# A run of consecutive headings with nothing between them: a "Walk 3" label above the
# chapter title, a subtitle under it. Together they open a chapter.
_HEADING_RUN = re.compile(
    r"(?:<h[1-6]>.*?</h[1-6]>\s*){1,4}", re.DOTALL | re.IGNORECASE
)
_HAS_H1 = re.compile(r"<h1[ >]", re.IGNORECASE)


def _group_chapter_openings(html: str) -> str:
    """Wrap each run of consecutive headings containing an <h1> in .chapter-open.

    The new-page break for a chapter then applies to the whole opening. Applied to the
    <h1> alone it falls *between* a "Walk 3" label and the title beneath it, leaving
    the label stranded by itself on an otherwise empty page.
    """

    def wrap(match: re.Match) -> str:
        run = match.group(0)
        if not _HAS_H1.search(run):
            return run
        return f'<div class="chapter-open">{run.rstrip()}</div>\n'

    return _HEADING_RUN.sub(wrap, html)


_TABLE = re.compile(r"(<table\b.*?</table>)", re.DOTALL | re.IGNORECASE)


def _wrap_tables(html: str) -> str:
    return _TABLE.sub(r'<div class="table-wrap">\1</div>', html)


_FIGURE_KEY = re.compile(
    r"<blockquote>\s*(<p>\s*<strong>مفتاح الشكل</strong>)", re.IGNORECASE
)


def _tag_figure_keys(html: str) -> str:
    return _FIGURE_KEY.sub(r'<blockquote class="figure-key">\1', html)


def split_chapters(markdown: str, level: int = 1) -> list[tuple[str, str]]:
    """Split Markdown at headings of ``level`` into ``(title, markdown)`` chunks.

    EPUB readers page and cache per document; a single 400-page XHTML file makes a
    reader stutter and breaks its progress tracking. Splitting at chapter headings is
    what makes the output behave like a real book.
    """
    marker = "#" * level
    pattern = re.compile(rf"^{re.escape(marker)} +(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(markdown))
    if not matches:
        return [("", markdown)]

    chunks: list[tuple[str, str]] = []
    preamble = markdown[: matches[0].start()].strip()
    if preamble:
        chunks.append(("", preamble))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        chunks.append((match.group(1).strip(), markdown[match.start() : end].strip()))
    return chunks
