"""Colours and window effects, taken from the operating system and kept in step with it.

Three things follow the system, and keep following it while the app is open:

*Light or dark*, when Appearance is "Use the system setting": Qt reports the
system colour scheme and signals when it changes.

*Accent colour*, unless Kitab green is chosen. On Windows it is the seven-shade
palette Windows builds from your accent (Settings > Personalisation > Colours), used
the way Windows' own apps use it: a deeper shade for buttons in light mode, a
lighter one in dark mode, and the neighbouring shades for hover and pressed. On
other systems the palette is built from the desktop's accent (KDE, GNOME), as
Qt reports it.

*Transparency*: the Mica backdrop on Windows 11 is on only while Windows'
"Transparency effects" switch is on.

Windows does not tell a Qt app when the accent or the transparency switch changes,
so those two registry values are read every two seconds and compared with the last
reading; nothing else runs unless they differ. Light/dark arrives as a Qt signal,
and a desktop that pushes a new palette (KDE, GNOME) reaches a hidden watcher.

qfluentwidgets derives every accent shade from one colour, and in dark mode sets
its brightness to the maximum. That is fine for a vivid blue and turns a grey or
dark accent nearly white, which is not what Windows shows. So the shades are
supplied directly: ``ThemeColor.color`` is routed through :func:`_role_color`,
which answers from the palette applied here and falls back to the library's own
formula when none is.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import Theme, ThemeColor, qconfig, setTheme, setThemeColor

#: Kitab's own colour: the green of the app icon.
KITAB_ACCENT = "#17866f"
#: Contrast the button colour must keep against its text (WCAG AA, 4.5:1).
MIN_CONTRAST = 4.5
_POLL_MS = 2000

# A palette is seven shades, lightest first, as Windows stores them.
LIGHT3, LIGHT2, LIGHT1, BASE, DARK1, DARK2, DARK3 = range(7)


# ---- reading the system ----------------------------------------------------


def system_is_dark() -> bool:
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    try:  # a desktop that reports nothing: ask darkdetect, as qfluentwidgets does
        import darkdetect

        return bool(darkdetect.isDark())
    except Exception:
        return False


def _registry(path: str, name: str):
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _windows_accent_palette() -> bytes | None:
    value = _registry(
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent", "AccentPalette"
    )
    return bytes(value) if value is not None and len(value) >= 28 else None


def windows_palette() -> list[QColor] | None:
    """Windows' seven accent shades: 4 bytes each (R, G, B, unused)."""
    if sys.platform != "win32":
        return None
    raw = _windows_accent_palette()
    if raw is None:
        return None
    return [QColor(raw[4 * i], raw[4 * i + 1], raw[4 * i + 2]) for i in range(7)]


def palette_from(color: QColor) -> list[QColor]:
    """Seven shades around one colour, spaced the way Windows spaces its own."""
    return [
        color.lighter(175),
        color.lighter(150),
        color.lighter(125),
        QColor(color),
        color.darker(125),
        color.darker(150),
        color.darker(200),
    ]


def system_palette() -> list[QColor] | None:
    shades = windows_palette()
    if shades is not None:
        return shades
    accent = QGuiApplication.palette().color(QPalette.ColorRole.Accent)
    # Qt fills the role from the style's own default when the desktop sets no
    # accent; that is Qt's colour, not the user's, so it does not count.
    style = (
        QApplication.style()
        if isinstance(QApplication.instance(), QApplication)
        else None
    )
    if style is not None:
        default = style.standardPalette().color(QPalette.ColorRole.Accent)
        if accent == default:
            return None
    return palette_from(accent) if accent.isValid() else None


def button_shade(shades: list[QColor], dark: bool) -> QColor:
    return shades[LIGHT2 if dark else DARK1]


def system_accent(dark: bool) -> QColor | None:
    """The system accent in the shade buttons use for ``dark``."""
    shades = system_palette()
    return button_shade(shades, dark) if shades else None


def _windows_signature() -> tuple:
    """The raw values the poll compares: cheap to read, cheap to compare."""
    return (
        _windows_accent_palette(),
        _registry(
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "EnableTransparency",
        ),
    )


def system_transparency() -> bool:
    if sys.platform != "win32":
        return False
    value = _registry(
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "EnableTransparency",
    )
    return value != 0


# ---- contrast ----------------------------------------------------------------


def _luminance(color: QColor) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.redF())
        + 0.7152 * channel(color.greenF())
        + 0.0722 * channel(color.blueF())
    )


def contrast(a: QColor, b: QColor) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable(accent: QColor, dark: bool) -> QColor:
    """Nudge ``accent`` until the text on it is readable, keeping its hue.

    Filled buttons carry white text in light mode and black text in dark mode.
    """
    text = QColor("black") if dark else QColor("white")
    color = QColor(accent)
    for _ in range(40):
        if contrast(color, text) >= MIN_CONTRAST:
            break
        color = color.lighter(106) if dark else color.darker(106)
    return color


# ---- the colours qfluentwidgets draws with ----------------------------------


def role_colors(shades: list[QColor], dark: bool) -> dict[ThemeColor, str]:
    """Which shade each of the library's colour roles gets.

    Its buttons take PRIMARY at rest; in light mode LIGHT_1 on hover and LIGHT_2
    when pressed, in dark mode DARK_1 and DARK_2. Each maps to the neighbouring
    Windows shade, as a Windows accent button moves one shade per state.
    """
    s = shades
    # Every role a filled button shows at rest, on hover or pressed carries its
    # text, so each is held to the same contrast, not only the resting one.
    if dark:
        roles = {
            ThemeColor.PRIMARY: readable(s[LIGHT2], dark=True),
            ThemeColor.DARK_1: readable(s[LIGHT1], dark=True),
            ThemeColor.DARK_2: readable(s[BASE], dark=True),
            ThemeColor.DARK_3: s[DARK1],
            ThemeColor.LIGHT_1: s[LIGHT3],
            ThemeColor.LIGHT_2: s[LIGHT3].lighter(108),
            ThemeColor.LIGHT_3: s[LIGHT3].lighter(116),
        }
    else:
        roles = {
            ThemeColor.PRIMARY: readable(s[DARK1], dark=False),
            ThemeColor.LIGHT_1: readable(s[BASE], dark=False),
            ThemeColor.LIGHT_2: readable(s[LIGHT1], dark=False),
            ThemeColor.LIGHT_3: s[LIGHT2],
            ThemeColor.DARK_1: s[DARK2],
            ThemeColor.DARK_2: s[DARK3],
            ThemeColor.DARK_3: s[DARK3].darker(120),
        }
    return {role: color.name() for role, color in roles.items()}


_roles: dict[ThemeColor, str] | None = None
_library_color = ThemeColor.color


def _role_color(self: ThemeColor) -> QColor:
    if _roles is not None and self in _roles:
        return QColor(_roles[self])
    return _library_color(self)


ThemeColor.color = _role_color


def reset() -> None:
    """Hand colours back to the library's own formula (tests use this)."""
    global _roles
    _roles = None


# ---- keeping the app in step -----------------------------------------------


class ThemeManager(QObject):
    """Applies the chosen appearance and re-applies it when the system changes."""

    def __init__(self, app: QGuiApplication, settings):
        super().__init__(app)
        self.app = app
        self.settings = settings
        self.windows: list = []
        self._applied: tuple | None = None

        app.styleHints().colorSchemeChanged.connect(lambda _scheme: self.apply())
        # Desktops that push a new palette (KDE, GNOME via the portal) reach every
        # widget; one hidden widget is enough to hear it. An event filter on the
        # application would run Python for every mouse move and paint instead.
        self._watcher = (
            _PaletteWatcher(self.apply) if isinstance(app, QApplication) else None
        )
        if sys.platform == "win32":
            self._signature = _windows_signature()
            self._poll = QTimer(self)
            self._poll.setInterval(_POLL_MS)
            self._poll.timeout.connect(self._poll_windows)
            self._poll.start()

    def _poll_windows(self) -> None:
        signature = _windows_signature()
        if signature != self._signature:
            self._signature = signature
            self.apply()

    def attach(self, window) -> None:
        self.windows = [w for w in self.windows if w is not window] + [window]
        window.destroyed.connect(lambda *_: self._forget(window))
        self._apply_effects(window, system_transparency())

    def _forget(self, window) -> None:
        self.windows = [w for w in self.windows if w is not window]

    def state(self) -> tuple:
        """(dark, the colour of every role, transparency) as they should be now."""
        mode = self.settings.theme
        dark = system_is_dark() if mode == "auto" else mode == "dark"
        shades = system_palette() if self.settings.accent == "system" else None
        if shades is None:
            shades = palette_from(QColor(KITAB_ACCENT))
        roles = role_colors(shades, dark)
        return (
            dark,
            tuple(sorted((r.value, c) for r, c in roles.items())),
            (system_transparency()),
        )

    def apply(self) -> None:
        global _roles
        state = self.state()
        # Setting a theme repaints everything and can itself raise a palette-change
        # event; applying only differences keeps that from looping, and keeps the
        # two-second poll free when nothing has changed.
        if state == self._applied:
            return
        dark, roles, transparent = state
        previous = self._applied
        self._applied = state

        # Keyed by value: ThemeColor defines its own name() method, hiding Enum.name.
        _roles = {ThemeColor(value): color for value, color in roles}
        primary = QColor(_roles[ThemeColor.PRIMARY])
        # Each of setTheme and setThemeColor re-styles every widget. When the mode
        # changes the colours change with it, so store the colour quietly and let
        # the one setTheme pass pick it up; lazy styles hidden pages when shown.
        if previous is None or previous[0] != dark:
            qconfig.set(qconfig.themeColor, primary)
            setTheme(Theme.DARK if dark else Theme.LIGHT, lazy=True)
        elif previous[1] != roles:
            setThemeColor(primary, lazy=True)
        if previous is None or previous[2] != transparent:
            for window in list(self.windows):
                self._apply_effects(window, transparent)

    def _apply_effects(self, window, transparent: bool) -> None:
        if hasattr(window, "setMicaEffectEnabled"):
            window.setMicaEffectEnabled(transparent)


class _PaletteWatcher(QWidget):
    """Never shown; told, like every widget, when the application palette changes."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            QTimer.singleShot(0, self._callback)
        super().changeEvent(event)
