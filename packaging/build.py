"""Build the desktop app for the platform this runs on.

    python packaging/build.py            # everything
    python packaging/build.py --no-installer

Windows  -> dist/Kitab-<v>-windows-x64-setup.exe  (if Inno Setup is installed)
            dist/Kitab-<v>-windows-x64-portable.zip
Linux    -> dist/Kitab-<v>-x86_64.AppImage        (Arch, Ubuntu, Mint, ...)
            dist/Kitab-<v>-linux-x86_64.tar.gz

PyInstaller does not cross-compile, so each platform is built on itself; CI does both
(.github/workflows/release.yml). For an AppImage that runs on every current distro,
build on the oldest one you support -- CI uses Ubuntu 22.04 -- because the result
needs a glibc at least as new as the one it was built against.

The script sets up its own environment, ``.venv-build``, with Python 3.12 (the
version PySide6, onnxruntime and PyInstaller are all most settled on), so your
development environment is never touched. It uses uv when available and falls back
to venv + pip.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
VENV = ROOT / ".venv-build"
PYTHON_VERSION = "3.12"
EXTRAS = "gui,ocr,fast,pdf"
WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
MARKER = "KITAB_BUILD_ENV"

APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/continuous/"
    "appimagetool-{arch}.AppImage"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--no-installer",
        action="store_true",
        help="stop after the PyInstaller folder and the portable archive",
    )
    parser.add_argument(
        "--skip-env",
        action="store_true",
        help="build with the current interpreter instead of .venv-build",
    )
    args = parser.parse_args()

    if not (WINDOWS or LINUX):
        sys.exit("kitab builds for Windows and Linux only")

    if not args.skip_env and os.environ.get(MARKER) != "1":
        return _reexec_in_build_env()

    version = _version()
    print(f"== kitab {version} for {platform.system()} {platform.machine()}")
    BUILD.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)

    _icons()
    if WINDOWS:
        _version_file(version)
    _ocr_models()
    _pyinstaller()

    folder = DIST / "kitab"
    _check_bundle(folder)
    if WINDOWS:
        _portable_zip(folder, version)
        if not args.no_installer:
            _inno_setup(folder, version)
    else:
        _fix_permissions(folder)
        _tarball(folder, version)
        if not args.no_installer:
            _appimage(folder, version)

    print("== done:")
    for item in sorted(DIST.iterdir()):
        if item.is_file():
            print(f"   {item.relative_to(ROOT)}  ({item.stat().st_size / 1e6:.0f} MB)")
    return 0


# ---------------------------------------------------------------- environment


def _venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def _reexec_in_build_env() -> int:
    """Create or refresh .venv-build, then run this script again inside it."""
    uv = shutil.which("uv")
    python = _venv_python()
    if uv:
        if not python.exists():
            _run([uv, "venv", str(VENV), "--python", PYTHON_VERSION])
        _run(
            [uv, "pip", "install", "--python", str(python), "-e", f".[{EXTRAS}]"]
            + ["pyinstaller>=6.10"]
        )
    else:
        if sys.version_info[:2] not in ((3, 11), (3, 12), (3, 13)):
            sys.exit(
                "Install uv (https://docs.astral.sh/uv/) or run this with Python "
                "3.11-3.13; the build environment needs one of them."
            )
        if not python.exists():
            _run([sys.executable, "-m", "venv", str(VENV)])
        _run([str(python), "-m", "pip", "install", "-U", "pip"])
        _run(
            [str(python), "-m", "pip", "install", "-e", f".[{EXTRAS}]"]
            + ["pyinstaller>=6.10"]
        )

    env = dict(os.environ, **{MARKER: "1"})
    return subprocess.call([str(python), __file__, *sys.argv[1:]], env=env, cwd=ROOT)


def _run(command: list[str], **kwargs) -> None:
    print("$", " ".join(str(c) for c in command))
    subprocess.run(command, check=True, cwd=kwargs.pop("cwd", ROOT), **kwargs)


def _version() -> str:
    text = (ROOT / "kitab" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        sys.exit("no __version__ in kitab/__init__.py")
    return match.group(1)


# ---------------------------------------------------------------- inputs


def _icons() -> None:
    """Render the SVG icon to .ico (Windows) and .png (Linux) with Qt itself."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    _app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    renderer = QSvgRenderer(str(ROOT / "kitab" / "gui" / "assets" / "icon.svg"))
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    if not image.save(str(BUILD / "icon.png")):
        sys.exit("could not write build/icon.png")
    if WINDOWS and not image.save(str(BUILD / "icon.ico")):
        sys.exit("could not write build/icon.ico")


def _version_file(version: str) -> None:
    """The Windows file properties dialog (Details tab) reads this."""
    numbers = [int(n) for n in re.findall(r"\d+", version)[:3]]
    numbers += [0] * (4 - len(numbers))
    tuple_ = tuple(numbers)
    (BUILD / "version_info.txt").write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple_}, prodvers={tuple_}),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'mohamad-aljeiawi'),
      StringStruct('FileDescription', 'Kitab - books into Arabic'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('ProductName', 'Kitab'),
      StringStruct('ProductVersion', '{version}'),
      StringStruct('LegalCopyright', 'AGPL-3.0-or-later'),
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ]
)
""",
        encoding="utf-8",
    )


def _ocr_models() -> None:
    """RapidOCR downloads its models on first use; do that now, so they ship."""
    print("== fetching OCR models")
    from rapidocr import RapidOCR

    RapidOCR()


def _pyinstaller() -> None:
    print("== PyInstaller")
    shutil.rmtree(DIST / "kitab", ignore_errors=True)
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(PACKAGING / "kitab.spec"),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "pyinstaller"),
        ]
    )


# Files that are loaded at run time rather than imported, so PyInstaller's import
# analysis cannot see them. A build missing any of them starts fine and then fails
# on the first book that needs it, which is exactly how the layout models went
# missing in 0.2.0. Checked here so that cannot ship again.
REQUIRED = [
    ("kitab/render/assets/template.html.j2", "HTML template"),
    ("kitab/render/assets/fonts/NotoNaskhArabic-Regular.ttf", "Arabic font"),
    ("kitab/gui/assets/icon.svg", "app icon"),
    ("rapidocr/models/*.onnx", "OCR models"),
    ("pymupdf/layout/resources/onnx/*.yaml", "PDF layout model configs"),
    ("pymupdf/layout/resources/onnx/*.onnx", "PDF layout models"),
    ("pymupdf4llm/ocr/ocr_decision_model.onnx", "PDF OCR-decision model"),
    ("playwright/driver/package/cli.js", "Playwright driver"),
]

# The list above only covers files someone thought of, which is how 0.3.0 still
# shipped without pymupdf4llm's OCR-decision model. So the build also compares
# every data file of every bundled package against the bundle. Anything missing
# fails the build unless it matches one of these: material no program loads at run
# time. Add to it only after checking the package never opens the file.
NOT_NEEDED_AT_RUN_TIME = [
    # PySide6's own hook collects the plugins Qt loads. The rest is QML, type
    # metadata, typesystems and headers, plus translations trimmed on purpose.
    "PySide6/*",
    "shiboken6/lib/cmake/*",
    "*/tests/*",
    "*/pkgconfig/*",
    "numpy/f2py/*",
    "numpy/random/_examples/*",
    "setuptools/*",
    "lxml/*.pxi",
    "greenlet/platform/*",
    "onnxruntime/datasets/*",
    "urllib3/contrib/emscripten/*",
    "markdown_it/port.yaml",
    "keyring/backend_complete.*",
    "tqdm/completion.sh",
    "tqdm/tqdm.1",
    "*/.keep",
    "*/LICENSE*",
    "*/NOTICE*",
]
# Never data: code, native libraries, headers and prose.
_NOT_DATA = {
    ".py", ".pyc", ".pyi", ".pyd", ".so", ".dll", ".dylib", ".exe", ".typed",
    ".h", ".hpp", ".c", ".cpp", ".pxd", ".pyx", ".lib", ".a",
    ".md", ".rst", ".txt", ".cfg", ".toml",
}  # fmt: skip


def _check_bundle(folder: Path) -> None:
    internal = folder / "_internal"
    missing = [
        f"{what} ({pattern})"
        for pattern, what in REQUIRED
        if not any(internal.glob(pattern))
    ]
    missing += _unbundled_data(internal)
    if missing:
        sys.exit("the bundle is missing:\n  " + "\n  ".join(missing))
    print(f"== bundle check: {len(REQUIRED)} named data sets, no unbundled data files")


def _unbundled_data(internal: Path) -> list[str]:
    """Data files of bundled packages that did not make it into the bundle."""
    import fnmatch
    import sysconfig

    site = Path(sysconfig.get_paths()["purelib"])
    packages = set()
    for toc in (BUILD / "pyinstaller" / "kitab").glob("PYZ-*.toc"):
        text = toc.read_text(encoding="utf-8", errors="replace")
        packages.update(re.findall(r"\('([A-Za-z0-9_]+)[.']", text))

    missing = []
    for package in sorted(packages):
        source = site / package
        if not source.is_dir():
            continue
        for path in source.rglob("*"):
            if not path.is_file() or path.suffix.lower() in _NOT_DATA:
                continue
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(site).as_posix()
            if (internal / relative).exists():
                continue
            if any(fnmatch.fnmatch(relative, p) for p in NOT_NEEDED_AT_RUN_TIME):
                continue
            missing.append(f"{relative} (not collected by kitab.spec)")
    return missing


# ---------------------------------------------------------------- Windows


def _portable_zip(folder: Path, version: str) -> None:
    target = DIST / f"Kitab-{version}-windows-x64-portable.zip"
    print(f"== {target.name}")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in folder.rglob("*"):
            z.write(path, Path("Kitab") / path.relative_to(folder))


def _inno_setup(folder: Path, version: str) -> None:
    iscc = shutil.which("iscc") or next(
        (
            str(p)
            for p in (
                Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6/ISCC.exe",
                Path(os.environ.get("PROGRAMFILES", "")) / "Inno Setup 6/ISCC.exe",
                Path(os.environ.get("LOCALAPPDATA", ""))
                / "Programs/Inno Setup 6/ISCC.exe",
            )
            if p.is_file()
        ),
        None,
    )
    if iscc is None:
        print(
            "== Inno Setup not found, skipping the installer "
            "(winget install JRSoftware.InnoSetup)"
        )
        return
    print("== installer")
    _run(
        [
            iscc,
            f"/DAppVersion={version}",
            f"/DSourceDir={folder}",
            f"/DOutputDir={DIST}",
            str(PACKAGING / "windows" / "kitab.iss"),
        ]
    )


# ---------------------------------------------------------------- Linux


def _fix_permissions(folder: Path) -> None:
    """Data files are copied without their execute bit; Playwright's node needs it."""
    for node in folder.rglob("playwright/driver/node"):
        node.chmod(0o755)


def _tarball(folder: Path, version: str) -> None:
    target = DIST / f"Kitab-{version}-linux-{platform.machine()}.tar.gz"
    print(f"== {target.name}")
    with tarfile.open(target, "w:gz") as tar:
        tar.add(folder, arcname="kitab")


def _appimage(folder: Path, version: str) -> None:
    arch = platform.machine()
    appdir = BUILD / "Kitab.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    lib = appdir / "usr" / "lib" / "kitab"
    shutil.copytree(folder, lib, symlinks=True)

    shutil.copy(PACKAGING / "linux" / "AppRun", appdir / "AppRun")
    (appdir / "AppRun").chmod(0o755)
    shutil.copy(PACKAGING / "linux" / "kitab.desktop", appdir / "kitab.desktop")
    shutil.copy(BUILD / "icon.png", appdir / "kitab.png")
    icons = appdir / "usr/share/icons/hicolor/256x256/apps"
    icons.mkdir(parents=True)
    shutil.copy(BUILD / "icon.png", icons / "kitab.png")
    applications = appdir / "usr/share/applications"
    applications.mkdir(parents=True)
    shutil.copy(PACKAGING / "linux" / "kitab.desktop", applications / "kitab.desktop")

    tool = shutil.which("appimagetool") or _download_appimagetool(arch)
    target = DIST / f"Kitab-{version}-{arch}.AppImage"
    print(f"== {target.name}")
    # Extract-and-run: CI containers and some desktops have no FUSE for the tool
    # itself. The AppImage it produces uses the static runtime and needs no libfuse2.
    env = dict(os.environ, ARCH=arch, APPIMAGE_EXTRACT_AND_RUN="1")
    _run([tool, str(appdir), str(target)], env=env)


def _download_appimagetool(arch: str) -> str:
    target = BUILD / f"appimagetool-{arch}.AppImage"
    if not target.exists():
        url = APPIMAGETOOL_URL.format(arch=arch)
        print(f"== downloading {url}")
        urllib.request.urlretrieve(url, target)
        target.chmod(0o755)
    return str(target)


if __name__ == "__main__":
    raise SystemExit(main())
