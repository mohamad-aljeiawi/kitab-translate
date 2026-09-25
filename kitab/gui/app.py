"""Entry point of the desktop application: ``kitab-gui``, or the packaged executable."""

from __future__ import annotations

import multiprocessing
import os
import sys

from PySide6.QtCore import QObject, Qt, QTranslator
from PySide6.QtWidgets import QApplication


class Controller(QObject):
    """Owns what outlives a window: settings, keys, the job queue, the language.

    Changing the language rebuilds the window, since every label is set once when
    a page is built. The queue lives here, not in the window, so books already
    translating carry on untouched while the text around them changes.
    """

    def __init__(self, app: QApplication, settings, secrets):
        super().__init__()
        from .jobs import JobManager
        from .theme import ThemeManager

        self.app = app
        self.settings = settings
        self.secrets = secrets
        self.jobs = JobManager(settings.max_jobs)
        self._qt_translator: QTranslator | None = None
        self._apply_language(settings.language)
        self.theme = ThemeManager(app, settings)
        self.theme.apply()
        self.window = self._make_window()
        self.window.center()

    def _apply_language(self, preference: str) -> None:
        from .i18n import is_rtl, resolve, set_language

        set_language(resolve(preference))
        self.app.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
            if is_rtl()
            else Qt.LayoutDirection.LeftToRight
        )
        # The widget library's own words (OK, Cancel, calendar names) come with an
        # Arabic translation; swap it in or out with ours.
        if self._qt_translator is not None:
            self.app.removeTranslator(self._qt_translator)
            self._qt_translator = None
        if is_rtl():
            translator = QTranslator(self.app)
            if translator.load(":/qfluentwidgets/i18n/qfluentwidgets.ar_AR.qm"):
                self.app.installTranslator(translator)
                self._qt_translator = translator

    def _make_window(self):
        from .main_window import MainWindow

        window = MainWindow(self.settings, self.secrets, self.jobs)
        window.settings_page.language_changed.connect(self.switch_language)
        window.settings_page.theme_changed.connect(lambda _: self.theme.apply())
        window.settings_page.accent_changed.connect(lambda _: self.theme.apply())
        self.theme.attach(window)
        return window

    def switch_language(self, preference: str) -> None:
        old = self.window
        pending = old.translate_page.pending_files()
        geometry = old.saveGeometry()

        self._apply_language(preference)
        new = self._make_window()
        new.restoreGeometry(geometry)
        new.translate_page.add_files(pending)
        new.switchTo(new.settings_page)
        new.show()

        old.replacing = True
        old.close()
        old.deleteLater()
        self.window = new


def main() -> int:
    # First, before anything else: in a frozen executable every job process starts
    # as another copy of this program, and this is where it turns into a worker
    # instead of opening a second window.
    multiprocessing.freeze_support()

    from .worker import _ensure_streams

    _ensure_streams()

    if sys.platform == "win32":
        # Without an explicit ID Windows groups the window under python.exe and shows
        # its icon in the taskbar when running from source.
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("kitab.gui")
        except Exception:
            pass

    from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Kitab")
    app.setOrganizationName("kitab")
    # Matches kitab.desktop, so Wayland compositors find the icon and group windows.
    app.setDesktopFileName("kitab")

    from .paths import ASSETS, FONTS
    from .settings import SecretStore, Settings

    app.setWindowIcon(QIcon(str(ASSETS / "icon.svg")))
    # Book titles and the Arabic interface need an Arabic font. A minimal Linux
    # install may have none, so the one the EPUB embeds is registered here too.
    for font in FONTS.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(font))

    controller = Controller(app, Settings.load(), SecretStore())
    controller.window.show()

    files = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if files:
        controller.window.translate_page.add_files(files)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
