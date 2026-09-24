# PyInstaller spec for the desktop build, Windows and Linux alike.
#
# Run it through packaging/build.py, which prepares the icons and the OCR models
# first. One folder, not one file: a one-file build unpacks ~250 MB to a temp
# directory on every launch, and the ONNX models make that slow enough to notice.
#
# Two executables share the folder: `kitab` (the window) and `kitab-cli` (the
# command line, with a console), so the installed app is also the CLI.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
BUILD = ROOT / "build"
WINDOWS = sys.platform == "win32"

datas = [
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE.md"), "."),
]
# Templates, stylesheet, the Arabic font and the app icon.
datas += collect_data_files("kitab")
# The ONNX models, downloaded into the package by build.py before this runs.
datas += collect_data_files("rapidocr")
# PyMuPDF's layout analyser, which pymupdf4llm (the "fast" extractor) loads on
# import: its ONNX models and their YAML configs. Not its C headers.
datas += collect_data_files("pymupdf", includes=["layout/**"])
# Playwright's Node driver. No browser: PDFs print with the Edge, Chrome or
# Chromium already on the machine (kitab.render.pdf_out.system_browser).
datas += collect_data_files("playwright", includes=["driver/**"])
# Theme stylesheets and icons of the widget library.
datas += collect_data_files("qfluentwidgets")

hiddenimports = (
    collect_submodules("kitab")
    # rapidocr picks its inference backend by name at run time. Only the ONNX
    # Runtime backend ships; the others need frameworks the build leaves out.
    + collect_submodules(
        "rapidocr",
        filter=lambda name: not any(
            other in name for other in ("openvino", "paddle", "torch", "tensorrt", "mnn")
        ),
    )
    + ["pymupdf4llm", "keyring.backends"]
)

excludes = [
    # The heavy extras stay CLI-only: marker and manga-ocr bring torch (2 GB+).
    "torch", "torchvision", "transformers", "marker", "manga_ocr",
    # Nothing here uses these; some get pulled in transitively by optional imports.
    "tkinter", "matplotlib", "IPython", "jupyter", "pytest", "black",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
]

icon = str(BUILD / ("icon.ico" if WINDOWS else "icon.png"))

# Files that arrive as dependencies of dependencies and are never used: OpenCV's
# video decoder (rapidocr reads still images), Qt's software OpenGL, and the Quick,
# QML and PDF libraries that unused Qt plugins drag in. ~75 MB together.
_UNUSED = (
    "opencv_videoio_ffmpeg",
    "opengl32sw",
    "qt6quick",
    "qt6qml",
    "qt6pdf",
    "qt6virtualkeyboard",
    "platforminputcontexts",
    "imageformats/qpdf",
    "imageformats\\qpdf",
    "pyside6/translations",
    "pyside6\\translations",
)


def _trim(entries):
    return [e for e in entries if not any(u in e[0].lower() for u in _UNUSED)]


def analysis(script):
    a = Analysis(
        [str(ROOT / "packaging" / script)],
        pathex=[str(ROOT)],
        datas=datas,
        hiddenimports=hiddenimports,
        excludes=excludes,
        noarchive=False,
    )
    a.binaries = _trim(a.binaries)
    a.datas = _trim(a.datas)
    return a


gui = analysis("entry_gui.py")
gui_exe = EXE(
    PYZ(gui.pure),
    gui.scripts,
    [],
    exclude_binaries=True,
    name="kitab",
    console=False,
    icon=icon,
    version=str(BUILD / "version_info.txt") if WINDOWS else None,
)

cli = analysis("entry_cli.py")
cli_exe = EXE(
    PYZ(cli.pure),
    cli.scripts,
    [],
    exclude_binaries=True,
    name="kitab-cli",
    console=True,
    icon=icon,
    version=str(BUILD / "version_info.txt") if WINDOWS else None,
)

COLLECT(
    gui_exe,
    gui.binaries,
    gui.datas,
    cli_exe,
    cli.binaries,
    cli.datas,
    name="kitab",
)
