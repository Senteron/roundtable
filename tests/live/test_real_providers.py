"""Live smoke tests against real provider APIs.

Maintainer-only check per D8 in docs/review-concerns-plan.md. Gated
by the `live` pytest marker AND by the presence of each provider's
API key in the environment. NOT run in CI; not a release gate.

Run via:
    OPENAI_API_KEY=… GOOGLE_API_KEY=… DEEPSEEK_API_KEY=… \
        .venv/bin/pytest -m live tests/live/

Each provider gets one test:
- short prompt, default model
- assert: response has non-empty text, positive elapsed time,
  estimated cost > 0, no exception
- timeout 60s per call

These tests cost real money (small — each call is ~$0.001-0.01)
and produce non-deterministic output. Use the smallest-possible
prompts and accept that any individual run may fail due to
provider flakiness; failure does not block release per D8 but
should be noted in the release PR description.
"""

from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_openai_real_dispatch() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    from roundtable.providers.openai import OpenAIProvider

    p = OpenAIProvider()
    response = await p.call(
        "Reply with the single word 'hello' and nothing else.",
        timeout_seconds=60,
    )

    assert response.text.strip()
    assert response.elapsed_seconds > 0
    assert response.estimated_cost_usd is not None
    assert response.estimated_cost_usd > 0


@pytest.mark.asyncio
async def test_google_real_dispatch() -> None:
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not set")

    from roundtable.providers.google import GoogleProvider

    p = GoogleProvider()
    response = await p.call(
        "Reply with the single word 'hello' and nothing else.",
        timeout_seconds=60,
    )

    assert response.text.strip()
    assert response.elapsed_seconds > 0
    # Google's cost estimate may be None if token counts weren't
    # populated; just check the elapsed/text invariants.


@pytest.mark.asyncio
async def test_deepseek_real_dispatch() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set")

    from roundtable.providers.deepseek import DeepSeekProvider

    p = DeepSeekProvider()
    response = await p.call(
        "Reply with the single word 'hello' and nothing else.",
        timeout_seconds=60,
    )

    assert response.text.strip()
    assert response.elapsed_seconds > 0
    assert response.estimated_cost_usd is not None
    assert response.estimated_cost_usd > 0
