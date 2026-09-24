"""Translator interface.

Carried over from PDFMathTranslate's ``pdf2zh.translator`` -- the env/config handling,
the cache-key discipline and the retry decorators are the parts of that codebase worth
keeping. Two things are new:

* **A batch contract.** ``translate_many`` is the primary entry point. Engines that can
  translate several segments in one request implement ``do_translate_batch``; the base
  implementation falls back to a loop, so a single-string engine like the free Google
  endpoint needs no extra code.
* **A mask style per engine.** Placeholders that survive an LLM are not the ones that
  survive statistical MT, so the engine declares which it wants and the masking layer
  follows it.

Target language is Arabic and only Arabic. That is a product decision, not a
limitation to route around: the prompt can then be specific about register, script
direction and numerals instead of being generic.
"""

from __future__ import annotations

import copy
import logging
import os
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Sequence

from kitab import progress
from kitab.cache import TranslationCache
from kitab.config import ConfigManager
from kitab.md.mask import CURLY, MaskStyle

from .limiter import RateLimiter

logger = logging.getLogger(__name__)


def remove_control_characters(s: str) -> str:
    return "".join(ch for ch in s if unicodedata.category(ch)[0] != "C" or ch in "\n\t")


# The instruction every LLM engine shares. Kept in one place so a prompt change is a
# one-line diff and -- because it is part of the cache key -- automatically invalidates
# stale rows.
ARABIC_SYSTEM_PROMPT = (
    "You are a professional literary and technical translator working into Modern "
    "Standard Arabic (فصحى معاصرة).\n"
    "Rules:\n"
    "1. Translate the meaning, not the words. Arabic has its own syntax; do not "
    "mirror English or Japanese sentence structure.\n"
    "2. Preserve every placeholder of the form {{vN}} exactly as written, once each. "
    "They stand for formulas, code, links and numbers. Never translate, renumber, "
    "merge or drop them. You may move a placeholder if Arabic word order requires it.\n"
    "3. Keep Markdown emphasis markers (*, **) around the corresponding Arabic words.\n"
    "4. Keep Western digits (0-9). Do not convert to Arabic-Indic numerals.\n"
    "5. Keep technical terms consistent. Where a glossary is given, use it exactly.\n"
    "6. Output the translation only. No notes, no explanations, no quotation marks "
    "you did not receive, no restating of the source."
)


class BaseTranslator:
    """Common behaviour: language mapping, env/config, caching, batching."""

    name = "base"
    envs: dict = {}
    lang_map: dict[str, str] = {}
    mask_style: MaskStyle = CURLY
    #: How many segments this engine accepts in one request.
    batch_size = 1
    #: Soft cap on characters per request, whatever ``batch_size`` says.
    max_batch_chars = 6000
    supports_glossary = False
    #: Requests in flight. Concurrency and rate are separate knobs on purpose.
    default_workers = 4
    #: Requests started per second, across all workers. 0 disables the limiter.
    default_qps = 4.0

    def __init__(
        self,
        lang_in: str,
        lang_out: str = "ar",
        model: str = "",
        ignore_cache: bool = False,
        glossary: dict[str, str] | None = None,
        workers: int | None = None,
        qps: float | None = None,
    ):
        self.lang_in = self.lang_map.get(lang_in.lower(), lang_in)
        self.lang_out = self.lang_map.get(lang_out.lower(), lang_out)
        self.model = model
        self.ignore_cache = ignore_cache
        self.glossary = glossary or {}

        self.workers = max(
            1, int(workers if workers is not None else self.default_workers)
        )
        self.limiter = RateLimiter(
            qps if qps is not None else self.default_qps, name=self.name
        )

        self.cache = TranslationCache(
            self.name,
            {
                "lang_in": self.lang_in,
                "lang_out": self.lang_out,
                "model": model,
            },
        )

    # ---- configuration -------------------------------------------------

    def set_envs(self, envs: dict | None) -> None:
        """Resolve engine settings: class defaults < stored config < environment < argument."""
        self.envs = copy.copy(self.envs)
        stored = ConfigManager.get_translator_by_name(self.name)
        if stored:
            self.envs.update(stored)
        changed = False
        for key in list(self.envs):
            if key in os.environ:
                self.envs[key] = os.environ[key]
                changed = True
        if envs:
            self.envs.update(envs)
            changed = True
        if changed:
            ConfigManager.set_translator_by_name(self.name, self.envs)

    def add_cache_impact_parameters(self, key: str, value) -> None:
        """Register a parameter that changes output, so cached rows stay honest."""
        self.cache.add_params(key, value)

    # ---- translation ---------------------------------------------------

    def translate(self, text: str, ignore_cache: bool = False) -> str:
        """Translate one string, through the cache."""
        if not (self.ignore_cache or ignore_cache):
            hit = self.cache.get(text)
            if hit is not None:
                return hit
        result = self.do_translate(text)
        self.cache.set(text, result)
        return result

    def translate_many(
        self, texts: Sequence[str], ignore_cache: bool = False
    ) -> list[str]:
        """Translate a list of strings, preserving order and length.

        Cache hits are served without a request; the misses are grouped into batches
        and the batches run across ``self.workers`` threads, paced by ``self.limiter``.

        Results are placed by index, never by completion order -- with a worker pool
        that distinction is the difference between a translated book and a shuffled one.
        """
        results: list[str | None] = [None] * len(texts)
        pending: list[int] = []

        for i, text in enumerate(texts):
            if not (self.ignore_cache or ignore_cache):
                hit = self.cache.get(text)
                if hit is not None:
                    results[i] = hit
                    continue
            pending.append(i)

        if len(pending) < len(texts):
            progress.advance(len(texts) - len(pending))
        groups = list(self._group(pending, texts))
        if not groups:
            return [r if r is not None else "" for r in results]

        if self.workers <= 1 or len(groups) == 1:
            for group in groups:
                self._run_group(group, texts, results)
        else:
            with ThreadPoolExecutor(
                max_workers=self.workers, thread_name_prefix=f"kitab-{self.name}"
            ) as pool:
                futures = [
                    pool.submit(self._run_group, group, texts, results)
                    for group in groups
                ]
                try:
                    for future in as_completed(futures):
                        # _run_group raises only on cancellation or a genuine bug in
                        # it; both should stop the run rather than lose a chapter.
                        future.result()
                except BaseException:
                    pool.shutdown(wait=True, cancel_futures=True)
                    raise

        return [r if r is not None else "" for r in results]

    def _run_group(
        self, group: list[int], texts: Sequence[str], results: list[str | None]
    ) -> None:
        """Translate one batch and write it into ``results`` at its own indices.

        Writing into a preallocated list from several threads is safe here: each group
        owns a disjoint set of indices, and CPython list item assignment is atomic.
        """
        # A cancelled job stops between batches: every finished batch is already in
        # the cache, so the resumed run starts where this one stopped.
        progress.check()
        sources = [texts[i] for i in group]
        try:
            translations = self.do_translate_batch(sources)
        except Exception as e:
            logger.warning(
                "%s: batch of %d failed (%s); retrying one at a time",
                self.name,
                len(group),
                e,
            )
            translations = None

        if translations is None or len(translations) != len(sources):
            if translations is not None:
                logger.warning(
                    "%s: expected %d segments back, got %d; retrying one at a time",
                    self.name,
                    len(sources),
                    len(translations),
                )
            translations = []
            for source in sources:
                try:
                    translations.append(self.do_translate(source))
                except Exception as e:
                    logger.error("%s: segment failed: %s", self.name, e)
                    translations.append("")

        for index, source, translation in zip(group, sources, translations):
            results[index] = translation
            if translation:
                self.cache.set(source, translation)
        progress.advance(len(group))

    def _group(self, indices: list[int], texts: Sequence[str]) -> Iterable[list[int]]:
        """Split pending indices into request-sized batches."""
        batch: list[int] = []
        chars = 0
        for i in indices:
            size = len(texts[i])
            too_many = len(batch) >= self.batch_size
            too_long = batch and chars + size > self.max_batch_chars
            if too_many or too_long:
                yield batch
                batch, chars = [], 0
            batch.append(i)
            chars += size
        if batch:
            yield batch

    # ---- engine hooks --------------------------------------------------

    def do_translate(self, text: str) -> str:
        """Translate a single string. Engines must implement this."""
        raise NotImplementedError

    def do_translate_batch(self, texts: Sequence[str]) -> list[str]:
        """Translate several strings in one request.

        The default loops over :meth:`do_translate`, which is correct for engines
        without a batch API. It must return exactly ``len(texts)`` items.
        """
        return [self.do_translate(t) for t in texts]

    def glossary_block(self, limit: int = 60) -> str:
        """The glossary as prompt text, or an empty string."""
        if not self.glossary:
            return ""
        pairs = list(self.glossary.items())[:limit]
        lines = "\n".join(f"- {src} = {dst}" for src, dst in pairs)
        return "\nUse exactly these translations for these terms:\n" + lines + "\n"

    def __str__(self) -> str:
        return f"{self.name} {self.lang_in}->{self.lang_out} {self.model}"
