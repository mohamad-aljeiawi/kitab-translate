"""The Translate page: choose books, choose options, queue them."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidgetItem,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    FluentIcon,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    SettingCardGroup,
    StrongBodyLabel,
)

from kitab.translate.registry import ENGINES

from ..jobs import JobManager
from ..settings import SecretStore, Settings, engine_defaults, engine_needs_key
from ..ui import (
    ENGINE_LABELS,
    INPUT_SUFFIXES,
    LANGUAGES,
    REASONING_LABELS,
    Page,
    engine_label,
    setting_row,
)


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
                summary = f"Scanned PDF · {info.pages} pages · will be OCR'd"
            elif info.kind is SourceKind.PDF_DIGITAL:
                summary = f"PDF · {info.pages} pages"
            else:
                summary = info.kind.value.upper()
        except Exception as e:
            summary = f"Cannot read: {e}"
        self.inspected.emit(str(path), summary)


class TranslatePage(Page):
    submitted = Signal(int)
    open_settings = Signal()

    def __init__(
        self,
        settings: Settings,
        secrets: SecretStore,
        jobs: JobManager,
        parent=None,
    ):
        super().__init__("translatePage", "Translate a book", parent)
        self.settings = settings
        self.secrets = secrets
        self.jobs = jobs
        self.setAcceptDrops(True)

        self._inspector = _Inspector(self)
        self._inspector.inspected.connect(self._on_inspected)

        self._build_files()
        self._build_options()
        self._build_actions()
        self._load_defaults()

    # ---- layout --------------------------------------------------------

    def _build_files(self) -> None:
        card = CardWidget(self.view)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)

        head = QHBoxLayout()
        icon = IconWidget(FluentIcon.DOCUMENT, card)
        icon.setFixedSize(20, 20)
        head.addWidget(icon)
        head.addSpacing(8)
        head.addWidget(StrongBodyLabel("Books", card))
        head.addStretch(1)
        self.add_button = PushButton(FluentIcon.ADD, "Add files", card)
        self.add_button.clicked.connect(self._choose_files)
        self.remove_button = PushButton(FluentIcon.REMOVE, "Remove", card)
        self.remove_button.clicked.connect(self._remove_selected)
        head.addWidget(self.add_button)
        head.addWidget(self.remove_button)
        layout.addLayout(head)

        self.hint = CaptionLabel(
            "Drop PDF, EPUB, HTML, Markdown or text files here. "
            "English and Japanese in, Arabic out.",
            card,
        )
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.file_list = ListWidget(card)
        self.file_list.setMinimumHeight(140)
        self.file_list.setSelectionMode(ListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.file_list)
        self.body.addWidget(card)

    def _build_options(self) -> None:
        group = SettingCardGroup("Options", self.view)

        self.engine = ComboBox()
        for name in ENGINE_LABELS:
            self.engine.addItem(engine_label(name), userData=name)
        self.engine.setFixedWidth(250)
        self.engine.currentIndexChanged.connect(self._on_engine_changed)
        self.model = LineEdit()
        self.model.setClearButtonEnabled(True)
        self.model.setFixedWidth(160)
        self.reasoning = ComboBox()
        for value, label in REASONING_LABELS.items():
            self.reasoning.addItem(label, userData=value)
        self.reasoning.setFixedWidth(210)
        self.reasoning.setToolTip(
            "How long a reasoning model thinks before it answers. Higher is slower "
            "and costs more output tokens. Each model accepts its own set of levels."
        )
        group.addSettingCard(
            setting_row(
                FluentIcon.ROBOT,
                "Translation engine",
                "Keys and endpoints are set in Settings",
                self.engine,
                self.model,
                self.reasoning,
            )
        )

        self.language = ComboBox()
        for code, label in LANGUAGES:
            self.language.addItem(label, userData=code)
        self.language.setMinimumWidth(200)
        group.addSettingCard(
            setting_row(
                FluentIcon.LANGUAGE,
                "Source language",
                "The book's language; the output is always Arabic",
                self.language,
            )
        )

        self.pages = LineEdit()
        self.pages.setPlaceholderText("All pages")
        self.pages.setClearButtonEnabled(True)
        self.pages.setFixedWidth(200)
        group.addSettingCard(
            setting_row(
                FluentIcon.PAGE_RIGHT,
                "Pages",
                'PDF only. A range such as "1-20,35" to try a sample first',
                self.pages,
            )
        )

        self.output = LineEdit()
        self.output.setPlaceholderText("Next to each book")
        self.output.setClearButtonEnabled(True)
        self.output.setFixedWidth(280)
        browse = PushButton(FluentIcon.FOLDER, "Browse")
        browse.clicked.connect(self._choose_output)
        group.addSettingCard(
            setting_row(FluentIcon.SAVE, "Output folder", None, self.output, browse)
        )

        self.epub = CheckBox("EPUB")
        self.pdf = CheckBox("PDF")
        group.addSettingCard(
            setting_row(
                FluentIcon.LIBRARY,
                "Formats",
                "Right-to-left Arabic",
                self.epub,
                self.pdf,
            )
        )

        self.bilingual = CheckBox("Bilingual review copy")
        self.glossary = CheckBox("Consistent terms (glossary)")
        self.tier1 = CheckBox("Arabic figure legends")
        self.ocr = CheckBox("Force OCR")
        group.addSettingCard(
            setting_row(
                FluentIcon.SETTING,
                "Quality",
                "The glossary costs one extra pass with LLM engines",
                self.glossary,
                self.tier1,
                self.bilingual,
                self.ocr,
            )
        )
        self.body.addWidget(group)

    def _build_actions(self) -> None:
        row = QHBoxLayout()
        self.summary = BodyLabel("", self.view)
        row.addWidget(self.summary)
        row.addStretch(1)
        self.start = PrimaryPushButton(FluentIcon.PLAY, "Translate", self.view)
        self.start.setMinimumWidth(160)
        self.start.clicked.connect(self._submit)
        row.addWidget(self.start)
        self.body.addSpacing(8)
        self.body.addLayout(row)
        self._refresh_summary()

    # ---- state ---------------------------------------------------------

    def _load_defaults(self) -> None:
        s = self.settings
        self.engine.setCurrentIndex(max(0, self.engine.findData(s.service)))
        self.language.setCurrentIndex(max(0, self.language.findData(s.lang_in)))
        self.output.setText(s.output_dir)
        self.epub.setChecked(s.epub)
        self.pdf.setChecked(s.pdf)
        self.bilingual.setChecked(s.bilingual)
        self.glossary.setChecked(s.glossary)
        self.tier1.setChecked(s.tier1)
        self.ocr.setChecked(s.ocr)
        self._on_engine_changed()

    def _remember(self) -> None:
        s = self.settings
        s.service = self.engine.currentData()
        s.lang_in = self.language.currentData()
        s.output_dir = self.output.text().strip()
        s.epub = self.epub.isChecked()
        s.pdf = self.pdf.isChecked()
        s.bilingual = self.bilingual.isChecked()
        s.glossary = self.glossary.isChecked()
        s.tier1 = self.tier1.isChecked()
        s.ocr = self.ocr.isChecked()
        if self._reasoning_supported():
            s.engine(s.service).reasoning = self.reasoning.currentData() or ""
        s.save()

    def reload_engine(self) -> None:
        """Settings changed: the model placeholder may be stale."""
        self._on_engine_changed()

    def _on_engine_changed(self) -> None:
        name = self.engine.currentData()
        if not name:
            return
        default_model, _ = engine_defaults(name)
        saved = self.settings.engine(name).model
        self.model.setEnabled(name != "google")
        self.model.setPlaceholderText(saved or default_model or "No model")
        self.model.clear()

        supported = ENGINES[name].supports_reasoning
        effort = self.settings.engine(name).reasoning if supported else ""
        self.reasoning.setCurrentIndex(max(0, self.reasoning.findData(effort)))
        self.reasoning.setEnabled(supported)

    def _reasoning_supported(self) -> bool:
        name = self.engine.currentData()
        return bool(name) and ENGINES[name].supports_reasoning

    # ---- files ---------------------------------------------------------

    def _paths(self) -> list[Path]:
        return [
            Path(self.file_list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.file_list.count())
        ]

    def add_files(self, paths) -> None:
        present = {p.resolve() for p in self._paths()}
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or path.suffix.lower() not in INPUT_SUFFIXES:
                continue
            if path.resolve() in present:
                continue
            present.add(path.resolve())
            item = QListWidgetItem(f"{path.name}    ·    inspecting…")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.file_list.addItem(item)
            self._inspector.inspect(path)
        self._refresh_summary()

    def _on_inspected(self, path: str, summary: str) -> None:
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setText(f"{Path(path).name}    ·    {summary}")

    def _choose_files(self) -> None:
        patterns = " ".join(f"*{s}" for s in INPUT_SUFFIXES)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose books",
            self.settings.last_open_dir or str(Path.home()),
            f"Books ({patterns});;All files (*)",
        )
        if files:
            self.settings.last_open_dir = str(Path(files[0]).parent)
            self.add_files(files)

    def _remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))
        self._refresh_summary()

    def _choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Output folder", self.output.text() or str(Path.home())
        )
        if folder:
            self.output.setText(folder)

    def _refresh_summary(self) -> None:
        count = self.file_list.count()
        self.summary.setText(
            "No books yet" if count == 0 else f"{count} book{'s' * (count != 1)} ready"
        )
        self.start.setEnabled(count > 0)
        self.remove_button.setEnabled(count > 0)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.add_files(
            url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()
        )
        event.acceptProposedAction()

    # ---- submit --------------------------------------------------------

    def _submit(self) -> None:
        engine = self.engine.currentData()
        engine_settings = self.settings.engine(engine)
        key = self.secrets.get(engine)
        if engine_needs_key(engine) and not key:
            bar = InfoBar.error(
                "No API key",
                f"{engine_label(engine)} needs a key. Add it in Settings.",
                duration=6000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            button = PushButton("Open Settings")
            button.clicked.connect(self.open_settings)
            bar.addWidget(button)
            return

        if self.pdf.isChecked():
            from kitab.render.pdf_out import available_backend, system_browser

            backend = available_backend()
            if backend is None or (backend == "chromium" and not system_browser()):
                InfoBar.warning(
                    "PDF may be skipped",
                    "No Chromium browser was found (Edge, Chrome or Chromium). "
                    "The EPUB will still be written.",
                    duration=6000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )

        self._remember()
        options = {
            "service": engine,
            "model": self.model.text().strip() or engine_settings.model,
            "lang_in": self.language.currentData(),
            "pages": self.pages.text().strip() or None,
            "ocr": self.ocr.isChecked(),
            "tier1": self.tier1.isChecked(),
            "bilingual": self.bilingual.isChecked(),
            "glossary": self.glossary.isChecked(),
            "epub": self.epub.isChecked(),
            "pdf": self.pdf.isChecked(),
            "page_size": self.settings.page_size,
            "api_key": key or None,
            "base_url": engine_settings.base_url or None,
            "workers": self.settings.workers or None,
            "reasoning_effort": (
                (self.reasoning.currentData() or None)
                if self._reasoning_supported()
                else None
            ),
        }

        output = self.output.text().strip()
        queued, refused = 0, []
        for path in self._paths():
            out_dir = Path(output) if output else path.parent
            try:
                self.jobs.submit(path, out_dir, options)
                queued += 1
            except ValueError as e:
                refused.append(str(e))

        self.file_list.clear()
        self._refresh_summary()
        if refused:
            InfoBar.warning(
                "Some books were skipped",
                "\n".join(refused),
                duration=6000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        if queued:
            self.submitted.emit(queued)
