"""Frozen entry point of the command line (kitab-cli.exe), shipped beside the app."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

    from kitab.cli import main

    raise SystemExit(main())
