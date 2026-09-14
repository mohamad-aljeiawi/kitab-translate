"""Placeholder protection.

Two layers, in this order:

1. *Markdown* masking protects constructs that must survive byte-exact: code spans,
   image references, link destinations, footnote references, raw HTML.
2. *Lexical* masking protects what is ordinary text as far as Markdown is concerned
   but must still survive verbatim: maths, URLs, section and figure numbers, code-like
   identifiers, and glossary terms marked do-not-translate.

Both run as a single left-to-right alternation, so nothing inside an already-emitted
placeholder can be masked a second time.

The placeholder syntax belongs to the translation engine, because engines differ in
what they leave alone. ``{{v0}}`` survives an instruction-following LLM; the free
Google endpoint is happier with ``[[0]]``. Restoration is deliberately tolerant --
engines insert spaces and reorder -- but it never guesses: an id that appears zero or
twice is a hard failure, reported per segment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# Markdown constructs that must survive byte-exact. These come first in the
# alternation. Emphasis markers are deliberately NOT here: "*word*" is safe to hand to
# an engine, and masking it would strip the emphasis from the translated word.
_MARKDOWN_PATTERNS: list[tuple[str, str]] = [
    ("code_span", r"`+[^`\n]*`+"),
    ("image", r"!\[[^\]\n]*\]\([^)\n]*\)"),
    ("footnote_ref", r"\[\^[^\]\n]{1,60}\]"),
    # Link destination only -- "[text]" stays outside the mask and gets translated.
    ("link_dest", r"\]\([^)\n]*\)"),
    ("ref_link", r"\]\[[^\]\n]*\]"),
    ("autolink", r"<(?:https?://|mailto:)[^>\s]+>"),
    ("html_tag", r"</?[A-Za-z][^>\n]{0,200}>"),
]

# Order matters: display maths before inline maths, longest constructs first.
_LEXICAL_PATTERNS: list[tuple[str, str]] = [
    ("math_display", r"\$\$.+?\$\$"),
    ("math_bracket", r"\\\[.+?\\\]"),
    ("math_paren", r"\\\(.+?\\\)"),
    # $...$ but not "$5 and $10": no space after the opener, no $ inside.
    ("math_inline", r"\$(?!\s)[^$\n]{1,200}?(?<!\s)\$"),
    ("url", r"\b(?:https?://|www\.)[^\s<>)\]]+"),
    ("email", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    # 3.2.1 / 1.4 -- section, figure and table numbers. Plain integers are left
    # alone: they are ordinary prose and an engine reordering them is harmless.
    ("section_no", r"\b\d+(?:\.\d+){1,4}\b"),
    # Appendix and figure numbers that begin with a letter: D.1, A.2.3. Unprotected,
    # the letter is translated ("D" -> "د") and the token then renders reversed as
    # "1.د", because an Arabic letter followed by a digit resolves that way under
    # UAX #9. Keeping the whole token Latin keeps it readable and correctly ordered.
    ("lettered_no", r"\b[A-Z]\.\d+(?:\.\d+){0,3}\b"),
    # Identifiers that are obviously code even outside a code span.
    ("snake_case", r"\b[a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+){1,}\b"),
    # Complexity and function notation written as prose: O(1), O(n log n), Θ(n), f(x).
    # A single capital immediately followed by a parenthesis is never a word, and
    # engines happily translate "O(n)" into Arabic if allowed to. No space before the
    # bracket, so "Figure (a)" is left alone.
    ("notation", r"\b[A-Za-zΘΩΛ]\([^)\n]{1,20}\)"),
]


@dataclass
class MaskStyle:
    """How one engine wants its placeholders written."""

    template: str  # must contain "{i}"
    pattern: re.Pattern  # must capture the id as group 1

    def render(self, index: int) -> str:
        return self.template.format(i=index)


# LLMs follow an instruction about a token like this and leave it intact.
CURLY = MaskStyle(
    template="{{{{v{i}}}}}",
    pattern=re.compile(r"\{\{\s*[vV]?\s*(\d{1,4})\s*\}\}"),
)
# Statistical MT engines mangle braces; square brackets survive better.
SQUARE = MaskStyle(
    template="[[{i}]]",
    pattern=re.compile(r"\[\[\s*(\d{1,4})\s*\]\]"),
)


def _combined_pattern(protected_terms: Iterable[str] = ()) -> re.Pattern:
    """One alternation over every rule, so masking is a single left-to-right pass.

    Running the rules one after another would let a later rule match *inside* a
    placeholder emitted by an earlier one. Alternation tries branches in order at each
    position, which gives the same precedence without that hazard.
    """
    rules = list(_MARKDOWN_PATTERNS) + list(_LEXICAL_PATTERNS)
    terms = sorted(
        {t for t in protected_terms if t and t.strip()}, key=len, reverse=True
    )
    if terms:
        alternatives = "|".join(re.escape(t) for t in terms)
        rules.insert(0, ("glossary", r"(?<!\w)(?:%s)(?!\w)" % alternatives))
    return re.compile("|".join(f"(?P<{n}>{b})" for n, b in rules), re.DOTALL)


def mask_text(
    text: str,
    style: MaskStyle,
    start_index: int = 0,
    protected_terms: Iterable[str] = (),
) -> tuple[str, list[str]]:
    """Replace protected spans with placeholders.

    Returns the masked text and the original literals, positionally indexed from
    ``start_index``.
    """
    literals: list[str] = []
    pattern = _combined_pattern(protected_terms)

    def substitute(match: re.Match) -> str:
        literals.append(match.group(0))
        return style.render(start_index + len(literals) - 1)

    return pattern.sub(substitute, text), literals


def find_ids(text: str, style: MaskStyle) -> list[int]:
    """Every placeholder id present, in order of appearance, duplicates included."""
    return [int(m.group(1)) for m in style.pattern.finditer(text)]


def restore_text(
    text: str, literals: list[str], style: MaskStyle
) -> tuple[str, set[int], set[int]]:
    """Put the originals back.

    Returns ``(restored, missing, unexpected)``. ``missing`` are ids the engine
    dropped; ``unexpected`` are ids it invented or duplicated. Both empty means the
    segment round-tripped cleanly.
    """
    expected = set(range(len(literals)))
    seen: list[int] = []

    def substitute(match: re.Match) -> str:
        index = int(match.group(1))
        seen.append(index)
        if 0 <= index < len(literals):
            return literals[index]
        return match.group(0)  # leave an invented id visible rather than guessing

    restored = style.pattern.sub(substitute, text)
    seen_set = set(seen)
    duplicated = {i for i in seen_set if seen.count(i) > 1}
    return restored, expected - seen_set, (seen_set - expected) | duplicated


def verify(
    text: str, literals: list[str], style: MaskStyle
) -> tuple[set[int], set[int]]:
    """Check placeholders without keeping the rebuilt string."""
    _restored, missing, unexpected = restore_text(text, literals, style)
    return missing, unexpected
