"""Names the pages show for engines, languages, levels and stages."""

from __future__ import annotations

from kitab.translate.openai_like import REASONING_EFFORTS

from .i18n import tr

#: In the order the Translate page offers them: free first.
ENGINES_SHOWN = ("google", "openai", "deepseek", "openailiked")

INPUT_SUFFIXES = (".pdf", ".epub", ".md", ".markdown", ".txt", ".html", ".htm")

SOURCE_LANGUAGES = ("auto", "en", "ja")


def engine_label(name: str) -> str:
    return tr(f"engine.{name}") if name in ENGINES_SHOWN else name


def engine_items() -> list[tuple[str, str]]:
    return [(name, engine_label(name)) for name in ENGINES_SHOWN]


def thinking_items() -> list[tuple[str, str]]:
    """ "" first: send nothing, the model decides."""
    return [("", tr("thinking.default"))] + [
        (level, tr(f"thinking.{level}")) for level in REASONING_EFFORTS
    ]


def source_items() -> list[tuple[str, str]]:
    return [(code, tr(f"source.{code}")) for code in SOURCE_LANGUAGES]


def stage_label(stage: str) -> str:
    key = f"stage.{stage}"
    try:
        return tr(key)
    except KeyError:
        return stage.capitalize()
