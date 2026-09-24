"""The job queue, with real processes and a fake engine.

These start actual spawned processes, which is the point: the pickling of the
request, the event queue and the cancel event are what break when this goes wrong,
and none of that is exercised by calling the worker in-process.
"""

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from kitab.gui.jobs import JobManager, State  # noqa: E402

from gui_fakes import DELAY_ENV, run_fake_job  # noqa: E402

OPTIONS = {"service": "slowfake", "glossary": False, "embed_fonts": False}


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kitab.gui.jobs.work_dir_for", lambda s: tmp_path / "work" / s.stem
    )


def _books(tmp_path, count, paragraphs=6):
    paths = []
    for i in range(count):
        path = tmp_path / f"book{i}.md"
        body = "\n\n".join(f"Book {i}, paragraph {n}." for n in range(paragraphs))
        path.write_text(f"# Book {i}\n\n{body}", encoding="utf-8")
        paths.append(path)
    return paths


def _wait(app, condition, timeout=90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_jobs_run_in_parallel_up_to_the_limit(app, isolated, tmp_path, monkeypatch):
    monkeypatch.setenv(DELAY_ENV, "0.05")
    manager = JobManager(max_parallel=2, target=run_fake_job)
    peak = 0

    def track(_job):
        nonlocal peak
        peak = max(peak, len(manager.running()))

    manager.job_changed.connect(track)
    jobs = [manager.submit(p, tmp_path / "out", OPTIONS) for p in _books(tmp_path, 3)]
    assert [j.state for j in jobs].count(State.RUNNING) == 2

    try:
        assert _wait(app, lambda: not manager.active())
    finally:
        manager.shutdown()

    for job in jobs:
        assert job.state is State.DONE, (job.message, list(job.log))
        assert job.result["epub"].endswith(".ar.epub")
        assert job.result["failed"] == 0
    assert peak == 2


def test_the_same_book_cannot_be_queued_twice(app, isolated, tmp_path):
    manager = JobManager(max_parallel=1, target=run_fake_job)
    (book,) = _books(tmp_path, 1)
    try:
        manager.submit(book, tmp_path / "out", OPTIONS)
        with pytest.raises(ValueError):
            manager.submit(book, tmp_path / "out", OPTIONS)
    finally:
        manager.shutdown()


def test_cancel_stops_a_running_job_and_retry_finishes_it(
    app, isolated, tmp_path, monkeypatch
):
    monkeypatch.setenv(DELAY_ENV, "0.3")
    manager = JobManager(max_parallel=1, target=run_fake_job)
    (book,) = _books(tmp_path, 1, paragraphs=40)
    try:
        job = manager.submit(book, tmp_path / "out", OPTIONS)
        assert _wait(app, lambda: job.stage == "translate" and job.done >= 2)
        manager.cancel(job)
        assert job.state is State.CANCELLING
        assert _wait(app, lambda: not job.state.active, timeout=30)
        assert job.state is State.CANCELLED

        monkeypatch.setenv(DELAY_ENV, "0")
        again = manager.retry(job)
        assert _wait(app, lambda: not again.state.active)
        assert again.state is State.DONE, (again.message, list(again.log))
    finally:
        manager.shutdown()


def test_a_crashing_job_is_reported(app, isolated, tmp_path):
    manager = JobManager(max_parallel=1, target=run_fake_job)
    missing = tmp_path / "missing.md"
    try:
        # The file vanishes after it was queued: the worker must say so.
        missing.write_text("# x\n\ny", encoding="utf-8")
        job = manager.submit(missing, tmp_path / "out", OPTIONS)
        missing.unlink()
        assert _wait(app, lambda: not job.state.active)
        assert job.state is State.FAILED
        assert "missing.md" in job.message
    finally:
        manager.shutdown()
