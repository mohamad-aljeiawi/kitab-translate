"""Reasoning effort on OpenAI-style engines.

The rules come from OpenAI's model guidance: ``reasoning_effort`` is sent as given,
and ``temperature`` must not be sent while a model is reasoning. The client is fake --
it records every request and can answer with the 400s the real API sends.
"""

import openai
import pytest

from kitab import cache
from kitab.errors import EngineConfigError
from kitab.pipeline import Options, translate_book
from kitab.translate.openai_like import (
    REASONING_EFFORTS,
    DeepSeekTranslator,
    OpenAITranslator,
)


def _bad_request(message):
    """An openai.BadRequestError carrying ``message``.

    Built without a response object: the SDK's HTTP library has changed (httpx,
    then httpx2), and the engine reads nothing from the error but its text.
    """
    error = openai.BadRequestError.__new__(openai.BadRequestError)
    Exception.__init__(error, message)
    return error


class FakeCompletions:
    def __init__(self, reject=None):
        self.requests = []
        #: A function of the request returning an error message, or None to answer.
        self.reject = reject

    def create(self, **request):
        self.requests.append(request)
        message = self.reject(request) if self.reject else None
        if message:
            raise _bad_request(message)
        text = request["messages"][-1]["content"].rsplit("\n\n", 1)[-1]
        choice = type("C", (), {"message": type("M", (), {"content": "AR " + text})})
        return type("R", (), {"choices": [choice]})


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    for var in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    db = cache.init_test_db()
    yield
    cache.clean_test_db(db)


def _engine(reject=None, cls=OpenAITranslator, **kw):
    engine = cls(
        "en", model="gpt-6-luna", api_key="sk-test", ignore_cache=True, qps=0, **kw
    )
    engine.client = type("Client", (), {})()
    engine.client.chat = type("Chat", (), {})()
    engine.client.chat.completions = FakeCompletions(reject)
    return engine


def _sent(engine):
    return engine.client.chat.completions.requests


def test_effort_is_sent_and_temperature_is_not_while_reasoning():
    engine = _engine(reasoning_effort="low")
    assert engine.translate("Hello") == "AR Hello"
    (request,) = _sent(engine)
    assert request["reasoning_effort"] == "low"
    assert "temperature" not in request


def test_none_keeps_temperature():
    engine = _engine(reasoning_effort="none")
    engine.translate("Hello")
    (request,) = _sent(engine)
    assert request["reasoning_effort"] == "none"
    assert request["temperature"] == 0.2


def test_unset_sends_no_effort_and_drops_temperature_once_when_refused():
    def reject(request):
        if "temperature" in request:
            return (
                "Unsupported parameter: 'temperature' is not supported with this model."
            )

    engine = _engine(reject)
    assert engine.translate("One") == "AR One"
    assert engine.translate("Two") == "AR Two"

    first, retried, second = _sent(engine)
    assert "reasoning_effort" not in first and "temperature" in first
    assert "temperature" not in retried
    # Remembered: the next request does not pay for a rejected attempt first.
    assert "temperature" not in second


def test_an_effort_the_model_refuses_stops_the_run():
    def reject(request):
        if request.get("reasoning_effort") == "none":
            return "Unsupported value: 'reasoning_effort' does not support 'none'."

    engine = _engine(reject, reasoning_effort="none")
    with pytest.raises(EngineConfigError, match="does not accept reasoning effort"):
        engine.translate_many(["One", "Two", "Three"])
    # One request, not one per segment plus a per-segment retry each.
    assert len(_sent(engine)) == 1


def test_unknown_level_is_refused_before_any_request():
    with pytest.raises(EngineConfigError, match="unknown reasoning effort"):
        _engine(reasoning_effort="turbo")


def test_every_documented_level_is_accepted():
    assert REASONING_EFFORTS == (
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    for effort in REASONING_EFFORTS:
        engine = _engine(reasoning_effort=effort)
        engine.translate("x")
        assert _sent(engine)[0]["reasoning_effort"] == effort


def test_effort_is_part_of_the_cache_key_only_when_set():
    plain = _engine()
    low = _engine(reasoning_effort="low")
    high = _engine(reasoning_effort="high")
    assert "reasoning_effort" not in plain.cache.params
    assert low.cache.translate_engine_params != high.cache.translate_engine_params


def test_engines_without_the_setting_say_so(tmp_path):
    assert OpenAITranslator.supports_reasoning
    assert not DeepSeekTranslator.supports_reasoning

    book = tmp_path / "b.md"
    book.write_text("# T\n\nHello.", encoding="utf-8")
    with pytest.raises(EngineConfigError, match="no reasoning effort"):
        translate_book(
            book,
            tmp_path / "out",
            options=Options(service="google", reasoning_effort="low", glossary=False),
        )
