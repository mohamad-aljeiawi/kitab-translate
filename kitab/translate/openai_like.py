"""OpenAI-compatible engines: OpenAI itself, DeepSeek, and any custom endpoint.

DeepSeek speaks the OpenAI protocol, so it is a subclass with a different base URL --
the same arrangement PDFMathTranslate uses, and the reason adding a fourth provider
later costs about ten lines.

Batching is a JSON array in, a JSON array out, with a hard length check. If the model
returns a different number of items the batch is discarded and the segments are retried
one at a time; a silently misaligned batch would shift every translation in the group
onto the wrong paragraph, which is the worst failure this pipeline can have.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Sequence

import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from kitab.errors import BatchShapeError
from kitab.md.mask import CURLY

from .base import ARABIC_SYSTEM_PROMPT, BaseTranslator

logger = logging.getLogger(__name__)

_LANG_NAMES = {
    "en": "English",
    "ja": "Japanese",
    "auto": "the source language",
}

# Reasoning models wrap their answer after a think block; strip it before parsing.
_THINK = re.compile(r"^<think>.*?</think>\s*", flags=re.DOTALL)
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", flags=re.DOTALL)


class OpenAITranslator(BaseTranslator):
    name = "openai"
    envs = {
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "OPENAI_API_KEY": None,
        "OPENAI_MODEL": "gpt-4o-mini",
    }
    mask_style = CURLY
    batch_size = 20
    max_batch_chars = 6000
    supports_glossary = True
    # 20 segments per request already amortises latency, so concurrency is about
    # keeping the pipe full rather than raw parallelism. Paid tiers differ wildly;
    # these are conservative and --workers/--qps override them.
    default_workers = 6
    default_qps = 6.0

    def __init__(
        self,
        lang_in: str,
        lang_out: str = "ar",
        model: str = "",
        base_url: str | None = None,
        api_key: str | None = None,
        envs: dict | None = None,
        ignore_cache: bool = False,
        glossary: dict[str, str] | None = None,
        temperature: float = 0.2,
        workers: int | None = None,
        qps: float | None = None,
    ):
        self.set_envs(envs)
        model = model or self.envs.get(self._model_env) or ""
        super().__init__(lang_in, lang_out, model, ignore_cache, glossary, workers, qps)

        key = api_key or self.envs.get(self._key_env)
        if not key:
            raise ValueError(
                f"{self.name}: no API key. Set {self._key_env} in the environment "
                f"or pass --api-key."
            )
        self.client = openai.OpenAI(
            base_url=base_url or self.envs.get("OPENAI_BASE_URL"), api_key=key
        )
        self.temperature = temperature

        # Anything that can change the output is part of the cache key.
        self.add_cache_impact_parameters("temperature", temperature)
        self.add_cache_impact_parameters("prompt_version", 1)
        self.add_cache_impact_parameters("glossary", sorted(self.glossary.items()))

    # Subclasses override these two to reuse the whole implementation.
    _key_env = "OPENAI_API_KEY"
    _model_env = "OPENAI_MODEL"

    # ---- prompts -------------------------------------------------------

    def _source_language(self) -> str:
        return _LANG_NAMES.get(self.lang_in, self.lang_in)

    def _single_messages(self, text: str) -> list[dict]:
        return [
            {"role": "system", "content": ARABIC_SYSTEM_PROMPT + self.glossary_block()},
            {
                "role": "user",
                "content": (
                    f"Translate this {self._source_language()} Markdown fragment into "
                    f"Arabic. Output the Arabic only.\n\n{text}"
                ),
            },
        ]

    def _batch_messages(self, texts: Sequence[str]) -> list[dict]:
        payload = json.dumps(list(texts), ensure_ascii=False)
        return [
            {"role": "system", "content": ARABIC_SYSTEM_PROMPT + self.glossary_block()},
            {
                "role": "user",
                "content": (
                    f"Translate each item of this JSON array from "
                    f"{self._source_language()} into Arabic.\n"
                    f"Return a JSON array of exactly {len(texts)} strings, in the same "
                    f"order, and nothing else. Do not merge, split, reorder or omit "
                    f"items. An item that needs no translation is returned unchanged.\n\n"
                    f"{payload}"
                ),
            },
        ]

    # ---- requests ------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(
            (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError)
        ),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        before_sleep=lambda state: logger.warning(
            "rate limited or unreachable; retry %d in %.0fs",
            state.attempt_number,
            state.next_action.sleep,
        ),
    )
    def _complete(self, messages: list[dict]) -> str:
        self.limiter.acquire()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
            )
        except openai.RateLimitError:
            # Back the shared rate off before tenacity sleeps, so the other workers
            # slow down too. Retrying alone only re-times the same collision.
            self.limiter.penalize("429 from the API")
            raise
        if not response.choices:
            raise ValueError(f"{self.name}: empty response")
        self.limiter.succeed()
        content = (response.choices[0].message.content or "").strip()
        return _THINK.sub("", content).strip()

    def do_translate(self, text: str) -> str:
        return self._complete(self._single_messages(text))

    def do_translate_batch(self, texts: Sequence[str]) -> list[str]:
        if len(texts) == 1:
            return [self.do_translate(texts[0])]
        raw = self._complete(self._batch_messages(texts))
        return self._parse_array(raw, len(texts))

    @staticmethod
    def _parse_array(raw: str, expected: int) -> list[str]:
        fenced = _FENCE.match(raw)
        if fenced:
            raw = fenced.group(1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise BatchShapeError(f"response was not JSON: {e}") from e
        if not isinstance(data, list):
            raise BatchShapeError(f"expected a JSON array, got {type(data).__name__}")
        if len(data) != expected:
            raise BatchShapeError(f"expected {expected} items, got {len(data)}")
        return [str(item) for item in data]


class DeepSeekTranslator(OpenAITranslator):
    name = "deepseek"
    envs = {
        "OPENAI_BASE_URL": "https://api.deepseek.com/v1",
        "DEEPSEEK_API_KEY": None,
        "DEEPSEEK_MODEL": "deepseek-chat",
    }
    _key_env = "DEEPSEEK_API_KEY"
    _model_env = "DEEPSEEK_MODEL"


class OpenAILikeTranslator(OpenAITranslator):
    """Any other OpenAI-compatible endpoint: Ollama, vLLM, OpenRouter, a gateway."""

    name = "openailiked"
    # A local model serves one request at a time; more workers only queue.
    default_workers = 2
    default_qps = 0.0  # no limit: it is your own hardware
    envs = {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY": "none",
        "OPENAI_MODEL": "qwen2.5:7b",
    }
    batch_size = 8  # smaller models hold a long array together less reliably
