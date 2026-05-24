"""D4: oversize framed prompts produce a per-model error stub, never
silently truncate, and never raise out of the dispatcher.
"""

from __future__ import annotations

import pytest

from roundtable.dispatcher import dispatch
from roundtable.providers.fake import FakeProvider
from roundtable.schemas import ErrorClass, RoundInput


@pytest.mark.asyncio
async def test_oversize_prompt_yields_per_model_overflow_stub() -> None:
    """A provider with a tiny context window should overflow; a
    provider with a large window on the same call should succeed.
    Demonstrates per-model overflow handling (not round-wide).
    """
    tiny = FakeProvider(
        name="tiny", behavior="echo", context_window_tokens=100
    )
    large = FakeProvider(
        name="large", behavior="echo", context_window_tokens=1_000_000
    )

    big_prompt = "x" * 40_000  # well under RoundInput 50k cap but
                                # large enough to overflow the tiny
                                # provider after the response reserve.

    out = await dispatch(
        RoundInput(prompt=big_prompt),
        providers=[tiny, large],
    )

    assert out.responses[0].error is ErrorClass.CONTEXT_OVERFLOW
    assert out.responses[0].answer is None
    assert out.responses[1].error is None
    assert out.responses[1].answer is not None


@pytest.mark.asyncio
async def test_overflow_is_pre_dispatch_not_post() -> None:
    """The overflow check must happen BEFORE the provider call, so a
    misconfigured provider can't burn credits on a doomed request.
    We can verify by ensuring last_prompt was not set on the
    overflowing provider.
    """
    tiny = FakeProvider(
        name="tiny", behavior="echo", context_window_tokens=10
    )

    out = await dispatch(
        RoundInput(prompt="x" * 1000),
        providers=[tiny],
    )

    assert out.responses[0].error is ErrorClass.CONTEXT_OVERFLOW
    assert tiny.last_prompt == ""  # never called


@pytest.mark.asyncio
async def test_borderline_prompt_succeeds() -> None:
    """Prompts comfortably under the budget go through normally."""
    p = FakeProvider(
        name="p", behavior="echo", context_window_tokens=100_000
    )

    out = await dispatch(
        RoundInput(prompt="x" * 1000),
        providers=[p],
    )

    assert out.responses[0].error is None
    assert out.responses[0].answer is not None
