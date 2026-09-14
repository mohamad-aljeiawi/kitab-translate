"""Rate limiting.

PDFMathTranslate's approach is a fixed-size thread pool plus
``@retry(wait=wait_fixed(1))`` on the worker: hit the endpoint with N threads and,
when it pushes back, keep asking every second until it relents. There is no limiter --
the retry *is* the limiter. Its GUI also passes the thread count as ``qps``, which
conflates two different things: four workers is not four requests per second, it is
"as fast as four threads can go", which on a fast endpoint is far more.

That works, in the sense that a run eventually finishes. It also means the only signal
that you are going too fast is a stream of 429s, and with `wait_fixed(1)` and no
`stop=`, a permanently failing segment retries forever and the book never completes.

This module separates the two concerns:

* **How many requests are in flight** -- the worker pool, in ``BaseTranslator``.
* **How often a request may start** -- a token bucket, here, shared by every worker.

and adds the piece neither has: the rate **responds** to what the server says. On a
429 the rate is halved; sustained success walks it back up toward the configured
ceiling. That is AIMD, the same control law TCP uses, and it is what lets an unofficial
endpoint like the free Google one be driven near its real limit without discovering
that limit as a wall of failures.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """A thread-safe token bucket with additive-increase / multiplicative-decrease.

    ``qps <= 0`` disables limiting entirely and every call returns immediately.
    """

    #: Never drop below this fraction of the configured rate, however many 429s arrive.
    MIN_FRACTION = 0.1
    #: Multiplier applied on a rate-limit response.
    BACKOFF = 0.5
    #: Successes required before the rate is allowed to step back up.
    RECOVERY_SUCCESSES = 20
    #: Fraction of the base rate added per recovery step.
    RECOVERY_STEP = 0.25

    def __init__(self, qps: float, burst: float | None = None, name: str = ""):
        self.name = name
        self.base_qps = max(float(qps), 0.0)
        self.qps = self.base_qps
        # A burst of 1 means strict spacing. Allowing a small burst lets a pool of
        # workers start together without each one sleeping through the first interval.
        self.burst = (
            float(burst) if burst is not None else max(1.0, min(self.base_qps, 4.0))
        )
        self._tokens = self.burst
        self._updated = time.monotonic()
        self._successes = 0
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.base_qps > 0

    def acquire(self, tokens: float = 1.0) -> float:
        """Block until ``tokens`` are available. Returns how long it waited."""
        if not self.enabled:
            return 0.0

        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.burst, self._tokens + (now - self._updated) * self.qps
                )
                self._updated = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                # How long until the bucket holds enough.
                delay = (tokens - self._tokens) / self.qps
            # Sleep outside the lock so other workers can keep draining the bucket.
            time.sleep(min(delay, 5.0))
            waited += min(delay, 5.0)

    def penalize(self, reason: str = "rate limited") -> None:
        """The server pushed back. Halve the rate."""
        if not self.enabled:
            return
        with self._lock:
            floor = self.base_qps * self.MIN_FRACTION
            previous = self.qps
            self.qps = max(floor, self.qps * self.BACKOFF)
            self._successes = 0
        if self.qps < previous:
            logger.warning(
                "%s: %s -- reducing rate %.2f -> %.2f req/s",
                self.name or "limiter",
                reason,
                previous,
                self.qps,
            )

    def succeed(self) -> None:
        """A request came back cleanly. Walk the rate back up, slowly."""
        if not self.enabled or self.qps >= self.base_qps:
            return
        with self._lock:
            self._successes += 1
            if self._successes < self.RECOVERY_SUCCESSES:
                return
            self._successes = 0
            previous = self.qps
            self.qps = min(self.base_qps, self.qps + self.base_qps * self.RECOVERY_STEP)
        logger.info(
            "%s: recovering rate %.2f -> %.2f req/s",
            self.name or "limiter",
            previous,
            self.qps,
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        if not self.enabled:
            return f"RateLimiter({self.name}, disabled)"
        return f"RateLimiter({self.name}, {self.qps:.2f}/{self.base_qps:.2f} req/s)"
