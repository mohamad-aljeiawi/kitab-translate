"""The main window: navigation between Translate, My translations and Settings."""

from __future__ import annotations

from PySide6.QtGui import QIcon
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    NavigationItemPosition,
    Theme,
    setTheme,
)

from .i18n import plural, tr
from .jobs import JobManager
from .pages.jobs import JobsPage
from .pages.settings import SettingsPage
from .pages.translate import TranslatePage
from .paths import ASSETS
from .settings import SecretStore, Settings

_THEMES = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}


def apply_theme(name: str) -> None:
    setTheme(_THEMES.get(name, Theme.AUTO))


class MainWindow(FluentWindow):
    def __init__(self, settings: Settings, secrets: SecretStore, jobs: JobManager):
        super().__init__()
        self.settings = settings
        self.secrets = secrets
        self.jobs = jobs
        #: Set when the window is being replaced (language change), not closed.
        self.replacing = False

        self.translate_page = TranslatePage(settings, secrets, jobs, self)
        self.jobs_page = JobsPage(jobs, self)
        self.settings_page = SettingsPage(settings, secrets, jobs, self)

        self.addSubInterface(
            self.translate_page, FluentIcon.LANGUAGE, tr("nav.translate")
        )
        self.addSubInterface(self.jobs_page, FluentIcon.LIBRARY, tr("nav.jobs"))
        self.addSubInterface(
            self.settings_page,
            FluentIcon.SETTING,
            tr("nav.settings"),
            NavigationItemPosition.BOTTOM,
        )

        self.translate_page.submitted.connect(self._on_submitted)
        self.translate_page.open_settings.connect(
            lambda: self.switchTo(self.settings_page)
        )
        self.jobs_page.go_translate.clicked.connect(
            lambda: self.switchTo(self.translate_page)
        )
        self.settings_page.changed.connect(self._on_settings_changed)

        self.setWindowTitle(tr("app.title"))
        self.setWindowIcon(QIcon(str(ASSETS / "icon.svg")))
        self.resize(1080, 760)
        self.setMinimumSize(720, 560)

    def center(self) -> None:
        screen = self.screen().availableGeometry()
        self.move(
            screen.x() + (screen.width() - self.width()) // 2,
            screen.y() + (screen.height() - self.height()) // 2,
        )

    def _on_submitted(self, count: int) -> None:
        self.switchTo(self.jobs_page)
        InfoBar.success(
            tr("queued.title"),
            plural("books.started", count),
            duration=2500,
            position=InfoBarPosition.TOP,
            parent=self.jobs_page,
        )

    def _on_settings_changed(self) -> None:
        self.jobs.set_max_parallel(self.settings.max_jobs)
        self.jobs_page.refresh_counts()
        self.translate_page.reload_engine()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.replacing:
            super().closeEvent(event)
            return
        active = self.jobs.active()
        if active:
            box = MessageBox(tr("quit.title"), tr("quit.body", n=len(active)), self)
            box.yesButton.setText(tr("quit.yes"))
            box.cancelButton.setText(tr("quit.no"))
            if not box.exec():
                event.ignore()
                return
        self.settings.save()
        self.jobs.shutdown()
        super().closeEvent(event)
