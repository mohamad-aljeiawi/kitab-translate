"""Frozen entry point of the desktop app (kitab.exe / the AppImage)."""

import multiprocessing

if __name__ == "__main__":
    # Every job process re-runs this executable; freeze_support turns those runs
    # into workers before any window code is imported.
    multiprocessing.freeze_support()

    from kitab.gui.app import main

    raise SystemExit(main())
