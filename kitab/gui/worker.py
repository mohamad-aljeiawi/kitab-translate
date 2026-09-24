"""The job process: one book, start to finish, with no window.

Every book runs in a process of its own rather than a thread. OCR is CPU-bound, so
threads would queue behind one another on the interpreter lock; a process can be
stopped outright if it stops listening; and a crash in a native library takes down
one book instead of the application.

The process talks to the window through one multiprocessing queue, as plain tuples:

    ("progress", job_id, stage, done, total)
    ("log",      job_id, level, message)
    ("done",     job_id, summary_dict)
    ("failed",   job_id, message)
    ("cancelled", job_id)

This module must not import Qt -- it is what every job process loads.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback

# Loggers from HTTP clients that would put a line per request into the job log.
_QUIET = ("httpx", "httpcore", "openai", "urllib3", "PIL", "RapidOCR", "onnxruntime")


class _QueueHandler(logging.Handler):
    def __init__(self, events, job_id: int):
        super().__init__(logging.INFO)
        self.events = events
        self.job_id = job_id

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.events.put(("log", self.job_id, record.levelname, self.format(record)))
        except Exception:
            pass


def run_job(job_id: int, request: dict, events, cancel) -> None:
    """Process entry point. ``request`` holds source, out_dir, work_dir, options."""
    _ensure_streams()

    root = logging.getLogger()
    root.handlers[:] = [_QueueHandler(events, job_id)]
    root.setLevel(logging.INFO)
    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)

    from kitab import progress
    from kitab.errors import Cancelled, KitabError
    from kitab.pipeline import Options, translate_book

    progress.install(
        sink=lambda stage, done, total: events.put(
            ("progress", job_id, stage, done, total)
        ),
        cancelled=cancel.is_set,
    )

    try:
        result = translate_book(
            request["source"],
            request["out_dir"],
            work_dir=request["work_dir"],
            options=Options(**request["options"]),
        )
    except Cancelled:
        events.put(("cancelled", job_id))
        return
    except KitabError as e:
        events.put(("failed", job_id, str(e)))
        return
    except Exception as e:
        logging.getLogger("kitab").error("%s", traceback.format_exc())
        events.put(("failed", job_id, f"{type(e).__name__}: {e}"))
        return

    report = result.report
    events.put(
        (
            "done",
            job_id,
            {
                "epub": str(result.epub_path) if result.epub_path else "",
                "pdf": str(result.pdf_path) if result.pdf_path else "",
                "markdown": str(result.markdown_path),
                "html": str(result.html_path),
                "segments": report.segments_total,
                "translated": report.segments_translated,
                "cached": report.segments_cached,
                "failed": report.segments_failed,
                "warnings": list(report.warnings),
            },
        )
    )


def _ensure_streams() -> None:
    """A windowed executable starts with no stdout or stderr at all.

    Anything that writes to them -- a progress bar in a dependency, a stray print --
    would raise. Point them at the null device instead.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
