"""Unit tests for DeepSeekProvider.

DeepSeek uses the OpenAI-compatible API at a different base URL, so
respx mocking targets `https://api.deepseek.com/chat/completions`.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from roundtable.providers.base import ProviderResponse
from roundtable.providers.deepseek import DeepSeekProvider, _estimate_cost_usd

CHAT_URL = "https://api.deepseek.com/chat/completions"


def _sample_payload(text: str = "hello world") -> dict:
    return {
        "id": "deepseek-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 11,
            "total_tokens": 31,
        },
    }


def test_constructor_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        DeepSeekProvider()


def test_constructor_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake")
    p = DeepSeekProvider()
    assert p.name == "deepseek-chat"
    assert p.context_window_tokens == 64_000


@pytest.mark.asyncio
async def test_successful_call_populates_response() -> None:
    provider = DeepSeekProvider(api_key="sk-fake")
    with respx.mock(assert_all_called=True) as mock:
        mock.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json=_sample_payload("hi from deepseek"))
        )
        resp = await provider.call("hello", timeout_seconds=5.0)

    assert isinstance(resp, ProviderResponse)
    assert resp.text == "hi from deepseek"
    assert resp.prompt_tokens == 20
    assert resp.completion_tokens == 11
    assert resp.elapsed_seconds >= 0.0
    assert resp.estimated_cost_usd is not None
    assert resp.estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_http_error_propagates() -> None:
    provider = DeepSeekProvider(api_key="sk-fake")
    with respx.mock() as mock:
        mock.post(CHAT_URL).mock(
            return_value=httpx.Response(500, json={"error": {"message": "boom"}})
        )
        with pytest.raises(Exception):
            await provider.call("hello", timeout_seconds=5.0)


@pytest.mark.asyncio
async def test_timeout_propagates() -> None:
    provider = DeepSeekProvider(api_key="sk-fake")
    with respx.mock() as mock:
        mock.post(CHAT_URL).mock(side_effect=httpx.ReadTimeout("simulated timeout"))
        with pytest.raises(Exception):
            await provider.call("hello", timeout_seconds=0.1)


@pytest.mark.asyncio
async def test_no_retries_in_provider() -> None:
    """N-1 contract: the provider must not retry within a round."""
    provider = DeepSeekProvider(api_key="sk-fake")
    with respx.mock() as mock:
        route = mock.post(CHAT_URL).mock(
            return_value=httpx.Response(500, json={"error": {"message": "boom"}})
        )
        with pytest.raises(Exception):
            await provider.call("hello", timeout_seconds=5.0)
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_cost_estimate_positive_for_nonzero_tokens() -> None:
    provider = DeepSeekProvider(api_key="sk-fake")
    with respx.mock() as mock:
        mock.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json=_sample_payload("ok"))
        )
        resp = await provider.call("hello", timeout_seconds=5.0)

    assert resp.estimated_cost_usd is not None
    assert resp.estimated_cost_usd > 0


def test_cost_is_none_for_unknown_model() -> None:
    # An override model not in _PRICING must report None rather than be
    # billed at the default model's rate.
    assert _estimate_cost_usd("not-a-real-model", 100, 50) is None


def test_cost_is_known_for_listed_model() -> None:
    assert _estimate_cost_usd("deepseek-chat", 1_000_000, 0) == pytest.approx(0.27)
    assert _estimate_cost_usd("deepseek-chat", 0, 1_000_000) == pytest.approx(1.10)
