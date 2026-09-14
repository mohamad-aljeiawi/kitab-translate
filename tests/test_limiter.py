"""Rate limiting and concurrency.

The contract that matters most is boring and easy to break: results come back in the
order they were asked for, whatever order the workers finish in.
"""

import threading
import time

import pytest

from kitab.md.mask import CURLY
from kitab.translate.base import BaseTranslator
from kitab.translate.limiter import RateLimiter


class SlowTranslator(BaseTranslator):
    """Sleeps, so concurrency is observable. Records the threads it ran on."""

    name = "slow"
    mask_style = CURLY
    batch_size = 1
    default_workers = 4
    default_qps = 0.0  # limiter off; this test is about the pool

    def __init__(self, *args, delay=0.05, **kwargs):
        kwargs.pop("glossary", None)
        super().__init__(*args, glossary={}, **kwargs)
        self.delay = delay
        self.threads = set()
        self._lock = threading.Lock()

    def do_translate(self, text: str) -> str:
        time.sleep(self.delay)
        with self._lock:
            self.threads.add(threading.get_ident())
        return "AR " + text


def test_token_bucket_paces_requests():
    limiter = RateLimiter(qps=20, burst=1)
    started = time.monotonic()
    for _ in range(5):
        limiter.acquire()
    elapsed = time.monotonic() - started
    # 5 tokens at 20/s with a burst of 1 is ~0.2s. Generous bounds: this asserts that
    # pacing happens at all, not that the clock is precise.
    assert 0.1 < elapsed < 1.0


def test_disabled_limiter_never_waits():
    limiter = RateLimiter(qps=0)
    assert not limiter.enabled
    started = time.monotonic()
    for _ in range(100):
        limiter.acquire()
    assert time.monotonic() - started < 0.1


def test_penalize_halves_the_rate_with_a_floor():
    limiter = RateLimiter(qps=8)
    limiter.penalize()
    assert limiter.qps == pytest.approx(4.0)
    for _ in range(20):
        limiter.penalize()
    assert limiter.qps == pytest.approx(8 * RateLimiter.MIN_FRACTION)


def test_recovery_needs_sustained_success():
    limiter = RateLimiter(qps=8)
    limiter.penalize()
    for _ in range(RateLimiter.RECOVERY_SUCCESSES - 1):
        limiter.succeed()
    assert limiter.qps == pytest.approx(4.0)  # not yet
    limiter.succeed()
    assert limiter.qps > 4.0
    # and never past the configured ceiling
    for _ in range(1000):
        limiter.succeed()
    assert limiter.qps == pytest.approx(8.0)


def test_limiter_is_thread_safe():
    limiter = RateLimiter(qps=200, burst=10)
    taken = []
    lock = threading.Lock()

    def worker():
        for _ in range(20):
            limiter.acquire()
            with lock:
                taken.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(taken) == 160


def test_results_keep_request_order_under_concurrency():
    """The one that would ruin a book: completion order must not become text order."""
    translator = SlowTranslator("en", ignore_cache=True, workers=4)
    sources = [f"segment {i}" for i in range(24)]
    out = translator.translate_many(sources)
    assert out == ["AR " + s for s in sources]


def test_pool_actually_runs_in_parallel():
    translator = SlowTranslator("en", ignore_cache=True, workers=4, delay=0.05)
    sources = [f"segment {i}" for i in range(16)]

    started = time.monotonic()
    translator.translate_many(sources)
    elapsed = time.monotonic() - started

    assert len(translator.threads) > 1, "no concurrency: everything ran on one thread"
    # 16 x 50ms is 0.8s sequential; four workers should land well under that.
    assert elapsed < 0.6


def test_single_worker_stays_sequential():
    translator = SlowTranslator("en", ignore_cache=True, workers=1, delay=0.01)
    out = translator.translate_many([f"s{i}" for i in range(5)])
    assert len(translator.threads) == 1
    assert out == [f"AR s{i}" for i in range(5)]


def test_engine_defaults_are_sane():
    from kitab.translate.google import GoogleTranslator
    from kitab.translate.openai_like import OpenAITranslator

    assert GoogleTranslator.default_qps > 0, "the free endpoint must stay limited"
    assert GoogleTranslator.default_workers >= 2
    assert OpenAITranslator.default_qps > 0
