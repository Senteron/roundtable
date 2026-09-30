"""Shared httpx2 mock transport for the OpenAI-SDK-backed providers.

openai>=3 sends requests through `httpx2`, which `respx` (a patcher for
`httpx`) cannot intercept — under openai 3.x the old respx-based tests
silently escaped to the live API. Instead of monkeypatching the
transport, `OpenAIProvider` and `DeepSeekProvider` accept an
`http_client=` and these tests inject an `httpx2.AsyncClient` whose
transport is an `httpx2.MockTransport`. No network, no API key.

The google-genai SDK still uses `httpx`, so `test_google.py` keeps
using `respx`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import httpx2
import pytest


@dataclass
class MockEndpoint:
    """Records every request and serves a scripted response.

    `responses` is consumed in order; once exhausted the last entry
    repeats. Each entry is an `httpx2.Response` to return or an
    exception instance to raise (e.g. `httpx2.ReadTimeout`).
    """

    responses: list[httpx2.Response | BaseException]
    requests: list[httpx2.Request] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def _handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        idx = min(len(self.requests), len(self.responses)) - 1
        scripted = self.responses[idx]
        if isinstance(scripted, BaseException):
            raise scripted
        return scripted

    def client(self) -> httpx2.AsyncClient:
        """A client the provider can be constructed with."""
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self._handler))


@pytest.fixture
def mock_endpoint() -> Callable[..., MockEndpoint]:
    """Factory: `mock_endpoint(resp1, resp2, ...)` -> MockEndpoint."""

    def _make(*responses: httpx2.Response | BaseException) -> MockEndpoint:
        if not responses:
            raise ValueError("mock_endpoint needs at least one scripted response")
        return MockEndpoint(list(responses))

    return _make
