"""The Settings page. Every change is saved as it is made; there is no Save button.

A Save button beside controls that already applied themselves (the theme did, the
rest did not) left people unsure what had been kept. Now everything behaves the
same way, and API keys are stored when you leave the field.
"""

from __future__ import annotations

import shutil
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    FluentIcon,
    HyperlinkButton,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PasswordLineEdit,
    PushButton,
    SpinBox,
)

from kitab import __version__
from kitab.translate.registry import ENGINES

from ..i18n import tr
from ..paths import config_dir, work_root
from ..settings import SecretStore, Settings, engine_defaults, engine_needs_key
from ..ui import ENGINES_SHOWN, engine_label
from ..widgets import (
    OptionRow,
    Page,
    Section,
    make_combo,
    open_path,
    WrapBodyLabel,
    WrapCaptionLabel,
)

SOURCE_URL = "https://github.com/mohamad-aljeiawi/kitab-translate"
PAGE_SIZES = ["A5", "A4", "B5", "Letter"]


class ServiceCard(QWidget):
    """One translation service: a header with its status, and its fields beneath."""

    changed = Signal()

    def __init__(
        self, name: str, settings: Settings, secrets: SecretStore, parent=None
    ):
        super().__init__(parent)
        self.name = name
        self.settings = settings
        self.secrets = secrets
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = CardWidget(self)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(16, 12, 14, 12)
        head.setSpacing(14)
        icon = IconWidget(FluentIcon.CERTIFICATE, self.header)
        icon.setFixedSize(18, 18)
        head.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(WrapBodyLabel(engine_label(name), self.header))
        if name == "openailiked":
            text.addWidget(
                WrapCaptionLabel(tr("service.openailiked.desc"), self.header)
            )
        head.addLayout(text, 1)
        self.status = CaptionLabel("", self.header)
        head.addWidget(self.status)
        self.arrow = IconWidget(FluentIcon.CHEVRON_DOWN_MED, self.header)
        self.arrow.setFixedSize(12, 12)
        head.addWidget(self.arrow)
        self.header.clicked.connect(self.toggle)
        layout.addWidget(self.header)

        self.body = CardWidget(self)
        rows = QVBoxLayout(self.body)
        rows.setContentsMargins(0, 4, 0, 4)
        rows.setSpacing(0)
        engine = settings.engine(name)
        default_model, default_url = engine_defaults(name)
        required = engine_needs_key(name)

        self.key = PasswordLineEdit()
        self.key.setPlaceholderText(tr("service.key.placeholder"))
        self.key.setMinimumWidth(260)
        self.key.setText(secrets.get(name))
        self.key.editingFinished.connect(self._save_key)
        rows.addWidget(
            OptionRow(
                FluentIcon.FINGERPRINT,
                tr("service.key"),
                tr("service.key.required" if required else "service.key.optional"),
                self.key,
            )
        )

        self.model = LineEdit()
        self.model.setClearButtonEnabled(True)
        self.model.setMinimumWidth(260)
        self.model.setPlaceholderText(default_model)
        self.model.setText(engine.model)
        self.model.editingFinished.connect(self._save_fields)
        rows.addWidget(
            OptionRow(
                FluentIcon.TAG,
                tr("service.model"),
                tr("service.model.desc", model=default_model),
                self.model,
            )
        )

        self.url = LineEdit()
        self.url.setClearButtonEnabled(True)
        self.url.setMinimumWidth(260)
        self.url.setPlaceholderText(default_url)
        self.url.setText(engine.base_url)
        # Addresses are Latin text; keep them left to right in the Arabic window.
        self.url.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.url.editingFinished.connect(self._save_fields)
        rows.addWidget(
            OptionRow(
                FluentIcon.GLOBE,
                tr("service.url"),
                tr("service.url.desc", url=default_url),
                self.url,
            )
        )
        self.key.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.model.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.body.hide()
        layout.addWidget(self.body)
        self._refresh_status()

    def toggle(self) -> None:
        open_ = not self.body.isVisible()
        self.body.setVisible(open_)
        self.arrow.setIcon(FluentIcon.UP if open_ else FluentIcon.CHEVRON_DOWN_MED)

    def _save_key(self) -> None:
        # editingFinished fires whenever focus leaves the field. Writing an
        # unchanged key would touch the keyring, which on Linux can raise a
        # KWallet or Secret Service prompt.
        if self.key.text().strip() == self.secrets.get(self.name):
            return
        self.secrets.set(self.name, self.key.text())
        self._refresh_status()
        self.changed.emit()

    def _save_fields(self) -> None:
        engine = self.settings.engine(self.name)
        model, url = self.model.text().strip(), self.url.text().strip()
        if (engine.model, engine.base_url) == (model, url):
            return
        engine.model, engine.base_url = model, url
        self.settings.save()
        self.changed.emit()

    def _refresh_status(self) -> None:
        if self.key.text().strip():
            self.status.setText(tr("service.status.ready"))
        elif engine_needs_key(self.name):
            self.status.setText(tr("service.status.missing"))
        else:
            self.status.setText(tr("service.status.optional"))


class SettingsPage(Page):
    language_changed = Signal(str)
    theme_changed = Signal(str)
    accent_changed = Signal(str)
    changed = Signal()

    def __init__(
        self, settings: Settings, secrets: SecretStore, jobs=None, parent=None
    ):
        super().__init__("settingsPage", tr("settings.title"), parent)
        self.settings = settings
        self.secrets = secrets
        self.jobs = jobs
        self._build_general()
        self._build_services()
        self._build_speed()
        self._build_storage()
        self._build_about()
        self.body.addStretch(1)

    # ---- sections ------------------------------------------------------

    def _build_general(self) -> None:
        s = self.settings
        section = Section(tr("group.general"), self.view)
        # Each language is named in itself, so it can be found by someone who
        # cannot read the one currently shown.
        self.language = make_combo(
            [("auto", tr("lang.auto")), ("en", "English"), ("ar", "العربية")],
            s.language,
        )
        self.language.currentIndexChanged.connect(self._on_language)
        section.add(
            OptionRow(
                FluentIcon.LANGUAGE, tr("lang.title"), tr("lang.desc"), self.language
            )
        )
        self.theme = make_combo(
            [
                ("auto", tr("theme.auto")),
                ("light", tr("theme.light")),
                ("dark", tr("theme.dark")),
            ],
            s.theme,
        )
        self.theme.currentIndexChanged.connect(self._on_theme)
        section.add(
            OptionRow(FluentIcon.BRUSH, tr("theme.title"), tr("theme.desc"), self.theme)
        )
        self.accent = make_combo(
            [("system", tr("accent.system")), ("kitab", tr("accent.kitab"))],
            s.accent,
        )
        self.accent.currentIndexChanged.connect(self._on_accent)
        section.add(
            OptionRow(
                FluentIcon.PALETTE, tr("accent.title"), tr("accent.desc"), self.accent
            )
        )
        self.body.addWidget(section)

    def _build_services(self) -> None:
        heading = Section(tr("group.services"), self.view)
        heading.card.hide()
        self.body.addWidget(heading)
        where = WrapCaptionLabel(
            tr("services.where", where=self._key_location()), self.view
        )
        if not self.secrets.secure:
            where.setTextColor("#9d5d00", "#fce100")
        self.body.addWidget(where)

        cards = QVBoxLayout()
        cards.setSpacing(6)
        self.services: dict[str, ServiceCard] = {}
        for name in ENGINES_SHOWN:
            if name not in ENGINES or name == "google":
                continue
            card = ServiceCard(name, self.settings, self.secrets, self.view)
            card.changed.connect(self.changed)
            self.services[name] = card
            cards.addWidget(card)
        self.body.addLayout(cards)

    def _build_speed(self) -> None:
        s = self.settings
        section = Section(tr("group.speed"), self.view)

        self.parallel = SpinBox()
        self.parallel.setRange(1, 8)
        self.parallel.setValue(s.max_jobs)
        self.parallel.valueChanged.connect(self._save_speed)
        section.add(
            OptionRow(
                FluentIcon.TILES,
                tr("parallel.title"),
                tr("parallel.desc"),
                self.parallel,
            )
        )

        self.requests = SpinBox()
        self.requests.setRange(0, 64)
        self.requests.setSpecialValueText(tr("requests.auto"))
        self.requests.setValue(s.workers)
        self.requests.setMinimumWidth(150)
        self.requests.valueChanged.connect(self._save_speed)
        section.add(
            OptionRow(
                FluentIcon.SPEED_HIGH,
                tr("requests.title"),
                tr("requests.desc"),
                self.requests,
            )
        )

        self.page_size = make_combo([(p, p) for p in PAGE_SIZES], s.page_size, 120)
        self.page_size.currentIndexChanged.connect(self._save_speed)
        section.add(
            OptionRow(
                FluentIcon.PRINT,
                tr("pagesize.title"),
                tr("pagesize.desc"),
                self.page_size,
            )
        )
        self.body.addWidget(section)

    def _build_storage(self) -> None:
        section = Section(tr("group.storage"), self.view)
        open_settings = PushButton(FluentIcon.FOLDER, tr("store.open"))
        open_settings.clicked.connect(lambda: open_path(config_dir()))
        row = OptionRow(
            FluentIcon.SETTING, tr("store.settings"), str(config_dir()), open_settings
        )
        row.description.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        section.add(row)

        open_work = PushButton(FluentIcon.FOLDER, tr("store.open"))
        open_work.clicked.connect(self._open_work)
        delete_work = PushButton(FluentIcon.DELETE, tr("store.delete"))
        delete_work.clicked.connect(self._delete_work)
        section.add(
            OptionRow(
                FluentIcon.ZIP_FOLDER,
                tr("store.work"),
                tr("store.work.desc"),
                open_work,
                delete_work,
            )
        )
        self.body.addWidget(section)

    def _build_about(self) -> None:
        section = Section(tr("group.about"), self.view)
        link = HyperlinkButton(SOURCE_URL, tr("about.source"))
        section.add(
            OptionRow(
                FluentIcon.INFO,
                tr("about.title", version=__version__),
                tr("about.desc"),
                link,
            )
        )
        self.body.addWidget(section)

    # ---- behaviour -----------------------------------------------------

    def _key_location(self) -> str:
        if not self.secrets.secure:
            return tr("where.file")
        if sys.platform == "win32":
            return tr("where.windows")
        if "kwallet" in type(self.secrets._keyring).__module__:
            return tr("where.kwallet")
        return tr("where.keyring")

    def _on_language(self) -> None:
        self.settings.language = self.language.currentData()
        self.settings.save()
        self.language_changed.emit(self.settings.language)

    def _on_theme(self) -> None:
        self.settings.theme = self.theme.currentData()
        self.settings.save()
        self.theme_changed.emit(self.settings.theme)

    def _on_accent(self) -> None:
        self.settings.accent = self.accent.currentData()
        self.settings.save()
        self.accent_changed.emit(self.settings.accent)

    def _save_speed(self) -> None:
        s = self.settings
        s.max_jobs = self.parallel.value()
        s.workers = self.requests.value()
        s.page_size = self.page_size.currentData()
        s.save()
        self.changed.emit()

    def _open_work(self) -> None:
        work_root().mkdir(parents=True, exist_ok=True)
        open_path(work_root())

    def _notify(self, kind, text: str) -> None:
        kind("", text, duration=3000, position=InfoBarPosition.TOP, parent=self)

    def _delete_work(self) -> None:
        if self.jobs is not None and self.jobs.active():
            self._notify(InfoBar.warning, tr("store.busy"))
            return
        box = MessageBox(
            tr("store.confirm.title"), tr("store.confirm.body"), self.window()
        )
        box.yesButton.setText(tr("store.delete"))
        box.cancelButton.setText(tr("common.cancel"))
        if not box.exec():
            return
        shutil.rmtree(work_root(), ignore_errors=True)
        self._notify(InfoBar.success, tr("store.deleted"))
