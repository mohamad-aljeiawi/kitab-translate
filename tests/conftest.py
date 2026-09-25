"""Shared test setup.

Qt tests run offscreen: no window appears on a developer's screen, and CI runners
have no display at all. Set before anything imports Qt.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
