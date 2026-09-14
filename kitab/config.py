"""Configuration store.

Carried over from PDFMathTranslate's ``pdf2zh.config`` with the same public API
(``get`` / ``set`` / ``get_translator_by_name`` / ``set_translator_by_name``) so the
translator layer keeps working unchanged.  Differences: English throughout, its own
config path, and no implicit write-back on plain reads.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from threading import RLock

CONFIG_DIR = Path.home() / ".config" / "kitab"
CONFIG_PATH = CONFIG_DIR / "config.json"


class ConfigManager:
    _instance: "ConfigManager | None" = None
    _lock = RLock()  # reentrant: get_instance may be called while holding the lock

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._config_path = CONFIG_PATH
        self._config_data: dict = {}
        self._ensure_config_exists()

    # ---- file handling -------------------------------------------------

    def _ensure_config_exists(self, create: bool = True) -> None:
        if self._config_path.exists():
            self._load_config()
        elif create:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_data = {}
            self._save_config()
        else:
            raise ValueError(f"config file {self._config_path} not found")

    def _load_config(self) -> None:
        with self._lock:
            try:
                with self._config_path.open("r", encoding="utf-8") as f:
                    self._config_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                # A corrupt config must not stop a translation run.
                self._config_data = {}

    def _save_config(self) -> None:
        with self._lock:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._config_path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._config_data, f, indent=2, ensure_ascii=False)
            tmp.replace(self._config_path)

    # ---- API -----------------------------------------------------------

    @classmethod
    def use_config_file(cls, file_path) -> None:
        """Point the singleton at a custom config file."""
        custom = Path(file_path)
        with cls._lock:
            instance = cls.get_instance()
            instance._config_path = custom
            instance._ensure_config_exists(create=True)
            cls._instance = instance

    @classmethod
    def get(cls, key: str, default=None):
        """Read a value: config file first, then environment, then ``default``.

        Unlike the original, a plain read never writes back to disk.
        """
        instance = cls.get_instance()
        if key in instance._config_data:
            return instance._config_data[key]
        if key in os.environ:
            return os.environ[key]
        return default

    @classmethod
    def set(cls, key: str, value) -> None:
        instance = cls.get_instance()
        with instance._lock:
            instance._config_data[key] = value
            instance._save_config()

    @classmethod
    def get_translator_by_name(cls, name: str):
        instance = cls.get_instance()
        for translator in instance._config_data.get("translators", []):
            if translator.get("name") == name:
                return translator.get("envs")
        return None

    @classmethod
    def set_translator_by_name(cls, name: str, envs: dict) -> None:
        instance = cls.get_instance()
        with instance._lock:
            translators = instance._config_data.setdefault("translators", [])
            for translator in translators:
                if translator.get("name") == name:
                    translator["envs"] = copy.deepcopy(envs)
                    instance._save_config()
                    return
            translators.append({"name": name, "envs": copy.deepcopy(envs)})
            instance._save_config()

    @classmethod
    def all(cls) -> dict:
        return copy.deepcopy(cls.get_instance()._config_data)

    @classmethod
    def clear(cls) -> None:
        instance = cls.get_instance()
        with instance._lock:
            instance._config_data = {}
            instance._save_config()
