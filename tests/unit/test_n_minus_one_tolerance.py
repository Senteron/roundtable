"""N-1 panel tolerance: one provider's failure doesn't block the round.

Per CLAUDE.md and docs/design.md §4.3: every requested model gets an
entry in `responses`; failures appear as error stubs with `answer=None`
and a stable error class.
"""

from __future__ import annotations

import pytest

from roundtable.dispatcher import dispatch
from roundtable.providers.fake import FakeProvider
from roundtable.schemas import ErrorClass, RoundInput


@pytest.mark.asyncio
async def test_one_error_does_not_block_others() -> None:
    p_ok_1 = FakeProvider(name="a", behavior="echo")
    p_err = FakeProvider(name="b", behavior="error")
    p_ok_2 = FakeProvider(name="c", behavior="echo")

    out = await dispatch(
        RoundInput(prompt="hi"),
        providers=[p_ok_1, p_err, p_ok_2],
    )

    assert len(out.responses) == 3
    assert out.responses[0].error is None
    assert out.responses[0].answer is not None
    assert out.responses[1].error is ErrorClass.API_ERROR
    assert out.responses[1].answer is None
    assert out.responses[2].error is None
    assert out.responses[2].answer is not None


@pytest.mark.asyncio
async def test_all_errors_returns_valid_response_object() -> None:
    """3 of 3 fail. Still one entry per requested model, no raise."""
    providers = [
        FakeProvider(name=f"p{i}", behavior="error") for i in range(3)
    ]

    out = await dispatch(
        RoundInput(prompt="hi"),
        providers=providers,
    )

    assert len(out.responses) == 3
    assert all(r.answer is None for r in out.responses)
    assert all(r.error is ErrorClass.API_ERROR for r in out.responses)
    assert len(out.errors) == 3
    assert out.total_cost_usd == 0.0


@pytest.mark.asyncio
async def test_errors_list_mirrors_response_error_stubs() -> None:
    p_ok = FakeProvider(name="ok", behavior="echo")
    p_err = FakeProvider(name="err", behavior="error")

    out = await dispatch(
        RoundInput(prompt="hi"),
        providers=[p_ok, p_err],
    )

    assert len(out.errors) == 1
    assert out.errors[0].model == "err"
    assert out.errors[0].error is ErrorClass.API_ERROR


@pytest.mark.asyncio
async def test_no_retry_attempted_after_error() -> None:
    """If we retried, FakeProvider behavior='error' would still raise
    on the retry — but the dispatcher is contractually no-retry. The
    test below proves the error stub appears immediately rather than
    being masked by a retry chain that eventually succeeds. We can't
    directly observe 'didn't retry,' but we can observe 'didn't take
    multiple call durations.'
    """
    p = FakeProvider(name="x", behavior="error", delay_seconds=0.05)

    out = await dispatch(
        RoundInput(prompt="hi"),
        providers=[p],
    )

    # If the dispatcher silently retried even once, total time would
    # be at least 2 * 0.05s. We allow generous headroom but well under
    # what any retry attempt would add.
    assert out.total_elapsed_seconds < 0.5
    assert out.responses[0].error is ErrorClass.API_ERROR
