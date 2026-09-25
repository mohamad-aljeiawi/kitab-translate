"""Colours from the system: which shade, readable text, and following changes live."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("qfluentwidgets")

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kitab.gui import theme  # noqa: E402
from kitab.gui.settings import Settings  # noqa: E402

# A Windows AccentPalette: Light3, Light2, Light1, base, Dark1, Dark2, Dark3, spare.
PALETTE = bytes.fromhex(
    "99ebff00"
    "4cc2ff00"
    "0091f800"
    "0078d400"
    "0067c000"
    "003e9200"
    "001a6800"
    "f7630c00"
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_windows_shade_follows_what_windows_apps_use(monkeypatch):
    monkeypatch.setattr(theme.sys, "platform", "win32")
    monkeypatch.setattr(theme, "_windows_accent_palette", lambda: PALETTE)
    # Dark mode takes the lighter Light2, light mode the deeper Dark1.
    assert theme.system_accent(dark=True).name() == "#4cc2ff"
    assert theme.system_accent(dark=False).name() == "#0067c0"


@pytest.mark.parametrize(
    "accent, dark",
    [("#ffd6e7", False), ("#fff59d", False), ("#1a1a40", True), ("#3b0a0a", True)],
)
def test_text_on_the_accent_is_always_readable(accent, dark):
    fixed = theme.readable(QColor(accent), dark)
    text = QColor("black") if dark else QColor("white")
    assert theme.contrast(fixed, text) >= theme.MIN_CONTRAST
    # Same colour family, not swapped for a different one.
    assert abs(fixed.hslHue() - QColor(accent).hslHue()) <= 2 or fixed.hslHue() < 0


def test_an_accent_that_is_already_readable_is_left_alone():
    blue = QColor("#0067c0")
    assert theme.readable(blue, dark=False) == blue


BLUE = [QColor("#" + PALETTE.hex()[8 * i : 8 * i + 6]) for i in range(7)]
GREY = [
    QColor(c)
    for c in (
        "#dfdedc",
        "#a6a5a1",
        "#686562",
        "#4c4a48",
        "#413f3d",
        "#272524",
        "#100d0d",
    )
]


class FakeWindow:
    def __init__(self):
        self.mica = []

    def setMicaEffectEnabled(self, on):  # noqa: N802 (mirrors the Qt method)
        self.mica.append(on)

    @property
    def destroyed(self):
        class _Signal:
            def connect(self, _slot):
                pass

        return _Signal()


@pytest.fixture
def manager(app, monkeypatch):
    system = {"dark": False, "shades": BLUE, "transparent": True}
    calls = {"theme": [], "color": []}
    monkeypatch.setattr(theme, "system_is_dark", lambda: system["dark"])
    monkeypatch.setattr(theme, "system_palette", lambda: system["shades"])
    monkeypatch.setattr(theme, "system_transparency", lambda: system["transparent"])
    monkeypatch.setattr(theme, "setTheme", lambda t: calls["theme"].append(t))
    monkeypatch.setattr(
        theme, "setThemeColor", lambda c: calls["color"].append(c.name())
    )

    def make(**settings):
        return theme.ThemeManager(app, Settings(**settings))

    yield make, system, calls
    theme.reset()


def test_system_accent_and_mode_are_applied_and_followed(manager):
    make, system, calls = manager
    m = make(theme="auto", accent="system")
    window = FakeWindow()
    m.attach(window)

    m.apply()
    assert calls["theme"] == [theme.Theme.LIGHT]
    # Light mode: buttons take Dark1, hover the base, pressed Light1 -- as Windows.
    assert theme.ThemeColor.PRIMARY.color().name() == "#0067c0"
    assert theme.ThemeColor.LIGHT_1.color().name() == "#0078d4"
    assert theme.ThemeColor.LIGHT_2.color().name() == "#0091f8"

    # Nothing changed: the two-second poll must not repaint anything.
    m.apply()
    assert len(calls["theme"]) == 1 and len(calls["color"]) == 1

    # Windows switches to dark mode: buttons take Light2, hover Light1.
    system["dark"] = True
    m.apply()
    assert calls["theme"][-1] == theme.Theme.DARK
    assert theme.ThemeColor.PRIMARY.color().name() == "#4cc2ff"
    assert theme.ThemeColor.DARK_1.color().name() == "#0091f8"

    # ...and turns transparency effects off.
    system["transparent"] = False
    m.apply()
    assert window.mica[-1] is False


def test_a_grey_accent_stays_grey_in_dark_mode(manager):
    """The library alone would push it to full brightness: #fffef9."""
    make, system, _ = manager
    system["shades"], system["dark"] = GREY, True
    make(theme="auto", accent="system").apply()
    assert theme.ThemeColor.PRIMARY.color().name() == "#a6a5a1"


def test_kitab_colour_and_fixed_mode_ignore_the_system(manager):
    make, system, calls = manager
    system["dark"] = True
    make(theme="light", accent="kitab").apply()
    assert calls["theme"] == [theme.Theme.LIGHT]
    expected = theme.role_colors(
        theme.palette_from(QColor(theme.KITAB_ACCENT)), dark=False
    )[theme.ThemeColor.PRIMARY]
    assert theme.ThemeColor.PRIMARY.color().name() == expected


def test_without_an_applied_palette_the_library_formula_is_used(app):
    theme.reset()
    assert theme.ThemeColor.PRIMARY.color().isValid()


def test_accent_setting_survives_a_reload(tmp_path):
    path = tmp_path / "gui.json"
    Settings(accent="kitab").save(path)
    assert Settings.load(path).accent == "kitab"
    path.write_text('{"accent": "rainbow"}', encoding="utf-8")
    assert Settings.load(path).accent == "system"
