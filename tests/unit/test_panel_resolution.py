"""Panel resolution: API-key detection and FakeProvider fallback.

P4-wiring flips _resolve_panel() to instantiate real providers when
API keys are present in the environment, and to fall back to
FakeProvider with a clear warning when they're missing. These tests
exercise that behavior with monkeypatched env vars so they run
offline.

Tests do NOT make any real network calls — they construct provider
instances and inspect their types/names, but the providers are
configured with stub API keys that would fail if any test attempted
to dispatch.
"""

from __future__ import annotations

import logging

import pytest

from roundtable.mcp_server import _resolve_panel
from roundtable.providers.fake import FakeProvider


def _strip_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no provider keys leak in from the test runner's env."""
    for k in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_default_panel_with_no_keys_returns_three_fakes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Default panel + no env keys = three FakeProviders, with a
    warning logged for each missing key."""
    _strip_provider_keys(monkeypatch)
    caplog.set_level(logging.WARNING, logger="roundtable.mcp_server")

    panel = _resolve_panel(None)

    assert len(panel) == 3
    assert all(isinstance(p, FakeProvider) for p in panel)
    assert {p.name for p in panel} == {
        "gpt-4o",
        "gemini-2.5-pro",
        "deepseek-chat",
    }
    # One warning per missing key.
    warning_text = caplog.text
    assert "OPENAI_API_KEY is not set" in warning_text
    assert "GOOGLE_API_KEY is not set" in warning_text
    assert "DEEPSEEK_API_KEY is not set" in warning_text


def test_explicit_fake_models_always_resolve_to_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """models=["fake-a"] etc. must always resolve to FakeProvider,
    even when real API keys are present. This is what keeps
    integration tests stable across environments with/without keys.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-stub")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-stub")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-stub")

    panel = _resolve_panel(["fake-a", "fake-b"])

    assert len(panel) == 2
    assert all(isinstance(p, FakeProvider) for p in panel)
    assert [p.name for p in panel] == ["fake-a", "fake-b"]


def test_default_panel_with_one_key_present_returns_one_real_two_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed env: only OPENAI_API_KEY set. The OpenAI slot should
    become a real provider; Gemini and DeepSeek slots fall back to
    FakeProvider.
    """
    _strip_provider_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-stub")

    panel = _resolve_panel(None)

    by_name = {p.name: p for p in panel}
    assert isinstance(by_name["gemini-2.5-pro"], FakeProvider)
    assert isinstance(by_name["deepseek-chat"], FakeProvider)
    # The OpenAI provider class is what gets instantiated when the
    # key is present. We avoid importing OpenAIProvider at module
    # level so this test can also document the contract: the
    # not-FakeProvider check is sufficient.
    assert not isinstance(by_name["gpt-4o"], FakeProvider)


def test_unknown_model_name_resolves_to_fake_without_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A model name like 'fake-test' or 'arbitrary-string' is not in
    the real-provider registry, so it resolves to FakeProvider with
    no warning (warnings are reserved for known models with missing
    keys).
    """
    _strip_provider_keys(monkeypatch)
    caplog.set_level(logging.WARNING, logger="roundtable.mcp_server")

    panel = _resolve_panel(["arbitrary-model-name"])

    assert len(panel) == 1
    assert isinstance(panel[0], FakeProvider)
    assert panel[0].name == "arbitrary-model-name"
    # No warning — unknown names aren't expected to have keys.
    assert "arbitrary-model-name" not in caplog.text
