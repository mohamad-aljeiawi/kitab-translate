"""The Jobs page: one card per book, live progress, and what to do next."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    IconWidget,
    IndeterminateProgressBar,
    MessageBoxBase,
    PlainTextEdit,
    ProgressBar,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    ToolTipFilter,
    TransparentToolButton,
)

from ..jobs import Job, JobManager, State
from ..ui import STAGE_LABELS, Page, engine_label, open_path

_STATE_ICONS = {
    State.QUEUED: FluentIcon.HISTORY,
    State.RUNNING: FluentIcon.SYNC,
    State.CANCELLING: FluentIcon.PAUSE,
    State.DONE: FluentIcon.COMPLETED,
    State.FAILED: FluentIcon.CANCEL,
    State.CANCELLED: FluentIcon.REMOVE,
}


def _tool(icon, tip: str) -> TransparentToolButton:
    button = TransparentToolButton(icon)
    button.setToolTip(tip)
    button.installEventFilter(ToolTipFilter(button))
    return button


class LogDialog(MessageBoxBase):
    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(job.source.name, self))
        text = PlainTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText("\n".join(job.log) or "Nothing logged yet.")
        text.setMinimumSize(720, 420)
        text.moveCursor(text.textCursor().MoveOperation.End)
        self.viewLayout.addWidget(text)
        self.yesButton.setText("Close")
        self.cancelButton.hide()


class JobCard(CardWidget):
    def __init__(self, job: Job, jobs: JobManager, parent=None):
        super().__init__(parent)
        self.job = job
        self.jobs = jobs

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 12, 14)
        outer.setSpacing(14)

        self.icon = IconWidget(FluentIcon.DOCUMENT, self)
        self.icon.setFixedSize(22, 22)
        outer.addWidget(self.icon)

        middle = QVBoxLayout()
        middle.setSpacing(4)
        self.name = StrongBodyLabel(job.source.name, self)
        self.name.setToolTip(str(job.source))
        self.detail = CaptionLabel("", self)
        self.detail.setWordWrap(True)
        self.bar = ProgressBar(self, useAni=False)
        self.busy = IndeterminateProgressBar(self, start=False)
        self.bars = QStackedWidget(self)
        self.bars.addWidget(self.bar)
        self.bars.addWidget(self.busy)
        self.bars.setFixedHeight(6)
        middle.addWidget(self.name)
        middle.addWidget(self.detail)
        middle.addWidget(self.bars)
        outer.addLayout(middle, 1)

        self.cancel = _tool(FluentIcon.CLOSE, "Stop")
        self.retry = _tool(FluentIcon.SYNC, "Run again (resumes where it stopped)")
        self.folder = _tool(FluentIcon.FOLDER, "Open the output folder")
        self.book = _tool(FluentIcon.LIBRARY, "Open the translated book")
        self.log = _tool(FluentIcon.VIEW, "Show the log")
        self.remove = _tool(FluentIcon.DELETE, "Remove from the list")
        for button in (
            self.book,
            self.folder,
            self.log,
            self.retry,
            self.cancel,
            self.remove,
        ):
            outer.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.cancel.clicked.connect(lambda: self.jobs.cancel(self.job))
        self.retry.clicked.connect(lambda: self.jobs.retry(self.job))
        self.remove.clicked.connect(lambda: self.jobs.remove(self.job))
        self.folder.clicked.connect(lambda: open_path(self.job.out_dir))
        self.book.clicked.connect(self._open_book)
        self.log.clicked.connect(lambda: LogDialog(self.job, self.window()).exec())
        self.refresh()

    def _open_book(self) -> None:
        result = self.job.result or {}
        target = result.get("epub") or result.get("pdf") or result.get("html")
        if target:
            open_path(target)

    def refresh(self) -> None:
        job = self.job
        state = job.state
        self.icon.setIcon(_STATE_ICONS[state])

        engine = engine_label(job.options.get("service", ""))
        if job.options.get("reasoning_effort"):
            engine += f" ({job.options['reasoning_effort']} reasoning)"
        if state is State.QUEUED:
            detail = f"Waiting · {engine}"
        elif state in (State.RUNNING, State.CANCELLING):
            stage = STAGE_LABELS.get(job.stage, job.stage.capitalize())
            count = f" {job.done}/{job.total}" if job.total else ""
            if job.total == 0 and job.done:
                count = f" · {job.done}"
            elapsed = _duration(time.monotonic() - job.started)
            detail = job.message or f"{stage}{count} · {elapsed} · {engine}"
        else:
            took = ""
            if job.started and job.finished:
                took = f" · {_duration(job.finished - job.started)}"
            detail = f"{state.value}{took} · {job.message}"
        self.detail.setText(detail)

        running = state in (State.RUNNING, State.CANCELLING)
        determinate = running and job.total > 0
        self.bars.setVisible(running or state is State.DONE)
        if state is State.DONE:
            self.bars.setCurrentWidget(self.bar)
            self.busy.stop()
            self.bar.setMaximum(100)
            self.bar.setValue(100)
        elif determinate:
            self.bars.setCurrentWidget(self.bar)
            self.busy.stop()
            self.bar.setMaximum(job.total)
            self.bar.setValue(min(job.done, job.total))
        elif running:
            self.bars.setCurrentWidget(self.busy)
            self.busy.start()
        else:
            self.busy.stop()

        self.bar.setError(state is State.FAILED)
        self.cancel.setVisible(state in (State.QUEUED, State.RUNNING))
        self.retry.setVisible(state in (State.FAILED, State.CANCELLED, State.DONE))
        self.remove.setVisible(not state.active)
        self.folder.setVisible(state is State.DONE)
        self.book.setVisible(state is State.DONE and bool(job.result))


class JobsPage(Page):
    def __init__(self, jobs: JobManager, parent=None):
        super().__init__("jobsPage", "Jobs", parent)
        self.jobs = jobs
        self.cards: dict[int, JobCard] = {}

        bar = QHBoxLayout()
        self.counts = BodyLabel("", self.view)
        bar.addWidget(self.counts)
        bar.addStretch(1)
        self.clear = PushButton(FluentIcon.BROOM, "Clear finished", self.view)
        self.clear.clicked.connect(self.jobs.clear_finished)
        bar.addWidget(self.clear)
        self.body.addLayout(bar)

        self.empty = CaptionLabel(
            "No jobs yet. Add books on the Translate page.", self.view
        )
        self.body.addWidget(self.empty)

        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        self.body.addLayout(self.list)
        self.body.addStretch(1)

        jobs.job_added.connect(self._add)
        jobs.job_changed.connect(self._update)
        jobs.job_removed.connect(self._remove)
        self._refresh_counts()

        # A scanned page can take several seconds, so the elapsed time is ticked
        # here rather than waiting for the job's next event.
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(1000)

    def _tick(self) -> None:
        for card in self.cards.values():
            if card.job.state in (State.RUNNING, State.CANCELLING):
                card.refresh()

    def _add(self, job: Job) -> None:
        card = JobCard(job, self.jobs, self.view)
        self.cards[job.id] = card
        self.list.addWidget(card)
        self._refresh_counts()

    def _update(self, job: Job) -> None:
        card = self.cards.get(job.id)
        if card is not None:
            card.refresh()
        self._refresh_counts()

    def _remove(self, job: Job) -> None:
        card = self.cards.pop(job.id, None)
        if card is not None:
            self.list.removeWidget(card)
            card.deleteLater()
        self._refresh_counts()

    def _refresh_counts(self) -> None:
        jobs = self.jobs.jobs()
        running = sum(1 for j in jobs if j.state in (State.RUNNING, State.CANCELLING))
        queued = sum(1 for j in jobs if j.state is State.QUEUED)
        done = sum(1 for j in jobs if j.state is State.DONE)
        parts = [f"{running} running", f"{queued} waiting", f"{done} done"]
        self.counts.setText(
            " · ".join(parts) + f"   (up to {self.jobs.max_parallel} at a time)"
        )
        self.empty.setVisible(not jobs)
        self.clear.setEnabled(any(not j.state.active for j in jobs))


def _duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"
