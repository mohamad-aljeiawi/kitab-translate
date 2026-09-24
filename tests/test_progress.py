"""Progress events and cooperative cancellation, in-process."""

import pytest

from kitab import cache, progress
from kitab.errors import Cancelled
from kitab.pipeline import Options, translate_book
from kitab.translate.registry import ENGINES

from gui_fakes import SlowFake

BOOK = "# Title\n\n" + "\n\n".join(f"Paragraph number {i}." for i in range(12))


@pytest.fixture(autouse=True)
def fake_engine():
    db = cache.init_test_db()
    ENGINES[SlowFake.name] = SlowFake
    yield
    ENGINES.pop(SlowFake.name, None)
    progress.install()
    cache.clean_test_db(db)


def _book(tmp_path):
    source = tmp_path / "book.md"
    source.write_text(BOOK, encoding="utf-8")
    return source


def _options(**kw):
    return Options(service=SlowFake.name, glossary=False, embed_fonts=False, **kw)


def test_stages_arrive_in_order_and_translate_counts_every_segment(tmp_path):
    events = []
    progress.install(sink=lambda *e: events.append(e))

    result = translate_book(_book(tmp_path), tmp_path / "out", options=_options())

    stages = []
    for stage, _, _ in events:
        if not stages or stages[-1] != stage:
            stages.append(stage)
    assert stages == ["extract", "translate", "rebuild", "epub"]

    translate = [(d, t) for s, d, t in events if s == "translate"]
    total = translate[0][1]
    assert total == len(result.document.segments)
    assert translate[-1] == (total, total)


def test_cancel_stops_between_batches_and_the_rerun_resumes(tmp_path):
    source = _book(tmp_path)
    done = []

    def sink(stage, count, total):
        if stage == "translate":
            done.append(count)

    progress.install(sink=sink, cancelled=lambda: len(done) > 4)
    with pytest.raises(Cancelled):
        translate_book(source, tmp_path / "out", options=_options())
    stopped_at = max(done)
    assert 0 < stopped_at < 13

    # Nothing is saved for the stage, but every finished batch is in the cache, so
    # the second run serves those without asking the engine again.
    served = []
    progress.install(sink=lambda s, d, t: served.append((s, d, t)))
    result = translate_book(source, tmp_path / "out", options=_options())
    assert result.report.segments_failed == 0
    first = next(e for e in served if e[0] == "translate" and e[1] > 0)
    assert first[1] >= stopped_at


def test_without_a_sink_nothing_is_required(tmp_path):
    progress.install()
    result = translate_book(_book(tmp_path), tmp_path / "out", options=_options())
    assert result.epub_path and result.epub_path.exists()
