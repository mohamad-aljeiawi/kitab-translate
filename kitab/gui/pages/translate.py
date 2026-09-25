"""The Translate page: choose books, choose how, start."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    CheckBox,
    FluentIcon,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    TransparentPushButton,
)

from kitab.translate.registry import ENGINES

from ..i18n import file_name, plural, tr
from ..jobs import JobManager
from ..settings import SecretStore, Settings, engine_defaults, engine_needs_key
from ..ui import (
    INPUT_SUFFIXES,
    engine_items,
    engine_label,
    source_items,
    thinking_items,
)
from ..widgets import (
    Collapsible,
    ElidedCaptionLabel,
    ElidedStrongLabel,
    OptionRow,
    Page,
    Section,
    make_combo,
    make_switch,
    show_row,
    tool_button,
    WrapBodyLabel,
)

_PAGES = re.compile(r"^\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*$")


class _Inspector(QObject):
    """Classify files off the GUI thread; a large PDF takes a moment to sample."""

    inspected = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="inspect")

    def inspect(self, path: Path) -> None:
        self._pool.submit(self._run, path)

    def _run(self, path: Path) -> None:
        try:
            from kitab.ingest.classify import SourceKind, classify

            info = classify(path)
            if info.kind is SourceKind.PDF_SCANNED:
                summary = tr("book.scanned", pages=info.pages)
            elif info.kind is SourceKind.PDF_DIGITAL:
                summary = tr("book.pdf", pages=info.pages)
            else:
                summary = tr(f"book.{info.kind.value}")
        except Exception:
            summary = tr("book.unreadable")
        self.inspected.emit(str(path), summary)


class BookRow(QWidget):
    removed = Signal(object)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 8, 10)
        layout.setSpacing(12)
        icon = IconWidget(FluentIcon.DOCUMENT, self)
        icon.setFixedSize(18, 18)
        layout.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.name = ElidedStrongLabel(file_name(path.name), self)
        self.detail = ElidedCaptionLabel(tr("book.checking"), self)
        text.addWidget(self.name)
        text.addWidget(self.detail)
        layout.addLayout(text, 1)
        remove = tool_button(FluentIcon.CLOSE, tr("book.remove"))
        remove.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(remove)


class BookList(CardWidget):
    """The chosen books, or a place to drop them when there are none."""

    changed = Signal()
    choose = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[BookRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Empty: one obvious target, with a button for those who do not drag.
        self.empty = QWidget(self)
        empty = QVBoxLayout(self.empty)
        empty.setContentsMargins(24, 28, 24, 28)
        empty.setSpacing(8)
        empty.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        icon = IconWidget(FluentIcon.FOLDER_ADD, self.empty)
        icon.setFixedSize(32, 32)
        empty.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        drop = StrongBodyLabel(tr("books.drop"), self.empty)
        drop.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty.addWidget(drop)
        choose = PrimaryPushButton(FluentIcon.ADD, tr("books.choose"), self.empty)
        choose.clicked.connect(self.choose)
        empty.addWidget(choose, 0, Qt.AlignmentFlag.AlignHCenter)
        hint = CaptionLabel(tr("books.supported"), self.empty)
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty.addWidget(hint)
        layout.addWidget(self.empty)

        self.list = QWidget(self)
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 4, 0, 0)
        self.list_layout.setSpacing(0)
        layout.addWidget(self.list)

        self.actions = QWidget(self)
        actions = QHBoxLayout(self.actions)
        actions.setContentsMargins(8, 0, 8, 8)
        add = TransparentPushButton(FluentIcon.ADD, tr("books.add_more"), self.actions)
        add.clicked.connect(self.choose)
        clear = TransparentPushButton(
            FluentIcon.DELETE, tr("books.clear"), self.actions
        )
        clear.clicked.connect(self.clear)
        actions.addWidget(add)
        actions.addWidget(clear)
        actions.addStretch(1)
        layout.addWidget(self.actions)
        self._refresh()

    def paths(self) -> list[Path]:
        return [row.path for row in self.rows]

    def add(self, path: Path) -> BookRow | None:
        if any(row.path.resolve() == path.resolve() for row in self.rows):
            return None
        row = BookRow(path, self.list)
        row.removed.connect(self._remove)
        self.rows.append(row)
        self.list_layout.addWidget(row)
        self._refresh()
        return row

    def set_detail(self, path: str, text: str) -> None:
        for row in self.rows:
            if str(row.path) == path:
                row.detail.set_text(text)

    def clear(self) -> None:
        for row in list(self.rows):
            self._remove(row)

    def _remove(self, row: BookRow) -> None:
        self.rows.remove(row)
        self.list_layout.removeWidget(row)
        row.deleteLater()
        self._refresh()

    def _refresh(self) -> None:
        has = bool(self.rows)
        self.empty.setVisible(not has)
        self.list.setVisible(has)
        self.actions.setVisible(has)
        self.changed.emit()


class TranslatePage(Page):
    submitted = Signal(int)
    open_settings = Signal()

    def __init__(
        self, settings: Settings, secrets: SecretStore, jobs: JobManager, parent=None
    ):
        super().__init__("translatePage", tr("translate.title"), parent)
        self.settings = settings
        self.secrets = secrets
        self.jobs = jobs
        self.setAcceptDrops(True)

        self._inspector = _Inspector(self)
        self._inspector.inspected.connect(self._on_inspected)

        self.books = BookList(self.view)
        self.books.choose.connect(self._choose_files)
        self.books.changed.connect(self._refresh_footer)
        self.body.addWidget(self.books)

        self._build_translation()
        self._build_result()
        self._build_more()
        self.body.addStretch(1)
        self._build_footer()
        self._on_engine_changed()
        self._refresh_footer()

    # ---- layout --------------------------------------------------------

    def _build_translation(self) -> None:
        s = self.settings
        section = Section(tr("group.translation"), self.view)

        self.engine = make_combo(engine_items(), s.service, width=240)
        self.engine.currentIndexChanged.connect(self._on_engine_changed)
        section.add(
            OptionRow(
                FluentIcon.ROBOT, tr("engine.title"), tr("engine.desc"), self.engine
            )
        )

        self.model = LineEdit()
        self.model.setClearButtonEnabled(True)
        self.model.setMinimumWidth(240)
        self.model_row = section.add(
            OptionRow(FluentIcon.TAG, tr("model.title"), "", self.model)
        )

        self.thinking = make_combo(thinking_items(), "", width=240)
        self.thinking_row = section.add(
            OptionRow(
                FluentIcon.SPEED_MEDIUM,
                tr("thinking.title"),
                tr("thinking.desc"),
                self.thinking,
            )
        )

        self.source = make_combo(source_items(), s.lang_in, width=240)
        section.add(
            OptionRow(
                FluentIcon.LANGUAGE, tr("source.title"), tr("source.desc"), self.source
            )
        )
        self.body.addWidget(section)

    def _build_result(self) -> None:
        s = self.settings
        section = Section(tr("group.result"), self.view)

        self.output_change = PushButton(FluentIcon.FOLDER, tr("output.change"))
        self.output_change.clicked.connect(self._choose_output)
        self.output_reset = tool_button(FluentIcon.CLOSE, tr("output.reset"))
        self.output_reset.clicked.connect(lambda: self._set_output(""))
        self.output_row = section.add(
            OptionRow(
                FluentIcon.SAVE,
                tr("output.title"),
                "",
                self.output_change,
                self.output_reset,
            )
        )
        self._set_output(s.output_dir, save=False)

        self.epub = CheckBox("EPUB")
        self.epub.setChecked(s.epub)
        self.pdf = CheckBox("PDF")
        self.pdf.setChecked(s.pdf)
        for box in (self.epub, self.pdf):
            box.stateChanged.connect(self._refresh_footer)
        section.add(
            OptionRow(
                FluentIcon.LIBRARY,
                tr("formats.title"),
                tr("formats.desc"),
                self.epub,
                self.pdf,
            )
        )
        self.body.addWidget(section)

    def _build_more(self) -> None:
        s = self.settings
        more = Collapsible(tr("group.more"), tr("more.desc"), self.view)

        self.pages = LineEdit()
        self.pages.setPlaceholderText(tr("pages.all"))
        self.pages.setClearButtonEnabled(True)
        self.pages.setMinimumWidth(180)
        self.pages.textChanged.connect(self._refresh_footer)
        more.add(
            OptionRow(
                FluentIcon.PAGE_RIGHT, tr("pages.title"), tr("pages.desc"), self.pages
            )
        )

        self.glossary = make_switch(s.glossary)
        more.add(
            OptionRow(
                FluentIcon.DICTIONARY,
                tr("glossary.title"),
                tr("glossary.desc"),
                self.glossary,
            )
        )
        self.figures = make_switch(s.tier1)
        more.add(
            OptionRow(
                FluentIcon.PHOTO, tr("figures.title"), tr("figures.desc"), self.figures
            )
        )
        self.bilingual = make_switch(s.bilingual)
        more.add(
            OptionRow(
                FluentIcon.ALIGNMENT,
                tr("bilingual.title"),
                tr("bilingual.desc"),
                self.bilingual,
            )
        )
        self.ocr = make_switch(s.ocr)
        more.add(
            OptionRow(FluentIcon.SEARCH, tr("ocr.title"), tr("ocr.desc"), self.ocr)
        )
        self.more = more
        self.body.addWidget(more)

    def _build_footer(self) -> None:
        self.summary = WrapBodyLabel("", self.footer)
        self.start = PrimaryPushButton(FluentIcon.PLAY, tr("start.button"), self.footer)
        self.start.setMinimumWidth(180)
        self.start.clicked.connect(self._submit)
        self.footer_layout.addWidget(self.summary, 1)
        self.footer_layout.addWidget(self.start)
        self.footer.show()

    # ---- state ---------------------------------------------------------

    def reload_engine(self) -> None:
        """Settings changed: model defaults and keys may be different now."""
        self._on_engine_changed()

    def _engine(self) -> str:
        return self.engine.currentData() or "google"

    def _on_engine_changed(self) -> None:
        name = self._engine()
        saved = self.settings.engine(name)
        default_model, _ = engine_defaults(name)
        fallback = saved.model or default_model

        show_row(self.model_row, name != "google")
        self.model.clear()
        self.model.setPlaceholderText(fallback)
        self.model_row.set_description(
            tr("model.desc", model=fallback) if fallback else tr("model.desc_plain")
        )

        supported = ENGINES[name].supports_reasoning
        show_row(self.thinking_row, supported)
        level = saved.reasoning if supported else ""
        self.thinking.setCurrentIndex(max(0, self.thinking.findData(level)))

    def _set_output(self, folder: str, save: bool = True) -> None:
        self.settings.output_dir = folder
        self.output_row.set_description(folder or tr("output.same"))
        self.output_reset.setVisible(bool(folder))
        if save:
            self.settings.save()

    def _pages_ok(self) -> bool:
        text = self.pages.text().strip()
        return not text or bool(_PAGES.match(text))

    def _refresh_footer(self) -> None:
        count = len(self.books.rows)
        pages_ok = self._pages_ok()
        has_format = self.epub.isChecked() or self.pdf.isChecked()
        self.pages.setError(not pages_ok)
        if count == 0:
            message = tr("start.none")
        elif not has_format:
            message = tr("start.no_format")
        elif not pages_ok:
            message = tr("pages.invalid")
        else:
            message = plural("books.ready", count)
        self.summary.setText(message)
        self.start.setEnabled(count > 0 and pages_ok and has_format)

    def _remember(self) -> None:
        s = self.settings
        s.service = self._engine()
        s.lang_in = self.source.currentData()
        s.epub = self.epub.isChecked()
        s.pdf = self.pdf.isChecked()
        s.glossary = self.glossary.isChecked()
        s.tier1 = self.figures.isChecked()
        s.bilingual = self.bilingual.isChecked()
        s.ocr = self.ocr.isChecked()
        if ENGINES[s.service].supports_reasoning:
            s.engine(s.service).reasoning = self.thinking.currentData() or ""
        s.save()

    # ---- files ---------------------------------------------------------

    def add_files(self, paths) -> None:
        for raw in paths:
            path = Path(raw)
            if path.is_file() and path.suffix.lower() in INPUT_SUFFIXES:
                if self.books.add(path) is not None:
                    self._inspector.inspect(path)

    def pending_files(self) -> list[Path]:
        return self.books.paths()

    def _on_inspected(self, path: str, summary: str) -> None:
        self.books.set_detail(path, summary)

    def _choose_files(self) -> None:
        patterns = " ".join(f"*{s}" for s in INPUT_SUFFIXES)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            tr("dialog.choose_books"),
            self.settings.last_open_dir or str(Path.home()),
            f"{tr('dialog.books')} ({patterns});;{tr('dialog.all_files')} (*)",
        )
        if files:
            self.settings.last_open_dir = str(Path(files[0]).parent)
            self.add_files(files)

    def _choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("dialog.choose_folder"),
            self.settings.output_dir or str(Path.home()),
        )
        if folder:
            self._set_output(folder)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.add_files(
            url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()
        )
        event.acceptProposedAction()

    # ---- submit --------------------------------------------------------

    def _notify(self, kind, title: str, body: str, action: QWidget | None = None):
        bar = kind(
            title, body, duration=6000, position=InfoBarPosition.TOP, parent=self
        )
        if action is not None:
            bar.addWidget(action)
        return bar

    def _submit(self) -> None:
        engine = self._engine()
        engine_settings = self.settings.engine(engine)
        key = self.secrets.get(engine)
        if engine_needs_key(engine) and not key:
            button = PushButton(tr("nokey.open"))
            button.clicked.connect(self.open_settings)
            self._notify(
                InfoBar.error,
                tr("nokey.title"),
                tr("nokey.body", engine=engine_label(engine)),
                button,
            )
            return

        if self.pdf.isChecked():
            from kitab.render.pdf_out import available_backend, system_browser

            backend = available_backend()
            if backend is None or (backend == "chromium" and not system_browser()):
                self._notify(
                    InfoBar.warning, tr("nobrowser.title"), tr("nobrowser.body")
                )

        self._remember()
        thinking = ENGINES[engine].supports_reasoning
        options = {
            "service": engine,
            "model": self.model.text().strip() or engine_settings.model,
            "lang_in": self.source.currentData(),
            "pages": self.pages.text().strip() or None,
            "ocr": self.ocr.isChecked(),
            "tier1": self.figures.isChecked(),
            "bilingual": self.bilingual.isChecked(),
            "glossary": self.glossary.isChecked(),
            "epub": self.epub.isChecked(),
            "pdf": self.pdf.isChecked(),
            "page_size": self.settings.page_size,
            "api_key": key or None,
            "base_url": engine_settings.base_url or None,
            "workers": self.settings.workers or None,
            "reasoning_effort": (
                (self.thinking.currentData() or None) if thinking else None
            ),
        }

        output = self.settings.output_dir
        queued, busy = 0, []
        for path in self.books.paths():
            try:
                self.jobs.submit(path, Path(output) if output else path.parent, options)
                queued += 1
            except ValueError:
                busy.append(path.name)

        self.books.clear()
        if busy:
            self._notify(InfoBar.warning, tr("busy.title"), "\n".join(busy))
        if queued:
            self.submitted.emit(queued)
