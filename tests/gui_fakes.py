"""A fake engine for tests that run real job processes.

A spawned process imports modules afresh, so a fake registered inside a test never
reaches it. The job manager is given :func:`run_fake_job` as its process entry point
instead; it registers the fake in the child, isolates the cache, then runs the real
worker.
"""

import os
import time

from kitab.md.mask import CURLY
from kitab.translate.base import BaseTranslator

#: Seconds each segment takes, read in the child from the environment.
DELAY_ENV = "KITAB_TEST_SEGMENT_DELAY"


class SlowFake(BaseTranslator):
    name = "slowfake"
    mask_style = CURLY
    batch_size = 1
    default_workers = 1
    default_qps = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.delay = float(os.environ.get(DELAY_ENV, "0"))

    def do_translate(self, text: str) -> str:
        time.sleep(self.delay)
        return "AR " + text


def run_fake_job(job_id, request, events, cancel):
    from kitab import cache
    from kitab.gui import worker
    from kitab.translate.registry import ENGINES

    ENGINES[SlowFake.name] = SlowFake
    cache.init_test_db()
    worker.run_job(job_id, request, events, cancel)
