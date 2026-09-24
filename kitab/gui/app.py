"""Entry point of the desktop application: ``kitab-gui``, or the packaged executable."""

from __future__ import annotations

import multiprocessing
import os
import sys


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

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Kitab")
    app.setOrganizationName("kitab")
    # Matches kitab.desktop, so Wayland compositors find the icon and group windows.
    app.setDesktopFileName("kitab")

    from .main_window import MainWindow, apply_theme
    from .paths import ASSETS, FONTS
    from .settings import SecretStore, Settings

    app.setWindowIcon(QIcon(str(ASSETS / "icon.svg")))
    # Book titles and log lines are often Arabic. A minimal Linux install may have
    # no Arabic font at all, so the one the EPUB embeds is registered here too.
    for font in FONTS.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(font))

    settings = Settings.load()
    apply_theme(settings.theme)
    window = MainWindow(settings, SecretStore())
    window.show()

    files = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if files:
        window.translate_page.add_files(files)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
