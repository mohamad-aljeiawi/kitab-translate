"""The command line itself: output that cannot crash, and the --check report."""

import os
import subprocess
import sys


def _run(*args, encoding="cp1252", cwd=None):
    env = dict(os.environ, PYTHONIOENCODING=encoding, PYTHONUTF8="0")
    return subprocess.run(
        [sys.executable, "-m", "kitab.cli", *args],
        capture_output=True,
        env=env,
        cwd=cwd,
        timeout=120,
    )


def test_arabic_names_do_not_crash_a_legacy_code_page(tmp_path):
    """Piped output on Windows is cp1252, which has no Arabic letters.

    Printing a book called "علم المناعة.md" raised UnicodeEncodeError and ended
    the program; the name is now printed with replacement characters instead.
    """
    book = tmp_path / "علم المناعة.md"
    book.write_text("# Title\n\nText.", encoding="utf-8")
    result = _run(str(book), "--inspect")
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"markdown" in result.stdout


def test_check_reports_every_part(tmp_path):
    result = _run("--check", encoding="utf-8")
    out = result.stdout.decode("utf-8")
    for part in ("OCR", "Fast PDF extractor", "PDF output"):
        assert part in out
    # Installed parts either work or are reported; missing ones never fail it.
    assert ("FAILED" in out) == (result.returncode == 1)
