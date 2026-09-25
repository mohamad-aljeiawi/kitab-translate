"""Markdown as a document model.

The unit of translation is one markdown-it ``inline`` token -- the inline content of a
paragraph, heading, list item, table cell or blockquote line. Everything else in the
token stream (fences, HTML blocks, table structure, list markers, heading levels,
image nodes) is never handed to a translation engine, so an engine cannot damage it.

An inline token's ``.content`` is the *raw Markdown source* of that inline content.
That is what we mask and translate; the result is re-parsed with ``parseInline`` to
rebuild the token's children. So the round-trip is:

    source -> tokens -> [inline.content -> mask -> translate -> restore] -> tokens -> Markdown

Code fences and HTML blocks are block tokens with no inline children, so they are
skipped by construction rather than by a rule that could be forgotten.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

import mdformat_tables
from markdown_it import MarkdownIt
from mdformat.renderer import MDRenderer

from kitab.models import Segment

from . import mask as maskmod

# Block tokens whose inline content we label with a specific kind. Anything not
# listed falls back to "paragraph".
_KIND_BY_OPEN_TOKEN = {
    "heading_open": "heading",
    "th_open": "table_cell",
    "td_open": "table_cell",
    "blockquote_open": "blockquote",
    "list_item_open": "list_item",
}

# Inline content shorter than this and containing no letters is not worth a
# round-trip: page numbers, bullet glyphs, stray punctuation from an extractor.
_MIN_TRANSLATABLE = 1


def make_parser() -> MarkdownIt:
    """The one parser configuration used everywhere, so parse and render agree."""
    return MarkdownIt("commonmark").enable("table").enable("strikethrough")


class _Strikethrough:
    """mdformat plugin for the ``s`` token the parser above produces.

    mdformat renders CommonMark only; tables come from mdformat_tables and
    strikethrough from nowhere, so a single ``~~x~~`` in a book -- extractors turn
    a struck-out rule into ``~~-~~`` -- failed the rebuild with ``KeyError: 's'``
    after every segment had been translated. The markup is written back as read.
    """

    CHANGES_AST = False
    POSTPROCESSORS: dict = {}

    @staticmethod
    def update_mdit(mdit: MarkdownIt) -> None:
        mdit.enable("strikethrough")

    @staticmethod
    def _render(node, context) -> str:
        inner = "".join(child.render(context) for child in node.children)
        return f"{node.markup}{inner}{node.markup}"

    RENDERERS = {"s": _render}


#: Every mdformat plugin the renderer needs for what make_parser() can produce.
_RENDER_EXTENSIONS = [mdformat_tables, _Strikethrough]


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


class MarkdownDocument:
    """A parsed Markdown document that can be segmented, translated and re-rendered."""

    def __init__(self, source: str):
        self.md = make_parser()
        self.source = source
        self.tokens = self.md.parse(source)
        # segment id -> index into self._inline_tokens
        self._inline_tokens: list = []
        self._segment_index: dict[str, int] = {}

    # ---- segmentation --------------------------------------------------

    def build_segments(
        self,
        style: maskmod.MaskStyle,
        protected_terms: Iterable[str] = (),
        id_prefix: str = "s",
    ) -> list[Segment]:
        """Walk the token stream and produce one Segment per translatable inline node."""
        self._inline_tokens = []
        self._segment_index = {}
        segments: list[Segment] = []

        kind_stack: list[str] = []
        pending_kind: Optional[str] = None

        for token in self.tokens:
            if token.type in _KIND_BY_OPEN_TOKEN:
                pending_kind = _KIND_BY_OPEN_TOKEN[token.type]
                kind_stack.append(pending_kind)
                continue
            if token.type.endswith("_close") and kind_stack:
                opener = token.type[: -len("_close")] + "_open"
                if opener in _KIND_BY_OPEN_TOKEN:
                    kind_stack.pop()
                continue
            if token.type != "inline":
                continue

            raw = token.content
            if not raw.strip() or len(raw.strip()) < _MIN_TRANSLATABLE:
                continue
            if not _has_letters(raw):
                # Pure punctuation or digits: keep it, don't spend a request on it.
                continue

            kind = kind_stack[-1] if kind_stack else "paragraph"
            masked, literals = maskmod.mask_text(
                raw, style, protected_terms=protected_terms
            )
            if not _has_letters(style.pattern.sub("", masked)):
                # Everything in this node was protected -- nothing left to translate.
                continue

            sid = f"{id_prefix}{len(segments):05d}"
            segments.append(
                Segment(id=sid, kind=kind, source=masked, placeholders=literals)
            )
            self._segment_index[sid] = len(self._inline_tokens)
            self._inline_tokens.append(token)

        return segments

    # ---- writing back --------------------------------------------------

    def apply_translations(
        self,
        segments: Iterable[Segment],
        style: maskmod.MaskStyle,
        bilingual: bool = False,
    ):
        """Write restored translations back into the token stream.

        Returns a list of ``(segment, missing, unexpected)`` for segments whose
        placeholders did not round-trip. Those segments keep their source text --
        losing a formula is worse than leaving a paragraph untranslated.

        With ``bilingual``, the original is kept beneath each translated node inside an
        LTR span. It is the review surface: a reader who knows both languages can check
        a chapter without opening the source document beside it.
        """
        problems = []
        for segment in segments:
            index = self._segment_index.get(segment.id)
            if index is None:
                continue
            if not segment.translated or not segment.translation:
                continue

            restored, missing, unexpected = maskmod.restore_text(
                segment.translation, segment.placeholders, style
            )
            if missing or unexpected:
                problems.append((segment, missing, unexpected))
                continue

            if bilingual:
                original, _m, _u = maskmod.restore_text(
                    segment.source, segment.placeholders, style
                )
                restored = (
                    f'{restored}<br /><span class="kitab-orig" dir="ltr">'
                    f"{original}</span>"
                )

            token = self._inline_tokens[index]
            token.content = restored
            reparsed = self.md.parseInline(restored)
            token.children = reparsed[0].children if reparsed else []
        return problems

    # ---- output --------------------------------------------------------

    def to_markdown(self) -> str:
        return MDRenderer().render(
            self.tokens, {"parser_extension": _RENDER_EXTENSIONS}, {}
        )

    def to_html(self) -> str:
        return self.md.renderer.render(self.tokens, self.md.options, {})


def restore_escaped_literals(markdown: str, literals: Iterable[str]) -> str:
    """Undo the Markdown escaping applied to protected literals.

    A restored literal such as ``$O(n \\log n)$`` is plain text as far as Markdown is
    concerned, so the renderer escapes its backslash to ``\\\\log`` to guarantee a
    round-trip. That is valid Markdown and renders correctly, but the intermediate
    ``.md`` is meant to be read, hand-corrected and fed to other tools -- and doubled
    backslashes in LaTeX are exactly the kind of thing that survives into a published
    book. So each literal is put back verbatim.

    Only literals we masked ourselves are touched; ordinary prose keeps its escaping.
    """
    out = markdown
    for literal in sorted({lit for lit in literals if lit}, key=len, reverse=True):
        if literal in out:
            continue  # already verbatim
        pattern = "".join(
            (r"\\?" + re.escape(ch)) if _is_escapable(ch) else re.escape(ch)
            for ch in literal
        )
        out = re.sub(pattern, lambda _m, lit=literal: lit, out)
    return out


_ESCAPABLE = set("\\`*_{}[]()#+-.!<>|~\"'$&:;=?@^/,")


def _is_escapable(ch: str) -> bool:
    return ch in _ESCAPABLE


def render_html(markdown_source: str) -> str:
    """Render a Markdown string to an HTML fragment with the shared parser."""
    return make_parser().render(markdown_source)
