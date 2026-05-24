"""Per-provider call timeouts: slow models become error stubs, not hangs."""

from __future__ import annotations

import time

import pytest

from roundtable.dispatcher import dispatch
from roundtable.providers.fake import FakeProvider
from roundtable.schemas import ErrorClass, RoundInput


@pytest.mark.asyncio
async def test_slow_provider_times_out_without_blocking_others() -> None:
    fast = FakeProvider(name="fast", behavior="echo")
    slow = FakeProvider(name="slow", behavior="timeout")

    start = time.monotonic()
    out = await dispatch(
        RoundInput(prompt="hi", per_call_timeout_seconds=1),
        providers=[fast, slow],
    )
    elapsed = time.monotonic() - start

    # Both responses present. Fast succeeded, slow timed out.
    assert len(out.responses) == 2
    assert out.responses[0].error is None
    assert out.responses[1].error is ErrorClass.TIMEOUT
    assert out.responses[1].answer is None

    # The round is bounded by the per-call timeout plus small overhead.
    # If wait_for didn't fire, this would hang for ~11s (timeout + 10
    # sleep) until the test runner killed it.
    assert elapsed < 3.0


@pytest.mark.asyncio
async def test_round_returns_within_timeout_bound() -> None:
    """All-slow panel: round duration is bounded, not unbounded."""
    providers = [
        FakeProvider(name=f"slow{i}", behavior="timeout") for i in range(3)
    ]

    start = time.monotonic()
    out = await dispatch(
        RoundInput(prompt="hi", per_call_timeout_seconds=1),
        providers=providers,
    )
    elapsed = time.monotonic() - start

    assert all(r.error is ErrorClass.TIMEOUT for r in out.responses)
    # Parallel dispatch + per-call=1s means total should be ~1s, not 3s.
    assert elapsed < 2.5
