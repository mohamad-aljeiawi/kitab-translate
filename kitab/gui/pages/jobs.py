"""The "My translations" page: one card per book, its progress, and what to do next.

Each card has exactly one visible action, the one that makes sense for its state
(Stop while running, Open book when finished, Try again after a failure), and
everything else in a "More" menu. The old row of unlabelled icons made people guess.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    CardWidget,
    FluentIcon,
    IconWidget,
    IndeterminateProgressBar,
    MessageBoxBase,
    PlainTextEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    RoundMenu,
    SubtitleLabel,
)

from ..i18n import duration, file_name, tr
from ..jobs import Job, JobManager, State
from ..ui import engine_label, stage_label
from ..widgets import (
    ElidedCaptionLabel,
    ElidedStrongLabel,
    EmptyState,
    Page,
    lead_align,
    open_path,
    tool_button,
    WrapBodyLabel,
    WrapCaptionLabel,
)

_STATE_ICONS = {
    State.QUEUED: FluentIcon.HISTORY,
    State.RUNNING: FluentIcon.SYNC,
    State.CANCELLING: FluentIcon.PAUSE,
    State.DONE: FluentIcon.COMPLETED,
    State.FAILED: FluentIcon.INFO,
    State.CANCELLED: FluentIcon.PAUSE,
}


class DetailsDialog(MessageBoxBase):
    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        title = SubtitleLabel(
            tr("details.title", name=file_name(job.source.name)), self
        )
        title.setWordWrap(True)
        lead_align(title)
        self.viewLayout.addWidget(title)
        self.text = PlainTextEdit(self)
        self.text.setReadOnly(True)
        # Log lines are the pipeline's own, in English: keep them left to right.
        self.text.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.text.setPlainText("\n".join(job.log) or tr("details.empty"))
        width = min(760, max(420, (parent.width() if parent else 800) - 120))
        self.text.setMinimumSize(width, 360)
        self.text.moveCursor(self.text.textCursor().MoveOperation.End)
        self.viewLayout.addWidget(self.text)
        self.yesButton.setText(tr("details.close"))
        self.cancelButton.setText(tr("details.copy"))
        # "Copy" keeps the dialog open: take it off the default reject path.
        self.cancelButton.clicked.disconnect()
        self.cancelButton.clicked.connect(self._copy)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text.toPlainText())
        self.cancelButton.setText(tr("details.copied"))


class JobCard(CardWidget):
    def __init__(self, job: Job, jobs: JobManager, parent=None):
        super().__init__(parent)
        self.job = job
        self.jobs = jobs

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 12, 12)
        outer.setSpacing(14)

        self.icon = IconWidget(FluentIcon.DOCUMENT, self)
        self.icon.setFixedSize(20, 20)
        outer.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)

        middle = QVBoxLayout()
        middle.setSpacing(4)
        self.name = ElidedStrongLabel(file_name(job.source.name), self)
        self.status = ElidedCaptionLabel("", self)
        self.bar = ProgressBar(self, useAni=False)
        self.busy = IndeterminateProgressBar(self, start=False)
        self.bars = QStackedWidget(self)
        self.bars.addWidget(self.bar)
        self.bars.addWidget(self.busy)
        self.bars.setFixedHeight(4)
        middle.addWidget(self.name)
        middle.addWidget(self.status)
        middle.addSpacing(2)
        middle.addWidget(self.bars)
        outer.addLayout(middle, 1)

        # One main action, shown as primary when it is the thing to do next.
        self.action = PushButton(self)
        self.primary = PrimaryPushButton(self)
        for button in (self.action, self.primary):
            button.setMinimumWidth(120)
            button.clicked.connect(self._main_action)
            outer.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.more = tool_button(FluentIcon.MORE, tr("action.more"))
        self.more.clicked.connect(self._show_menu)
        outer.addWidget(self.more, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh()

    # ---- actions -------------------------------------------------------

    def _main_action(self) -> None:
        state = self.job.state
        if state in (State.QUEUED, State.RUNNING):
            self.jobs.cancel(self.job)
        elif state is State.DONE:
            self._open_book()
        elif state in (State.FAILED, State.CANCELLED):
            self.jobs.retry(self.job)

    def _open_book(self) -> None:
        result = self.job.result or {}
        target = result.get("epub") or result.get("pdf") or result.get("html")
        open_path(target or self.job.out_dir)

    def _show_menu(self) -> None:
        menu = RoundMenu(parent=self)
        menu.addAction(
            Action(FluentIcon.VIEW, tr("action.details"), triggered=self._details)
        )
        if self.job.state is State.DONE:
            menu.addAction(
                Action(
                    FluentIcon.FOLDER,
                    tr("action.show_folder"),
                    triggered=lambda: open_path(self.job.out_dir),
                )
            )
        if not self.job.state.active:
            menu.addSeparator()
            menu.addAction(
                Action(
                    FluentIcon.DELETE,
                    tr("action.remove"),
                    triggered=lambda: self.jobs.remove(self.job),
                )
            )
        below = self.more.mapToGlobal(QPoint(0, self.more.height()))
        menu.exec(below)

    def _details(self) -> None:
        DetailsDialog(self.job, self.window()).exec()

    # ---- display -------------------------------------------------------

    def refresh(self) -> None:
        job, state = self.job, self.job.state
        self.icon.setIcon(_STATE_ICONS[state])
        self.status.set_text(self._status_text())

        running = state in (State.RUNNING, State.CANCELLING)
        if state is State.DONE:
            self._show_bar(determinate=True, done=1, total=1)
        elif running and job.total > 0:
            self._show_bar(determinate=True, done=job.done, total=job.total)
        elif running:
            self._show_bar(determinate=False)
        else:
            self.bars.setVisible(False)
            self.busy.stop()
        self.bar.setError(state is State.FAILED)

        label, primary = {
            State.QUEUED: (tr("action.cancel"), False),
            State.RUNNING: (tr("action.stop"), False),
            State.CANCELLING: (tr("state.stopping"), False),
            State.DONE: (tr("action.open_book"), True),
            State.FAILED: (tr("action.retry"), True),
            State.CANCELLED: (tr("action.continue"), True),
        }[state]
        shown, hidden = (
            (self.primary, self.action) if primary else (self.action, self.primary)
        )
        shown.setText(label)
        shown.setVisible(True)
        shown.setEnabled(state is not State.CANCELLING)
        hidden.setVisible(False)

    def _show_bar(self, determinate: bool, done: int = 0, total: int = 0) -> None:
        self.bars.setVisible(True)
        if determinate:
            self.busy.stop()
            self.bars.setCurrentWidget(self.bar)
            self.bar.setMaximum(max(1, total))
            self.bar.setValue(min(done, total))
        else:
            self.bars.setCurrentWidget(self.busy)
            self.busy.start()

    def _status_text(self) -> str:
        job, state = self.job, self.job.state
        via = tr("job.via", engine=engine_label(job.options.get("service", "")))
        if state is State.QUEUED:
            return f"{tr('state.queued')} · {via}"
        if state is State.CANCELLING:
            return tr("state.stopping")
        if state is State.RUNNING:
            parts = [stage_label(job.stage)]
            if job.total:
                parts.append(tr("progress.of", done=job.done, total=job.total))
            parts.append(duration(time.monotonic() - job.started))
            parts.append(via)
            return " · ".join(parts)

        took = duration(job.finished - job.started) if job.started else ""
        if state is State.DONE:
            result = job.result or {}
            parts = [tr("state.done"), took]
            total = result.get("segments", 0)
            done = result.get("translated", 0) + result.get("cached", 0)
            if total:
                parts.append(tr("job.parts", done=done, total=total))
            if result.get("failed"):
                parts.append(tr("job.kept", n=result["failed"]))
            if result.get("warnings"):
                parts.append(tr("job.warnings", n=len(result["warnings"])))
            return " · ".join(p for p in parts if p)
        if state is State.CANCELLED:
            if not job.started:
                return tr("job.cancelled_before")
            return f"{tr('state.cancelled')} · {tr('job.resume_hint')}"
        # Failed: the first line of the pipeline's message is the useful part; the
        # full text, paths and traceback included, is one click away in Details.
        first = (job.message or "").strip().splitlines()[0:1]
        reason = first[0] if first else tr("job.crashed")
        return f"{tr('state.failed')} · {reason}"


class JobsPage(Page):
    def __init__(self, jobs: JobManager, parent=None):
        super().__init__("jobsPage", tr("jobs.title"), parent)
        self.jobs = jobs
        self.cards: dict[int, JobCard] = {}

        header = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(2)
        self.counts = WrapBodyLabel("", self.view)
        self.limit = WrapCaptionLabel("", self.view)
        text.addWidget(self.counts)
        text.addWidget(self.limit)
        header.addLayout(text, 1)
        self.clear = PushButton(FluentIcon.BROOM, tr("jobs.clear"), self.view)
        self.clear.clicked.connect(self.jobs.clear_finished)
        header.addWidget(self.clear, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(header)

        self.go_translate = PrimaryPushButton(
            FluentIcon.LANGUAGE, tr("jobs.empty.go"), self.view
        )
        self.empty = EmptyState(
            FluentIcon.LIBRARY,
            tr("jobs.empty.title"),
            tr("jobs.empty.body"),
            self.go_translate,
            self.view,
        )
        self.body.addWidget(self.empty)

        self.list = QWidget(self.view)
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.body.addWidget(self.list)
        self.body.addStretch(1)

        jobs.job_added.connect(self._add)
        jobs.job_changed.connect(self._update)
        jobs.job_removed.connect(self._remove)
        # A window rebuilt for a language change picks up jobs already running.
        for job in jobs.jobs():
            self._add(job)
        self.refresh_counts()

        # A scanned page can take several seconds, so the elapsed time ticks here
        # rather than waiting for the job's next event.
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(1000)

    def _tick(self) -> None:
        for card in self.cards.values():
            if card.job.state is State.RUNNING:
                card.status.set_text(card._status_text())

    def _add(self, job: Job) -> None:
        if job.id in self.cards:
            return
        card = JobCard(job, self.jobs, self.list)
        self.cards[job.id] = card
        # Newest first: what you just started is what you are looking for.
        self.list_layout.insertWidget(0, card)
        self.refresh_counts()

    def _update(self, job: Job) -> None:
        card = self.cards.get(job.id)
        if card is not None:
            card.refresh()
        self.refresh_counts()

    def _remove(self, job: Job) -> None:
        card = self.cards.pop(job.id, None)
        if card is not None:
            self.list_layout.removeWidget(card)
            card.deleteLater()
        self.refresh_counts()

    def refresh_counts(self) -> None:
        jobs = self.jobs.jobs()
        running = sum(1 for j in jobs if j.state in (State.RUNNING, State.CANCELLING))
        waiting = sum(1 for j in jobs if j.state is State.QUEUED)
        done = sum(1 for j in jobs if j.state is State.DONE)
        self.counts.setText(
            tr("jobs.summary", running=running, waiting=waiting, done=done)
        )
        self.limit.setText(tr("jobs.limit", n=self.jobs.max_parallel))
        has = bool(jobs)
        self.empty.setVisible(not has)
        self.list.setVisible(has)
        self.counts.setVisible(has)
        self.limit.setVisible(has)
        self.clear.setVisible(any(not j.state.active for j in jobs))
