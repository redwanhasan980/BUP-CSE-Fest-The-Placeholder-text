"""Retry-with-backoff and deadline-aware per-call timeout in the LLM client.

Fully offline: the real OpenAI() client is monkeypatched, no network calls.
"""
from __future__ import annotations

import time

import httpx
import pytest
from openai import APITimeoutError, RateLimitError

import app.llm.client as client_mod
from app.llm.client import ProviderSpec, _call_timeout, _make_provider, _retry_after_seconds


def _rate_limit_error(retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    resp = httpx.Response(429, headers=headers, request=httpx.Request("POST", "http://x"))
    return RateLimitError("rate limited", response=resp, body=None)


class _FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, script):
        self.chat = _FakeChat(_FakeCompletions(script))


def _ok_response(content: str):
    msg = type("M", (), {"content": content})
    choice = type("C", (), {"message": msg})
    return type("R", (), {"choices": [choice]})


GOOD_JSON = '{"interpretations": [{"note_index": 0, "directive_type": "no_op", "windows": [], "factor": null, "minimum_energy_kwh": null, "reserve_percent_of_capacity": null, "max_grid_kwh": null, "explanation": "x"}]}'


def _install_fake(monkeypatch, script):
    fake = _FakeClient(script)
    monkeypatch.setattr(client_mod, "OpenAI", lambda **kw: fake)
    return fake


def test_call_timeout_no_deadline_uses_configured_timeout():
    assert _call_timeout(None) == client_mod.settings.llm_timeout_seconds


def test_call_timeout_shrinks_with_remaining_deadline():
    deadline = time.monotonic() + 2.0
    t = _call_timeout(deadline)
    assert 0.5 <= t <= 2.0


def test_call_timeout_floors_at_minimum_when_deadline_almost_gone():
    deadline = time.monotonic() + 0.1
    assert _call_timeout(deadline) == client_mod._MIN_CALL_TIMEOUT_SECONDS


def test_retry_after_seconds_parses_header():
    exc = _rate_limit_error(retry_after="1.5")
    assert _retry_after_seconds(exc) == 1.5


def test_retry_after_seconds_none_when_missing():
    exc = _rate_limit_error()
    assert _retry_after_seconds(exc) is None


def test_retries_transient_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)
    fake = _install_fake(monkeypatch, [
        _rate_limit_error(retry_after="0.01"),
        _ok_response(GOOD_JSON),
    ])
    provider = _make_provider(ProviderSpec("primary", "k", "http://x", "m"))
    ir = provider(["some note"], None)
    assert ir.interpretations[0].directive_type == "no_op"
    assert len(fake.chat.completions.calls) == 2


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)
    _install_fake(monkeypatch, [
        _rate_limit_error(), _rate_limit_error(), _rate_limit_error(),
    ])
    provider = _make_provider(ProviderSpec("primary", "k", "http://x", "m"))
    with pytest.raises(RateLimitError):
        provider(["some note"], None)


def test_non_retryable_error_raises_immediately(monkeypatch):
    fake = _install_fake(monkeypatch, [ValueError("bad json")])
    provider = _make_provider(ProviderSpec("primary", "k", "http://x", "m"))
    with pytest.raises(ValueError):
        provider(["some note"], None)
    assert len(fake.chat.completions.calls) == 1


def test_exhausted_deadline_raises_without_calling(monkeypatch):
    fake = _install_fake(monkeypatch, [_ok_response(GOOD_JSON)])
    deadline = time.monotonic() - 1.0
    provider = _make_provider(ProviderSpec("primary", "k", "http://x", "m"), deadline=deadline)
    with pytest.raises(TimeoutError):
        provider(["some note"], None)
    assert len(fake.chat.completions.calls) == 0


def test_retry_backoff_respects_remaining_deadline(monkeypatch):
    sleeps = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sleeps.append(s))
    fake = _install_fake(monkeypatch, [
        _rate_limit_error(retry_after="100"),  # far longer than remaining deadline
        _ok_response(GOOD_JSON),
    ])
    deadline = time.monotonic() + 3.0
    provider = _make_provider(ProviderSpec("primary", "k", "http://x", "m"), deadline=deadline)
    provider(["some note"], None)
    assert sleeps[0] < 3.0  # clamped to what's left, not the 100s Retry-After
    assert len(fake.chat.completions.calls) == 2
