"""The main window: navigation between Translate, Jobs and Settings."""

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
    def __init__(self, settings: Settings, secrets: SecretStore):
        super().__init__()
        self.settings = settings
        self.secrets = secrets
        self.jobs = JobManager(settings.max_jobs, self)

        self.translate_page = TranslatePage(settings, secrets, self.jobs, self)
        self.jobs_page = JobsPage(self.jobs, self)
        self.settings_page = SettingsPage(settings, secrets, self)

        self.addSubInterface(self.translate_page, FluentIcon.LANGUAGE, "Translate")
        self.addSubInterface(self.jobs_page, FluentIcon.HISTORY, "Jobs")
        self.addSubInterface(
            self.settings_page,
            FluentIcon.SETTING,
            "Settings",
            NavigationItemPosition.BOTTOM,
        )

        self.translate_page.submitted.connect(self._on_submitted)
        self.translate_page.open_settings.connect(
            lambda: self.switchTo(self.settings_page)
        )
        self.settings_page.theme_changed.connect(apply_theme)
        self.settings_page.saved.connect(self._on_settings_saved)

        self.setWindowTitle("Kitab — books into Arabic")
        self.setWindowIcon(QIcon(str(ASSETS / "icon.svg")))
        self.resize(1080, 760)
        self.setMinimumSize(860, 600)
        screen = self.screen().availableGeometry()
        self.move(
            screen.x() + (screen.width() - self.width()) // 2,
            screen.y() + (screen.height() - self.height()) // 2,
        )

    def _on_submitted(self, count: int) -> None:
        self.switchTo(self.jobs_page)
        InfoBar.success(
            "Queued",
            f"{count} book{'s' * (count != 1)} added to the queue.",
            duration=2500,
            position=InfoBarPosition.TOP,
            parent=self.jobs_page,
        )

    def _on_settings_saved(self) -> None:
        self.jobs.set_max_parallel(self.settings.max_jobs)
        self.jobs_page._refresh_counts()
        self.translate_page.reload_engine()

    def closeEvent(self, event) -> None:
        active = self.jobs.active()
        if active:
            box = MessageBox(
                "Stop and quit?",
                f"{len(active)} book{'s are' if len(active) != 1 else ' is'} still "
                "in the queue. Quitting stops them; each one resumes from where it "
                "stopped when you queue it again.",
                self,
            )
            box.yesButton.setText("Stop and quit")
            box.cancelButton.setText("Keep working")
            if not box.exec():
                event.ignore()
                return
        self.settings.save()
        self.jobs.shutdown()
        super().closeEvent(event)
