"""Termbase.

Consistency across a whole book is what separates a usable technical translation from
an unusable one, and chunk-by-chunk translation cannot produce it: the same term
becomes three different Arabic words in three chapters, and the reader cannot tell they
are the same thing.

So: one pass over the whole document collects candidate terms, they are translated
once, and the result is injected into every later request. The glossary is written to
the work directory as plain JSON so it can be corrected by hand -- which is the point.
A translator who fixes twenty terms before the main run fixes them everywhere.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from .base import BaseTranslator

# A capitalised word or run of them: "Kalman Filter", "Bayesian". Deliberately narrow;
# a noisy glossary is worse than a small one because every entry is forced on the model.
_CANDIDATE = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}(?:\s+[A-Z][a-zA-Z0-9]{2,}){0,3}\b")

# Words that start sentences and mean nothing as terms.
_STOPWORDS = {
    "The",
    "This",
    "That",
    "These",
    "Those",
    "There",
    "Then",
    "They",
    "Their",
    "When",
    "Where",
    "What",
    "Which",
    "While",
    "With",
    "Without",
    "Here",
    "For",
    "From",
    "But",
    "And",
    "Not",
    "You",
    "Your",
    "One",
    "Two",
    "Three",
    "First",
    "Second",
    "Third",
    "Next",
    "Last",
    "Chapter",
    "Section",
    "Figure",
    "Table",
    "Note",
    "Example",
    "Exercise",
    "Part",
    "Page",
    "See",
    "Its",
    "It",
    "If",
    "In",
    "On",
    "At",
    "As",
    "An",
    "A",
    "Is",
    "Are",
    "Was",
    "Were",
    "Be",
    "Can",
    "May",
    "Must",
    "Should",
    "Would",
    "Could",
    "We",
    "Our",
    "He",
    "She",
}


def extract_candidates(markdown: str, min_count: int = 4, limit: int = 80) -> list[str]:
    """Terms worth pinning down, most frequent first.

    ``min_count`` is what keeps this useful: a term that appears once does not create
    an inconsistency, so it does not belong in the glossary.
    """
    # Strip fenced code -- identifiers there are protected by masking anyway.
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)

    counts: Counter[str] = Counter()
    for match in _CANDIDATE.finditer(text):
        term = match.group(0).strip()
        if term in _STOPWORDS:
            continue
        head = term.split()[0]
        if len(term.split()) == 1 and head in _STOPWORDS:
            continue
        counts[term] += 1

    return [
        term for term, count in counts.most_common(limit * 3) if count >= min_count
    ][:limit]


def build_glossary(
    markdown: str,
    translator: BaseTranslator,
    min_count: int = 4,
    limit: int = 80,
) -> dict[str, str]:
    """Translate the candidate terms once. Returns ``{source term: Arabic}``."""
    terms = extract_candidates(markdown, min_count=min_count, limit=limit)
    if not terms:
        return {}
    translations = translator.translate_many(terms)
    return {
        term: arabic.strip()
        for term, arabic in zip(terms, translations)
        if arabic and arabic.strip() and arabic.strip() != term
    }


def load(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save(path: Path, glossary: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(glossary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def merge(base: dict[str, str], overrides: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Hand-written entries always win over generated ones."""
    merged = dict(base)
    merged.update(dict(overrides))
    return merged
