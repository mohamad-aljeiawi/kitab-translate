"""User preferences and API keys.

Two stores, deliberately separate:

*Preferences* are a JSON file in the config directory. Unknown keys are ignored and
missing ones take their defaults, so a settings file from an older or newer version
never stops the app starting.

*Keys* go to the operating system's credential store through ``keyring``: Windows
Credential Manager, or the Secret Service (GNOME Keyring on Ubuntu and Mint, KWallet
on KDE). A bare Arch install with a tiling window manager often has neither, and
there the keys fall back to a file only the user can read -- and the Settings page
says so, rather than implying a protection that is not there.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from kitab.translate.openai_like import REASONING_EFFORTS
from kitab.translate.registry import DEFAULT_ENGINE, ENGINES

from .paths import config_dir

logger = logging.getLogger(__name__)

SETTINGS_FILE = "gui.json"
SECRETS_FILE = "secrets.json"
KEYRING_SERVICE = "kitab"


def engine_needs_key(name: str) -> bool:
    """Whether an engine refuses to run without a key the user must supply."""
    cls = ENGINES[name]
    return any(k.endswith("_API_KEY") and v is None for k, v in cls.envs.items())


def engine_defaults(name: str) -> tuple[str, str]:
    """The engine's own (model, base URL), shown as placeholders in the UI."""
    envs = ENGINES[name].envs
    model = next((v for k, v in envs.items() if k.endswith("_MODEL")), "") or ""
    return model, envs.get("OPENAI_BASE_URL") or ""


@dataclass
class EngineSettings:
    model: str = ""
    base_url: str = ""
    #: Reasoning effort last chosen for this engine; "" is the model's default.
    reasoning: str = ""


@dataclass
class Settings:
    # appearance
    theme: str = "auto"  # auto | light | dark
    language: str = "auto"  # auto (follow the system) | en | ar
    accent: str = "system"  # system (the OS accent colour) | kitab
    # jobs
    max_jobs: int = 2
    output_dir: str = ""  # empty: next to each source file
    # the last options used on the Translate page, offered again next time
    service: str = DEFAULT_ENGINE
    lang_in: str = "auto"
    epub: bool = True
    pdf: bool = False
    bilingual: bool = False
    ocr: bool = False
    tier1: bool = True
    glossary: bool = True
    page_size: str = "A5"
    workers: int = 0  # 0: the engine's own default
    last_open_dir: str = ""
    engines: dict[str, EngineSettings] = field(default_factory=dict)

    def engine(self, name: str) -> EngineSettings:
        return self.engines.setdefault(name, EngineSettings())

    # ---- persistence ---------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_dir() / SETTINGS_FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as e:
            logger.warning("ignoring unreadable settings %s: %s", path, e)
            return cls()

        known = {f.name for f in dataclasses.fields(cls)} - {"engines"}
        settings = cls(**{k: v for k, v in raw.items() if k in known})
        for name, values in (raw.get("engines") or {}).items():
            if name in ENGINES and isinstance(values, dict):
                reasoning = str(values.get("reasoning") or "")
                settings.engines[name] = EngineSettings(
                    model=str(values.get("model") or ""),
                    base_url=str(values.get("base_url") or ""),
                    reasoning=reasoning if reasoning in REASONING_EFFORTS else "",
                )
        if settings.service not in ENGINES:
            settings.service = DEFAULT_ENGINE
        if settings.language not in ("auto", "en", "ar"):
            settings.language = "auto"
        if settings.accent not in ("system", "kitab"):
            settings.accent = "system"
        return settings

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / SETTINGS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(dataclasses.asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)


class SecretStore:
    """API keys, one per engine, in the OS keyring or a private file."""

    def __init__(self, fallback: Path | None = None, use_keyring: bool = True):
        self._fallback = fallback or config_dir() / SECRETS_FILE
        self._keyring = _usable_keyring() if use_keyring else None

    @property
    def secure(self) -> bool:
        return self._keyring is not None

    @property
    def location(self) -> str:
        """Where keys live, in words for the Settings page."""
        if self._keyring is None:
            return f"a private file ({self._fallback}); no system keyring was found"
        if sys.platform == "win32":
            return "Windows Credential Manager"
        name = type(self._keyring).__module__
        if "kwallet" in name:
            return "KWallet"
        return "the system keyring (Secret Service)"

    def get(self, engine: str) -> str:
        if self._keyring is not None:
            try:
                return self._keyring.get_password(KEYRING_SERVICE, engine) or ""
            except Exception as e:  # locked wallet, D-Bus gone, ...
                logger.warning("keyring read failed, using the file store: %s", e)
        return self._read_file().get(engine, "")

    def set(self, engine: str, value: str) -> None:
        value = value.strip()
        if self._keyring is not None:
            try:
                if value:
                    self._keyring.set_password(KEYRING_SERVICE, engine, value)
                else:
                    self._delete_keyring(engine)
                # A key saved to the keyring must not linger in the fallback file.
                self._write_file_entry(engine, "")
                return
            except Exception as e:
                logger.warning("keyring write failed, using the file store: %s", e)
        self._write_file_entry(engine, value)

    def _delete_keyring(self, engine: str) -> None:
        import keyring.errors

        try:
            self._keyring.delete_password(KEYRING_SERVICE, engine)
        except keyring.errors.PasswordDeleteError:
            pass

    # ---- the fallback file ---------------------------------------------

    def _read_file(self) -> dict[str, str]:
        try:
            data = json.loads(self._fallback.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in data.items() if isinstance(v, str)}

    def _write_file_entry(self, engine: str, value: str) -> None:
        data = self._read_file()
        if not value and engine not in data:
            return
        if value:
            data[engine] = value
        else:
            data.pop(engine, None)
        self._fallback.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._fallback.with_suffix(".json.tmp")
        # Create with owner-only permissions from the start: chmod after writing
        # would leave a window in which the key is world-readable.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self._fallback)


def _usable_keyring():
    """The active keyring backend, or None if it cannot actually store anything."""
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:
        return None
    if isinstance(backend, fail.Keyring):
        return None
    # The chainer wraps every viable backend; with none viable it is an empty shell.
    if getattr(backend, "backends", None) == []:
        return None
    if type(backend).__module__.startswith("keyring.backends.null"):
        return None
    return backend
