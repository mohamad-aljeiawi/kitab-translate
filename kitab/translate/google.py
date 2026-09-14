"""The free Google Translate web endpoint.

Carried over from PDFMathTranslate's ``GoogleTranslator``: same endpoint, same
result-container scrape. It needs no key and no account, which makes it the honest
default for someone trying the tool before deciding whether to pay for anything.

Its limits are real and are treated as limits rather than papered over:

* One segment per request, 5000 characters -- there is no batch API here, so all
  throughput comes from concurrency plus the shared rate limiter.
* It is an unofficial endpoint. It rate-limits, and it can start returning nothing at
  all. Requests are therefore throttled by default and failures are reported, never
  silently replaced with the source text.
* It does not follow instructions, so it gets ``[[0]]`` placeholders rather than
  ``{{v0}}`` -- braces come back mangled from statistical MT often enough to matter --
  and the pipeline verifies every placeholder afterwards.

For a whole book, use an LLM engine. This one is for samples, short works and trying
the pipeline out.
"""

from __future__ import annotations

import html
import logging
import re
import threading
from typing import Sequence

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from kitab.md.mask import SQUARE

from .base import BaseTranslator, remove_control_characters

logger = logging.getLogger(__name__)

_RESULT = re.compile(r'(?s)class="(?:t0|result-container)">(.*?)<')
_MAX_CHARS = 5000


class GoogleTranslator(BaseTranslator):
    name = "google"
    # Google's own codes for the languages we accept.
    lang_map = {"auto": "auto", "en": "en", "ja": "ja", "ar": "ar"}
    mask_style = SQUARE
    batch_size = 1
    max_batch_chars = _MAX_CHARS
    supports_glossary = False

    # One segment per request means throughput comes entirely from concurrency.
    # Measured against the live endpoint: 151 segments at 8 workers / 10 req/s
    # completed in 15s with no 429 and no backoff, against 77s strictly sequential.
    # These defaults sit just under that, and the AIMD limiter is what makes being
    # this forward safe -- a 429 halves the rate for everyone and it climbs back.
    # If you do get blocked, --qps 3 --workers 3 is the cautious setting.
    default_workers = 8
    default_qps = 8.0

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
        super().__init__(
            lang_in, lang_out, model or "web", ignore_cache, glossary, workers, qps
        )
        self.endpoint = "https://translate.google.com/m"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        }
        # A Session is not documented as thread-safe, and its connection pool is
        # shared mutable state. One per worker thread costs nothing and removes the
        # question entirely.
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    @retry(
        retry=retry_if_exception_type((requests.RequestException, ValueError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        before_sleep=lambda state: logger.warning(
            "google endpoint unhappy; retry %d in %.0fs",
            state.attempt_number,
            state.next_action.sleep,
        ),
    )
    def do_translate(self, text: str) -> str:
        if len(text) > _MAX_CHARS:
            # Splitting here would break placeholder accounting; the segmenter should
            # never hand us anything this long. Say so rather than truncate silently.
            raise ValueError(
                f"segment of {len(text)} characters exceeds the "
                f"{_MAX_CHARS}-character limit of the free Google endpoint"
            )
        self.limiter.acquire()
        response = self.session.get(
            self.endpoint,
            params={"tl": self.lang_out, "sl": self.lang_in, "q": text},
            headers=self.headers,
            timeout=30,
        )
        # 429 is the explicit signal; 403 and 503 are how this endpoint says "slow
        # down" once it decides you look like a robot. All three back the rate off.
        if response.status_code in (429, 403, 503):
            self.limiter.penalize(f"HTTP {response.status_code}")
        response.raise_for_status()

        found = _RESULT.findall(response.text)
        if not found:
            # The other way it throttles: a 200 carrying nothing. Treat that as
            # pushback rather than only as a parse failure.
            self.limiter.penalize("empty response")
            raise ValueError(
                "no result container in response (endpoint changed, or throttling)"
            )
        self.limiter.succeed()
        return remove_control_characters(html.unescape(found[0]))

    def do_translate_batch(self, texts: Sequence[str]) -> list[str]:
        return [self.do_translate(t) for t in texts]
