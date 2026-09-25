"""The window: both languages, narrow widths, and switching language live.

These build real widgets offscreen. They guard the things that broke before the
redesign or would break silently: a label key missing in one language, controls
overlapping when the window narrows, a page taller than its content, and the
language switch dropping books that were already translating.
"""

import re
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("qfluentwidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kitab.gui import i18n  # noqa: E402

GUI = Path(__file__).parent.parent / "kitab" / "gui"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from kitab.gui import paths
    from kitab.gui import settings as settings_module

    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(settings_module, "config_dir", lambda: tmp_path / "config")
    yield tmp_path
    i18n.set_language("en")


def _settle(app, seconds=0.3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()


def _controller(app, tmp_path, language="en"):
    from kitab.gui.app import Controller
    from kitab.gui.settings import SecretStore, Settings

    settings = Settings(language=language)
    secrets = SecretStore(fallback=tmp_path / "secrets.json", use_keyring=False)
    controller = Controller(app, settings, secrets)
    controller.window.show()
    _settle(app)
    return controller


# ---- the string table ------------------------------------------------------


def test_every_string_exists_in_both_languages():
    for key in i18n.keys():
        for language in ("en", "ar"):
            i18n.set_language(language)
            assert i18n.tr(key).strip("‏").strip(), f"{key} is empty in {language}"
    i18n.set_language("en")


def test_every_key_the_code_uses_is_defined():
    used = set()
    for source in GUI.rglob("*.py"):
        used |= set(re.findall(r'\btr\(\s*"([a-z0-9_.]+)"', source.read_text("utf-8")))
    # Keys built at run time from engine, level, language and stage names.
    from kitab.gui.ui import ENGINES_SHOWN, SOURCE_LANGUAGES
    from kitab.translate.openai_like import REASONING_EFFORTS

    used |= {f"engine.{e}" for e in ENGINES_SHOWN}
    used |= {f"thinking.{level}" for level in REASONING_EFFORTS}
    used |= {f"source.{code}" for code in SOURCE_LANGUAGES}
    used |= {f"book.{kind}" for kind in ("epub", "html", "markdown", "text")}
    used |= {f"stage.{s}" for s in ("extract", "ocr", "translate", "rebuild", "epub")}
    missing = used - i18n.keys()
    assert not missing, f"used but not defined: {sorted(missing)}"


def test_arabic_plurals_follow_arabic_grammar():
    i18n.set_language("ar")
    forms = [i18n.plural("books.ready", n).strip("‏") for n in (1, 2, 5, 11, 100)]
    i18n.set_language("en")
    assert forms == [
        "كتاب واحد جاهز",
        "كتابان جاهزان",
        "5 كتب جاهزة",
        "11 كتابًا جاهزًا",
        "100 كتاب جاهز",
    ]
    assert i18n.plural("books.ready", 1) == "1 book ready"
    assert i18n.plural("books.ready", 3) == "3 books ready"


def test_arabic_text_is_forced_right_to_left_and_file_names_stay_whole():
    i18n.set_language("ar")
    # Opens with a Latin word; without the mark Qt lays the line out left to right.
    assert i18n.tr("formats.desc").startswith("‏")
    i18n.set_language("en")
    assert not i18n.tr("formats.desc").startswith("‏")
    assert i18n.file_name("علم المناعة 2.pdf") == "علم المناعة 2‎.pdf"
    assert i18n.file_name("book 2.pdf") == "book 2.pdf"


# ---- layout ------------------------------------------------------------------


def test_rows_put_controls_under_the_text_when_narrow(app, isolated):
    from qfluentwidgets import ComboBox, FluentIcon

    from kitab.gui.widgets import OptionRow

    combo = ComboBox()
    combo.addItem("A fairly long option label")
    combo.setMinimumWidth(240)
    row = OptionRow(FluentIcon.ROBOT, "Title", "A sentence that explains it.", combo)
    row.show()
    row.resize(1000, 80)
    _settle(app, 0.1)
    assert row._content.direction().name == "LeftToRight"
    row.resize(420, 80)
    _settle(app, 0.1)
    assert row._content.direction().name == "TopToBottom"


@pytest.mark.parametrize("language", ["en", "ar"])
def test_pages_are_as_tall_as_their_content_at_any_width(app, isolated, language):
    """Wrapped labels used to inflate the page into screens of empty space."""
    controller = _controller(app, isolated, language)
    window = controller.window
    page = window.translate_page
    page.more.set_open(True)
    for width in (720, 1080, 1400):
        window.resize(width, 760)
        _settle(app)
        needed = page.body.heightForWidth(page.view.width())
        viewport = page.scroll.viewport().height()
        assert page.view.height() == max(needed, viewport), width
    window.replacing = True
    window.close()


def test_arabic_mirrors_the_whole_window(app, isolated):
    controller = _controller(app, isolated, "ar")
    assert app.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert controller.window.windowTitle().strip("‏").startswith("كتاب")
    controller.window.replacing = True
    controller.window.close()
    controller._apply_language("en")
    assert app.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_switching_language_keeps_the_queue_and_the_chosen_books(app, isolated):
    controller = _controller(app, isolated, "en")
    book = isolated / "book.md"
    book.write_text("# Title\n\nText.", encoding="utf-8")
    controller.window.translate_page.add_files([book])
    jobs_before = controller.jobs
    old_window = controller.window

    controller.window.settings_page.language.setCurrentIndex(
        controller.window.settings_page.language.findData("ar")
    )
    _settle(app)

    assert controller.window is not old_window
    assert controller.jobs is jobs_before
    assert controller.settings.language == "ar"
    assert controller.window.translate_page.pending_files() == [book]
    assert controller.window.settings_page.title.text().strip("‏") == "الإعدادات"
    controller.window.replacing = True
    controller.window.close()


def test_settings_save_as_they_change(app, isolated):
    from kitab.gui.settings import Settings

    controller = _controller(app, isolated, "en")
    page = controller.window.settings_page
    page.parallel.setValue(3)
    page.theme.setCurrentIndex(page.theme.findData("dark"))
    saved = Settings.load(isolated / "config" / "gui.json")
    assert saved.max_jobs == 3
    assert saved.theme == "dark"
    assert controller.jobs.max_parallel == 3
    controller.window.replacing = True
    controller.window.close()


def test_start_is_blocked_until_the_choice_makes_sense(app, isolated):
    controller = _controller(app, isolated, "en")
    page = controller.window.translate_page
    assert not page.start.isEnabled()  # no books

    book = isolated / "book.md"
    book.write_text("# T\n\nx", encoding="utf-8")
    page.add_files([book])
    assert page.start.isEnabled()

    page.pages.setText("1-5, x")
    assert not page.start.isEnabled()
    assert page.summary.text() == i18n.tr("pages.invalid")
    page.pages.setText("1-5,12")
    assert page.start.isEnabled()

    page.epub.setChecked(False)
    page.pdf.setChecked(False)
    assert not page.start.isEnabled()
    controller.window.replacing = True
    controller.window.close()
