"""Where the desktop app keeps things, on Windows and on Linux.

``platformdirs`` answers the per-OS question once: settings go to ``%APPDATA%\\kitab``
or ``~/.config/kitab``, work files to ``%LOCALAPPDATA%\\kitab\\Cache`` or
``~/.cache/kitab``. Bundled files are found relative to the package, which is also
where PyInstaller puts them, so there is no frozen/unfrozen branch here.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import platformdirs

APP = "kitab"
ASSETS = Path(__file__).parent / "assets"
FONTS = Path(__file__).parent.parent / "render" / "assets" / "fonts"


def config_dir() -> Path:
    return platformdirs.user_config_path(APP, appauthor=False, roaming=True)


def cache_dir() -> Path:
    return platformdirs.user_cache_path(APP, appauthor=False)


def work_root() -> Path:
    return cache_dir() / "work"


def work_dir_for(source: Path) -> Path:
    """A stable work directory per source file.

    Stable so that a cancelled or crashed book resumes on the next run; keyed by the
    full path as well as the name so two ``book.pdf`` files in different folders do
    not share one.
    """
    resolved = os.path.normcase(str(Path(source).resolve())).encode("utf-8")
    digest = hashlib.sha1(resolved).hexdigest()[:10]
    return work_root() / f"{Path(source).stem[:60]}-{digest}"
