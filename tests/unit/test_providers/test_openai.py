"""Unit tests for OpenAIProvider.

Mocks the Chat Completions HTTP endpoint with an `httpx2.MockTransport`
injected through the provider's `http_client=` seam (see conftest.py).
No network calls. No real API key required.
"""

from __future__ import annotations

import httpx2
import openai
import pytest

from roundtable.providers.base import ProviderResponse
from roundtable.providers.openai import OpenAIProvider, _estimate_cost_usd

CHAT_URL = "https://api.openai.com/v1/chat/completions"


def _sample_payload(text: str = "hello world") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 7,
            "total_tokens": 19,
        },
    }


def test_constructor_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIProvider()


def test_constructor_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    p = OpenAIProvider()
    assert p.name == "gpt-4o"
    assert p.context_window_tokens == 128_000


@pytest.mark.asyncio
async def test_successful_call_populates_response(mock_endpoint) -> None:
    endpoint = mock_endpoint(
        httpx2.Response(200, json=_sample_payload("hi from gpt-4o"))
    )
    provider = OpenAIProvider(api_key="sk-fake", http_client=endpoint.client())
    resp = await provider.call("hello", timeout_seconds=5.0)

    assert endpoint.call_count == 1
    assert str(endpoint.requests[0].url) == CHAT_URL
    assert endpoint.requests[0].method == "POST"
    # The per-call timeout must reach the transport even though the
    # client was supplied by the caller.
    assert endpoint.requests[0].extensions["timeout"]["read"] == 5.0
    assert isinstance(resp, ProviderResponse)
    assert resp.text == "hi from gpt-4o"
    assert resp.prompt_tokens == 12
    assert resp.completion_tokens == 7
    assert resp.elapsed_seconds >= 0.0
    assert resp.estimated_cost_usd is not None
    assert resp.estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_http_error_propagates(mock_endpoint) -> None:
    endpoint = mock_endpoint(
        httpx2.Response(500, json={"error": {"message": "boom"}})
    )
    provider = OpenAIProvider(api_key="sk-fake", http_client=endpoint.client())
    with pytest.raises(openai.InternalServerError):
        await provider.call("hello", timeout_seconds=5.0)


@pytest.mark.asyncio
async def test_timeout_propagates(mock_endpoint) -> None:
    """SDK timeout enforcement: the transport raises ReadTimeout and
    the SDK wraps it as APITimeoutError. Note the dispatcher surfaces
    that as `api_error` (with an APITimeoutError detail); the
    `timeout` error class comes from the dispatcher's own
    `asyncio.wait_for` bound at the same budget."""
    endpoint = mock_endpoint(httpx2.ReadTimeout("simulated timeout"))
    provider = OpenAIProvider(api_key="sk-fake", http_client=endpoint.client())
    with pytest.raises(openai.APITimeoutError):
        await provider.call("hello", timeout_seconds=0.1)


@pytest.mark.asyncio
async def test_no_retries_in_provider(mock_endpoint) -> None:
    """N-1 contract: the provider must not retry within a round."""
    endpoint = mock_endpoint(
        httpx2.Response(500, json={"error": {"message": "boom"}})
    )
    provider = OpenAIProvider(api_key="sk-fake", http_client=endpoint.client())
    with pytest.raises(openai.InternalServerError):
        await provider.call("hello", timeout_seconds=5.0)
    assert endpoint.call_count == 1


@pytest.mark.asyncio
async def test_cost_estimate_positive_for_nonzero_tokens(mock_endpoint) -> None:
    endpoint = mock_endpoint(httpx2.Response(200, json=_sample_payload("ok")))
    provider = OpenAIProvider(api_key="sk-fake", http_client=endpoint.client())
    resp = await provider.call("hello", timeout_seconds=5.0)

    assert resp.estimated_cost_usd is not None
    assert resp.estimated_cost_usd > 0


def test_cost_is_none_for_unknown_model() -> None:
    # An override model not in _PRICING must report None rather than be
    # billed at the default model's rate.
    assert _estimate_cost_usd("not-a-real-model", 100, 50) is None


def test_cost_is_known_for_listed_model() -> None:
    assert _estimate_cost_usd("gpt-4o", 1_000_000, 0) == pytest.approx(2.50)
    assert _estimate_cost_usd("gpt-4o", 0, 1_000_000) == pytest.approx(10.00)


@pytest.mark.parametrize(
    "model,expected_input,expected_output",
    [
        ("gpt-5", 1.25, 10.00),
        ("gpt-5.1", 1.25, 10.00),
        ("gpt-5.5", 5.00, 30.00),
        ("gpt-5.6-sol", 4.00, 20.00),
        ("gpt-6-astra", 10.00, 50.00),
        ("gpt-6.1-sol", 2.00, 10.00),
        ("gpt-6-luna", 0.10, 0.50),
    ],
)
def test_new_models_have_documented_prices(
    model: str, expected_input: float, expected_output: float
) -> None:
    assert _estimate_cost_usd(model, 1_000_000, 0) == pytest.approx(expected_input)
    assert _estimate_cost_usd(model, 0, 1_000_000) == pytest.approx(expected_output)
