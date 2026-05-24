"""Unit tests for GoogleProvider.

The google-genai SDK uses httpx under the hood, so respx mocks the
`generativelanguage.googleapis.com` endpoint directly. No network
calls. No real API key required.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from roundtable.providers.base import ProviderResponse
from roundtable.providers.google import GoogleProvider

GENERATE_HOST = "generativelanguage.googleapis.com"


def _sample_payload(text: str = "hello world") -> dict:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text}], "role": "model"},
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 9,
            "candidatesTokenCount": 4,
            "totalTokenCount": 13,
        },
    }


def test_constructor_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # google-genai also auto-detects other env vars; clear them too.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        GoogleProvider()


def test_constructor_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    p = GoogleProvider()
    assert p.name == "gemini-2.5-pro"
    assert p.context_window_tokens == 1_000_000


@pytest.mark.asyncio
async def test_successful_call_populates_response() -> None:
    provider = GoogleProvider(api_key="fake-key")
    with respx.mock(assert_all_called=True) as mock:
        mock.post(host=GENERATE_HOST).mock(
            return_value=httpx.Response(200, json=_sample_payload("hi from gemini"))
        )
        resp = await provider.call("hello", timeout_seconds=5.0)

    assert isinstance(resp, ProviderResponse)
    assert resp.text == "hi from gemini"
    assert resp.prompt_tokens == 9
    assert resp.completion_tokens == 4
    assert resp.elapsed_seconds >= 0.0
    assert resp.estimated_cost_usd is not None
    assert resp.estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_http_error_propagates() -> None:
    provider = GoogleProvider(api_key="fake-key")
    with respx.mock() as mock:
        mock.post(host=GENERATE_HOST).mock(
            return_value=httpx.Response(500, json={"error": {"message": "boom"}})
        )
        with pytest.raises(Exception):
            await provider.call("hello", timeout_seconds=5.0)


@pytest.mark.asyncio
async def test_timeout_propagates() -> None:
    provider = GoogleProvider(api_key="fake-key")
    with respx.mock() as mock:
        mock.post(host=GENERATE_HOST).mock(
            side_effect=httpx.ReadTimeout("simulated timeout")
        )
        with pytest.raises(Exception):
            await provider.call("hello", timeout_seconds=0.1)


@pytest.mark.asyncio
async def test_no_retries_in_provider() -> None:
    """N-1 contract: the provider must not retry within a round."""
    provider = GoogleProvider(api_key="fake-key")
    with respx.mock() as mock:
        route = mock.post(host=GENERATE_HOST).mock(
            return_value=httpx.Response(500, json={"error": {"message": "boom"}})
        )
        with pytest.raises(Exception):
            await provider.call("hello", timeout_seconds=5.0)
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_cost_estimate_positive_for_nonzero_tokens() -> None:
    provider = GoogleProvider(api_key="fake-key")
    with respx.mock() as mock:
        mock.post(host=GENERATE_HOST).mock(
            return_value=httpx.Response(200, json=_sample_payload("ok"))
        )
        resp = await provider.call("hello", timeout_seconds=5.0)

    assert resp.estimated_cost_usd is not None
    assert resp.estimated_cost_usd > 0
