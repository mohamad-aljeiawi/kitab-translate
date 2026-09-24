"""The Settings page: appearance, jobs, engine keys, storage."""

from __future__ import annotations

import shutil

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SettingCardGroup,
    SpinBox,
)

from kitab import __version__
from kitab.translate.registry import ENGINES

from ..paths import config_dir, work_root
from ..settings import SecretStore, Settings, engine_defaults, engine_needs_key
from ..ui import Page, engine_label, open_path, setting_row

THEMES = [("auto", "Follow the system"), ("light", "Light"), ("dark", "Dark")]
PAGE_SIZES = ["A5", "A4", "B5", "Letter"]


class SettingsPage(Page):
    theme_changed = Signal(str)
    saved = Signal()

    def __init__(self, settings: Settings, secrets: SecretStore, parent=None):
        super().__init__("settingsPage", "Settings", parent)
        self.settings = settings
        self.secrets = secrets
        self._engine_fields: dict[str, tuple] = {}

        self._build_appearance()
        self._build_jobs()
        self._build_engines()
        self._build_storage()

        row = QHBoxLayout()
        row.addStretch(1)
        save = PrimaryPushButton(FluentIcon.SAVE, "Save", self.view)
        save.setMinimumWidth(140)
        save.clicked.connect(self._save)
        row.addWidget(save)
        self.body.addSpacing(8)
        self.body.addLayout(row)
        self.body.addWidget(CaptionLabel(f"kitab {__version__}", self.view))
        self._load()

    # ---- layout --------------------------------------------------------

    def _build_appearance(self) -> None:
        group = SettingCardGroup("Appearance", self.view)
        self.theme = ComboBox()
        for value, label in THEMES:
            self.theme.addItem(label, userData=value)
        self.theme.setMinimumWidth(200)
        # Applied at once, so the choice can be judged before saving it.
        self.theme.currentIndexChanged.connect(
            lambda: self.theme_changed.emit(self.theme.currentData())
        )
        group.addSettingCard(setting_row(FluentIcon.BRUSH, "Theme", None, self.theme))
        self.body.addWidget(group)

    def _build_jobs(self) -> None:
        group = SettingCardGroup("Jobs", self.view)

        self.max_jobs = SpinBox()
        self.max_jobs.setRange(1, 8)
        group.addSettingCard(
            setting_row(
                FluentIcon.TILES,
                "Books at the same time",
                "Each book is its own process; OCR uses every core, so 2 is a "
                "good ceiling for scanned books",
                self.max_jobs,
            )
        )

        self.workers = SpinBox()
        self.workers.setRange(0, 64)
        self.workers.setSpecialValueText("Engine default")
        group.addSettingCard(
            setting_row(
                FluentIcon.SPEED_HIGH,
                "Requests in flight per book",
                "Raise for a paid API tier; lower if the engine starts refusing",
                self.workers,
            )
        )

        self.page_size = ComboBox()
        for size in PAGE_SIZES:
            self.page_size.addItem(size, userData=size)
        group.addSettingCard(
            setting_row(FluentIcon.PRINT, "PDF page size", None, self.page_size)
        )
        self.body.addWidget(group)

    def _build_engines(self) -> None:
        group = SettingCardGroup("Translation engines", self.view)
        store = CaptionLabel(f"Keys are stored in {self.secrets.location}.", self.view)
        store.setWordWrap(True)
        if not self.secrets.secure:
            store.setTextColor("#9d5d00", "#fce100")

        for name in ENGINES:
            if name == "google":
                continue
            default_model, default_url = engine_defaults(name)
            key = PasswordLineEdit()
            key.setPlaceholderText("Required" if engine_needs_key(name) else "Optional")
            key.setFixedWidth(260)
            model = LineEdit()
            model.setPlaceholderText(default_model or "Model")
            model.setClearButtonEnabled(True)
            model.setFixedWidth(160)
            url = LineEdit()
            url.setPlaceholderText(default_url or "Endpoint")
            url.setClearButtonEnabled(True)
            url.setFixedWidth(220)
            self._engine_fields[name] = (key, model, url)
            group.addSettingCard(
                setting_row(
                    FluentIcon.CERTIFICATE,
                    engine_label(name),
                    (
                        "Ollama, LM Studio, vLLM… · key · model · endpoint"
                        if name == "openailiked"
                        else "API key · model · endpoint"
                    ),
                    key,
                    model,
                    url,
                )
            )
        self.body.addWidget(group)
        self.body.addWidget(store)

    def _build_storage(self) -> None:
        group = SettingCardGroup("Storage", self.view)
        open_settings = PushButton(FluentIcon.FOLDER, "Open")
        open_settings.clicked.connect(lambda: open_path(config_dir()))
        group.addSettingCard(
            setting_row(
                FluentIcon.SETTING, "Settings folder", str(config_dir()), open_settings
            )
        )

        open_work = PushButton(FluentIcon.FOLDER, "Open")
        open_work.clicked.connect(self._open_work)
        clear_work = PushButton(FluentIcon.DELETE, "Clear")
        clear_work.clicked.connect(self._clear_work)
        group.addSettingCard(
            setting_row(
                FluentIcon.ZIP_FOLDER,
                "Work files",
                "What lets a stopped book resume. Clearing them is safe when "
                "nothing is running; finished translations stay cached",
                open_work,
                clear_work,
            )
        )
        self.body.addWidget(group)

    # ---- state ---------------------------------------------------------

    def _load(self) -> None:
        s = self.settings
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.theme)))
        self.max_jobs.setValue(s.max_jobs)
        self.workers.setValue(s.workers)
        self.page_size.setCurrentIndex(max(0, self.page_size.findData(s.page_size)))
        for name, (key, model, url) in self._engine_fields.items():
            engine = s.engine(name)
            key.setText(self.secrets.get(name))
            model.setText(engine.model)
            url.setText(engine.base_url)

    def _save(self) -> None:
        s = self.settings
        s.theme = self.theme.currentData()
        s.max_jobs = self.max_jobs.value()
        s.workers = self.workers.value()
        s.page_size = self.page_size.currentData()
        for name, (key, model, url) in self._engine_fields.items():
            engine = s.engine(name)
            engine.model = model.text().strip()
            engine.base_url = url.text().strip()
            self.secrets.set(name, key.text())
        s.save()
        self.saved.emit()
        InfoBar.success(
            "Saved",
            "Settings apply to books queued from now on.",
            duration=2500,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _open_work(self) -> None:
        work_root().mkdir(parents=True, exist_ok=True)
        open_path(work_root())

    def _clear_work(self) -> None:
        window = self.window()
        if getattr(window, "jobs", None) and window.jobs.active():
            InfoBar.warning(
                "Books are running",
                "Stop or finish them before clearing their work files.",
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        shutil.rmtree(work_root(), ignore_errors=True)
        InfoBar.success(
            "Cleared",
            "Work files removed.",
            duration=2500,
            position=InfoBarPosition.TOP,
            parent=self,
        )
