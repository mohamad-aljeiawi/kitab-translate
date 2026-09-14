"""Engine registry.

One place that knows every engine name. Adding a provider means adding a class and one
line here; nothing else in the pipeline learns about it.
"""

from __future__ import annotations

from .base import BaseTranslator
from .google import GoogleTranslator
from .openai_like import DeepSeekTranslator, OpenAILikeTranslator, OpenAITranslator

ENGINES: dict[str, type[BaseTranslator]] = {
    GoogleTranslator.name: GoogleTranslator,
    OpenAITranslator.name: OpenAITranslator,
    DeepSeekTranslator.name: DeepSeekTranslator,
    OpenAILikeTranslator.name: OpenAILikeTranslator,
}

#: Needs no key -- what ``kitab`` uses when nothing is configured.
DEFAULT_ENGINE = GoogleTranslator.name


def get_translator(
    service: str,
    lang_in: str,
    lang_out: str = "ar",
    model: str = "",
    ignore_cache: bool = False,
    glossary: dict[str, str] | None = None,
    workers: int | None = None,
    qps: float | None = None,
    **kwargs,
) -> BaseTranslator:
    """Build an engine by name."""
    try:
        cls = ENGINES[service.lower()]
    except KeyError:
        raise ValueError(
            f"unknown service {service!r}; available: {', '.join(sorted(ENGINES))}"
        ) from None
    return cls(
        lang_in=lang_in,
        lang_out=lang_out,
        model=model,
        ignore_cache=ignore_cache,
        glossary=glossary,
        workers=workers,
        qps=qps,
        **kwargs,
    )
