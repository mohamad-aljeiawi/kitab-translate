"""Preferences and key storage. No Qt needed."""

import json
import os
import sys

import pytest

pytest.importorskip("platformdirs")

from kitab.gui.settings import (  # noqa: E402
    SecretStore,
    Settings,
    engine_defaults,
    engine_needs_key,
)


def test_settings_round_trip(tmp_path):
    path = tmp_path / "gui.json"
    s = Settings(theme="dark", max_jobs=3, service="deepseek", pdf=True)
    s.engine("deepseek").model = "deepseek-reasoner"
    s.save(path)

    loaded = Settings.load(path)
    assert loaded.theme == "dark"
    assert loaded.max_jobs == 3
    assert loaded.service == "deepseek"
    assert loaded.pdf is True
    assert loaded.engine("deepseek").model == "deepseek-reasoner"


def test_settings_tolerate_unknown_missing_and_broken(tmp_path):
    path = tmp_path / "gui.json"
    path.write_text(
        json.dumps({"theme": "light", "from_the_future": 1, "service": "gone"}),
        encoding="utf-8",
    )
    loaded = Settings.load(path)
    assert loaded.theme == "light"
    assert loaded.service == "google"  # unknown engine falls back to the default

    path.write_text("{not json", encoding="utf-8")
    assert Settings.load(path) == Settings()
    assert Settings.load(tmp_path / "missing.json") == Settings()


def test_settings_never_contain_keys(tmp_path):
    path = tmp_path / "gui.json"
    Settings().save(path)
    assert "key" not in path.read_text(encoding="utf-8").lower()


def test_engine_metadata():
    assert engine_needs_key("openai")
    assert engine_needs_key("deepseek")
    assert not engine_needs_key("google")
    assert not engine_needs_key("openailiked")
    assert engine_defaults("deepseek") == (
        "deepseek-chat",
        "https://api.deepseek.com/v1",
    )


def test_file_store_without_a_keyring(tmp_path):
    store = SecretStore(fallback=tmp_path / "secrets.json", use_keyring=False)
    assert not store.secure
    assert store.get("openai") == ""

    store.set("openai", "  sk-test  ")
    assert store.get("openai") == "sk-test"
    if sys.platform != "win32":
        assert (os.stat(tmp_path / "secrets.json").st_mode & 0o777) == 0o600

    store.set("openai", "")
    assert store.get("openai") == ""
    assert "openai" not in json.loads((tmp_path / "secrets.json").read_text())


class MemoryKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, user):
        return self.data.get((service, user))

    def set_password(self, service, user, value):
        self.data[(service, user)] = value

    def delete_password(self, service, user):
        import keyring.errors

        if (service, user) not in self.data:
            raise keyring.errors.PasswordDeleteError(user)
        del self.data[(service, user)]


def test_keyring_is_used_and_clears_the_file(tmp_path):
    pytest.importorskip("keyring")
    fallback = tmp_path / "secrets.json"
    fallback.write_text(json.dumps({"deepseek": "old-plaintext"}))

    store = SecretStore(fallback=fallback, use_keyring=False)
    store._keyring = MemoryKeyring()
    assert store.secure

    store.set("deepseek", "sk-new")
    assert store._keyring.data[("kitab", "deepseek")] == "sk-new"
    assert store.get("deepseek") == "sk-new"
    assert "deepseek" not in json.loads(fallback.read_text())

    store.set("deepseek", "")
    assert store.get("deepseek") == ""


def test_a_failing_keyring_falls_back_to_the_file(tmp_path):
    class Broken(MemoryKeyring):
        def set_password(self, *a):
            raise RuntimeError("D-Bus is gone")

        def get_password(self, *a):
            raise RuntimeError("D-Bus is gone")

    store = SecretStore(fallback=tmp_path / "secrets.json", use_keyring=False)
    store._keyring = Broken()
    store.set("openai", "sk-x")
    assert store.get("openai") == "sk-x"
