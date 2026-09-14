"""Figure handling: Tier 0 and Tier 1 only.

Tier 0
    Pass the image through untouched. Photographs, artwork, decorative rules.

Tier 1
    OCR the labels, translate them, and emit an Arabic **legend beneath the image**,
    keyed by coarse position. The image itself is never modified.

Tiers 2 and 3 -- re-rendering text inside the image by inpainting -- are deliberately
not implemented. A reader of a translated technical book does not need the diagram
redrawn; they need to know what its labels say. The legend delivers that for one OCR
pass per figure and it cannot corrupt the original artwork, which an inpainting
pipeline can and does.

The legend is injected into the Markdown *before* segmentation, so its text is
translated by the ordinary path with the ordinary glossary and the ordinary
placeholder checks. No second translation route exists.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from kitab.models import Figure

logger = logging.getLogger(__name__)

_IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$", re.MULTILINE)

#: Below these, a figure is Tier 0: one stray word is noise, not a label set.
MIN_LEGEND_LINES = 2
MIN_LEGEND_CHARS = 8

LEGEND_TITLE = "مفتاح الشكل"

_ARABIC_POSITION = {
    "top-left": "أعلى اليسار",
    "top-centre": "أعلى الوسط",
    "top-right": "أعلى اليمين",
    "middle-left": "الوسط الأيسر",
    "middle-centre": "الوسط",
    "middle-right": "الوسط الأيمن",
    "bottom-left": "أسفل اليسار",
    "bottom-centre": "أسفل الوسط",
    "bottom-right": "أسفل اليمين",
}


def find_images(markdown: str) -> list[tuple[str, str]]:
    """Every standalone image reference, as ``(alt, target)``."""
    return [(m.group(1), m.group(2)) for m in _IMAGE.finditer(markdown)]


def annotate(
    markdown: str,
    extract_dir: Path,
    tier1: bool = True,
    min_lines: int = MIN_LEGEND_LINES,
    min_chars: int = MIN_LEGEND_CHARS,
) -> tuple[str, list[Figure]]:
    """Classify figures and inject Tier-1 legends.

    Returns the annotated Markdown and the figure records. If OCR is unavailable this
    is a no-op that reports every figure as Tier 0 -- an uninstalled extra degrades the
    output, it does not fail the run.
    """
    references = find_images(markdown)
    if not references:
        return markdown, []

    engine_ready = False
    if tier1:
        from kitab.ingest import ocr as ocrmod

        engine_ready = ocrmod.available()
        if not engine_ready:
            logger.warning(
                "Tier-1 figure legends need the OCR extra "
                "(pip install 'kitab[ocr]'); every figure will be Tier 0."
            )

    figures: list[Figure] = []
    additions: dict[str, str] = {}

    for index, (_alt, target) in enumerate(references):
        figure = Figure(id=f"fig{index:04d}", path=target, tier=0)
        image_path = extract_dir / target
        if engine_ready and image_path.exists():
            entries = _read_labels(image_path)
            if (
                len(entries) >= min_lines
                and sum(len(e["text"]) for e in entries) >= min_chars
            ):
                figure.tier = 1
                figure.ocr_lines = entries
                additions[target] = _legend_markdown(entries)
        figures.append(figure)

    if additions:
        markdown = _inject(markdown, additions)
    tier1_count = sum(1 for f in figures if f.tier == 1)
    logger.info("figures: %d total, %d Tier-1", len(figures), tier1_count)
    return markdown, figures


def _read_labels(image_path: Path) -> list[dict]:
    from kitab.ingest import ocr as ocrmod

    try:
        import pymupdf

        with pymupdf.open(image_path) as doc:
            rect = doc[0].rect
            width, height = int(rect.width), int(rect.height)
    except Exception:
        width = height = 1000  # position labels degrade gracefully

    try:
        lines = ocrmod.ocr_image(image_path)
    except Exception as e:
        logger.debug("OCR failed on %s: %s", image_path.name, e)
        return []
    return ocrmod.describe(lines, width, height)


def _legend_markdown(entries: list[dict]) -> str:
    """A blockquote beneath the figure. Positions are already Arabic and fixed;
    only the label text goes to the translation engine."""
    lines = [f"> **{LEGEND_TITLE}**", ">"]
    for entry in entries:
        position = _ARABIC_POSITION.get(entry["pos"], entry["pos"])
        lines.append(f"> - {position}: {entry['text']}")
    return "\n".join(lines)


def _inject(markdown: str, additions: dict[str, str]) -> str:
    """Put each legend immediately after its image, once per occurrence."""

    def replace(match: re.Match) -> str:
        target = match.group(2)
        legend = additions.get(target)
        if not legend:
            return match.group(0)
        return f"{match.group(0).rstrip()}\n\n{legend}"

    return _IMAGE.sub(replace, markdown)
