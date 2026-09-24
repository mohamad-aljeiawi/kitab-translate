"""Progress reporting and cooperative cancellation.

The pipeline announces what it is doing through three calls -- :func:`stage`,
:func:`advance` and :func:`check` -- and does not know who, if anyone, is listening.
With nothing installed every call is a no-op, so the CLI and the tests pay nothing.

The GUI runs each book in its own process and installs a sink that forwards events to
the window, plus a cancel test backed by a shared event. That is why the hook is
process-global rather than threaded through every signature: one process is one job,
and the translator's worker threads have to reach it too, which a context variable
would not.

Cancellation is cooperative. :func:`check` raises :class:`~kitab.errors.Cancelled` at
points where stopping leaves the work directory consistent -- between OCR pages,
between translation batches, between stages -- so a cancelled book resumes from where
it stopped instead of from scratch.
"""

from __future__ import annotations

import threading
from typing import Callable

from kitab.errors import Cancelled

#: ``sink(stage, done, total)``. ``total == 0`` means the amount of work is unknown.
Sink = Callable[[str, int, int], None]

_sink: Sink | None = None
_cancelled: Callable[[], bool] | None = None
_lock = threading.Lock()
_stage = ""
_done = 0
_total = 0


def install(sink: Sink | None = None, cancelled: Callable[[], bool] | None = None):
    """Route progress to ``sink`` and consult ``cancelled`` in :func:`check`."""
    global _sink, _cancelled
    _sink = sink
    _cancelled = cancelled


def stage(name: str, total: int = 0) -> None:
    """A new stage starts. Also a cancellation point."""
    global _stage, _done, _total
    check()
    with _lock:
        _stage, _done, _total = name, 0, total
    _emit(name, 0, total)


def advance(step: int = 1, total: int | None = None) -> None:
    """``step`` more units of the current stage are done. Safe from any thread."""
    global _done, _total
    with _lock:
        _done += step
        if total is not None:
            _total = total
        name, done, total_now = _stage, _done, _total
    _emit(name, done, total_now)


def check() -> None:
    """Raise :class:`Cancelled` if the job has been asked to stop."""
    if _cancelled is not None and _cancelled():
        raise Cancelled("cancelled")


def _emit(name: str, done: int, total: int) -> None:
    if _sink is not None:
        _sink(name, done, total)
