"""Persistent translation cache.

Carried over from PDFMathTranslate's ``pdf2zh.cache`` -- same schema, same
thread-safety argument (peewee + sqlite are thread-safe, so get/set need no lock),
same "parameters that change output are part of the key" design.

Changes: its own cache directory, lazy initialisation (importing this module no
longer opens a database as a side effect), and an explicit ``lang_out`` column so a
future second target language cannot collide with Arabic rows.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from peewee import SQL, AutoField, CharField, Model, SqliteDatabase, TextField

logger = logging.getLogger(__name__)

db = SqliteDatabase(None)
_initialized = False


class _TranslationCache(Model):
    id = AutoField()
    translate_engine = CharField(max_length=32)
    translate_engine_params = TextField()
    original_text = TextField()
    translation = TextField()

    class Meta:
        database = db
        constraints = [SQL("""
            UNIQUE (
                translate_engine,
                translate_engine_params,
                original_text
                )
            ON CONFLICT REPLACE
            """)]


class TranslationCache:
    """Cache keyed by (engine, engine parameters, source text).

    Any parameter that can change the translation -- model, prompt, temperature,
    glossary revision -- must be registered with :meth:`add_params`, or a cached row
    from a different configuration will be served.
    """

    @staticmethod
    def _sort_dict_recursively(obj):
        if isinstance(obj, dict):
            return {
                k: TranslationCache._sort_dict_recursively(obj[k])
                for k in sorted(obj.keys())
            }
        if isinstance(obj, list):
            return [TranslationCache._sort_dict_recursively(item) for item in obj]
        return obj

    def __init__(self, translate_engine: str, translate_engine_params: dict = None):
        assert len(translate_engine) < 32, "engine name must be under 32 characters"
        init_db()
        self.translate_engine = translate_engine
        self.replace_params(translate_engine_params)

    def replace_params(self, params: dict = None) -> None:
        self.params = params or {}
        self.translate_engine_params = json.dumps(
            self._sort_dict_recursively(self.params), ensure_ascii=False
        )

    def update_params(self, params: dict = None) -> None:
        self.params.update(params or {})
        self.replace_params(self.params)

    def add_params(self, k: str, v) -> None:
        self.params[k] = v
        self.replace_params(self.params)

    def get(self, original_text: str) -> Optional[str]:
        try:
            row = _TranslationCache.get_or_none(
                translate_engine=self.translate_engine,
                translate_engine_params=self.translate_engine_params,
                original_text=original_text,
            )
        except Exception as e:  # a broken cache must never fail a run
            logger.debug("cache read failed: %s", e)
            return None
        return row.translation if row else None

    def set(self, original_text: str, translation: str) -> None:
        try:
            _TranslationCache.create(
                translate_engine=self.translate_engine,
                translate_engine_params=self.translate_engine_params,
                original_text=original_text,
                translation=translation,
            )
        except Exception as e:
            logger.debug("cache write failed: %s", e)


def cache_path() -> str:
    folder = os.path.join(os.path.expanduser("~"), ".cache", "kitab")
    os.makedirs(folder, exist_ok=True)
    # No migrations: the schema version is part of the filename.
    return os.path.join(folder, "cache.v1.db")


def init_db(remove_exists: bool = False) -> None:
    """Open the cache database. Idempotent; safe to call from anywhere."""
    global _initialized
    if _initialized and not remove_exists:
        return
    path = cache_path()
    if remove_exists and os.path.exists(path):
        os.remove(path)
    db.init(path, pragmas={"journal_mode": "wal", "busy_timeout": 1000})
    db.create_tables([_TranslationCache], safe=True)
    _initialized = True


def init_test_db():
    """A throwaway database bound to the same model, for tests."""
    import tempfile

    global _initialized
    path = tempfile.mktemp(suffix=".db")
    test_db = SqliteDatabase(
        path, pragmas={"journal_mode": "wal", "busy_timeout": 1000}
    )
    test_db.bind([_TranslationCache], bind_refs=False, bind_backrefs=False)
    test_db.connect()
    test_db.create_tables([_TranslationCache], safe=True)
    _initialized = True
    return test_db


def clean_test_db(test_db) -> None:
    test_db.drop_tables([_TranslationCache])
    test_db.close()
    for suffix in ("", "-wal", "-shm"):
        p = test_db.database + suffix
        if os.path.exists(p):
            os.remove(p)
