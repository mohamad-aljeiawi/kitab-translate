"""The job queue: which books are waiting, which are running, and what they say.

Jobs start in submission order, at most ``max_parallel`` at a time. Each running job
is a :func:`kitab.gui.worker.run_job` process; a timer on the GUI thread drains the
shared event queue, so every signal this object emits arrives on the GUI thread and
widgets can be updated directly from it.

Cancelling asks first -- the job stops at its next safe point and keeps its work
files -- and only terminates the process if it has not stopped after a grace period.
"""

from __future__ import annotations

import enum
import itertools
import multiprocessing
import queue
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from . import worker
from .paths import work_dir_for

#: Seconds a job has to stop by itself after Cancel before it is terminated.
CANCEL_GRACE = 20.0
#: Log lines kept per job.
LOG_LINES = 2000


class State(enum.Enum):
    QUEUED = "Queued"
    RUNNING = "Running"
    CANCELLING = "Stopping"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def active(self) -> bool:
        return self in (State.QUEUED, State.RUNNING, State.CANCELLING)


@dataclass(eq=False)
class Job:
    id: int
    source: Path
    out_dir: Path
    options: dict
    state: State = State.QUEUED
    stage: str = ""
    done: int = 0
    total: int = 0
    message: str = ""
    result: dict | None = None
    log: deque = field(default_factory=lambda: deque(maxlen=LOG_LINES))
    started: float = 0.0
    finished: float = 0.0
    process: multiprocessing.process.BaseProcess | None = None
    cancel_event: object | None = None
    cancel_requested: float = 0.0

    @property
    def work_dir(self) -> Path:
        return work_dir_for(self.source)


class JobManager(QObject):
    job_added = Signal(object)
    job_changed = Signal(object)
    job_removed = Signal(object)

    def __init__(
        self,
        max_parallel: int = 2,
        parent: QObject | None = None,
        target=worker.run_job,
    ):
        super().__init__(parent)
        #: The process entry point; tests substitute one that uses a fake engine.
        self._target = target
        # spawn everywhere, not only on Windows: forking a process that has Qt
        # running is unsafe, and one start method means one behaviour to test.
        self._ctx = multiprocessing.get_context("spawn")
        self._events = self._ctx.Queue()
        self._jobs: dict[int, Job] = {}
        self._ids = itertools.count(1)
        self.max_parallel = max(1, max_parallel)

        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- queries -------------------------------------------------------

    def jobs(self) -> list[Job]:
        return list(self._jobs.values())

    def running(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.state.active and j.process]

    def active(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.state.active]

    # ---- commands ------------------------------------------------------

    def submit(self, source: Path, out_dir: Path, options: dict) -> Job:
        source = Path(source)
        for job in self.active():
            if job.source.resolve() == source.resolve():
                raise ValueError(f"{source.name} is already in the queue")
        job = Job(next(self._ids), source, Path(out_dir), dict(options))
        self._jobs[job.id] = job
        self.job_added.emit(job)
        self._start_waiting()
        return job

    def cancel(self, job: Job) -> None:
        if job.state is State.QUEUED:
            self._finish(job, State.CANCELLED, "Cancelled before it started")
        elif job.state is State.RUNNING:
            job.state = State.CANCELLING
            job.message = "Stopping at the next safe point…"
            job.cancel_requested = time.monotonic()
            job.cancel_event.set()
            self.job_changed.emit(job)

    def retry(self, job: Job) -> Job:
        """Run a finished job again. Work files make it resume, not restart."""
        self.remove(job)
        return self.submit(job.source, job.out_dir, job.options)

    def remove(self, job: Job) -> None:
        if job.state.active:
            return
        self._jobs.pop(job.id, None)
        self.job_removed.emit(job)

    def clear_finished(self) -> None:
        for job in [j for j in self._jobs.values() if not j.state.active]:
            self.remove(job)

    def set_max_parallel(self, value: int) -> None:
        self.max_parallel = max(1, int(value))
        self._start_waiting()

    def shutdown(self, timeout: float = 8.0) -> None:
        """Stop everything, politely first. Called when the window closes."""
        self._timer.stop()
        for job in self.active():
            if job.process is None:
                job.state = State.CANCELLED
            elif job.cancel_event is not None:
                job.cancel_event.set()
        deadline = time.monotonic() + timeout
        for job in self._jobs.values():
            if job.process is not None:
                job.process.join(max(0.0, deadline - time.monotonic()))
                if job.process.is_alive():
                    job.process.terminate()
                    job.process.join(2)

    # ---- scheduling ----------------------------------------------------

    def _start_waiting(self) -> None:
        slots = self.max_parallel - len(self.running())
        waiting = [j for j in self._jobs.values() if j.state is State.QUEUED]
        for job in waiting[: max(0, slots)]:
            self._launch(job)

    def _launch(self, job: Job) -> None:
        job.cancel_event = self._ctx.Event()
        request = {
            "source": str(job.source),
            "out_dir": str(job.out_dir),
            "work_dir": str(job.work_dir),
            "options": job.options,
        }
        job.process = self._ctx.Process(
            target=self._target,
            args=(job.id, request, self._events, job.cancel_event),
            name=f"kitab-job-{job.id}",
            daemon=True,
        )
        job.state = State.RUNNING
        job.stage, job.done, job.total = "starting", 0, 0
        job.message = ""
        job.started = time.monotonic()
        job.process.start()
        self.job_changed.emit(job)

    def _tick(self) -> None:
        self._drain()
        for job in list(self._jobs.values()):
            if job.process is None or not job.state.active:
                continue
            if not job.process.is_alive():
                # Its last events may still be in the pipe; read them before
                # concluding it died without a word.
                self._drain()
                if job.state.active:
                    code = job.process.exitcode
                    if job.state is State.CANCELLING:
                        self._finish(job, State.CANCELLED, "Stopped")
                    else:
                        self._finish(
                            job, State.FAILED, f"The job process exited ({code})"
                        )
            elif (
                job.state is State.CANCELLING
                and time.monotonic() - job.cancel_requested > CANCEL_GRACE
            ):
                job.process.terminate()
        self._start_waiting()

    def _drain(self, limit: int = 500) -> None:
        changed: dict[int, Job] = {}
        for _ in range(limit):
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            kind, job_id, *payload = event
            job = self._jobs.get(job_id)
            if job is None:
                continue
            if kind == "progress":
                job.stage, job.done, job.total = payload
                changed[job.id] = job
            elif kind == "log":
                level, message = payload
                job.log.append(f"{level:<7} {message}" if level != "INFO" else message)
                changed[job.id] = job
            elif kind == "done":
                job.result = payload[0]
                self._finish(job, State.DONE, _summary(job.result))
            elif kind == "failed":
                self._finish(job, State.FAILED, payload[0])
            elif kind == "cancelled":
                self._finish(job, State.CANCELLED, "Stopped — it will resume from here")
        # Coalesced: a Google run can send dozens of progress events per tick.
        for job in changed.values():
            if job.state.active:
                self.job_changed.emit(job)

    def _finish(self, job: Job, state: State, message: str) -> None:
        job.state = state
        job.message = message
        job.finished = time.monotonic()
        if job.process is not None:
            job.process.join(0.1)
        job.process = None
        job.cancel_event = None
        self.job_changed.emit(job)


def _summary(result: dict) -> str:
    parts = [f"{result['translated'] + result['cached']}/{result['segments']} segments"]
    if result["failed"]:
        parts.append(f"{result['failed']} failed")
    if result["warnings"]:
        parts.append(f"{len(result['warnings'])} warning(s)")
    return " · ".join(parts)
