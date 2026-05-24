"""Dispatcher tests: happy path, ordering, cost aggregation, round 0 vs 1+."""

from __future__ import annotations

import pytest

from roundtable.dispatcher import dispatch
from roundtable.framing import ROUND_1_PLUS_HEADER
from roundtable.providers.fake import FakeProvider
from roundtable.schemas import (
    ErrorClass,
    PriorAnswer,
    RoundInput,
    Source,
)


@pytest.mark.asyncio
async def test_round_zero_sends_raw_prompt() -> None:
    p1 = FakeProvider(name="a", behavior="echo")
    p2 = FakeProvider(name="b", behavior="echo")

    out = await dispatch(
        RoundInput(prompt="hello world"),
        providers=[p1, p2],
    )

    assert p1.last_prompt == "hello world"
    assert p2.last_prompt == "hello world"
    assert ROUND_1_PLUS_HEADER not in p1.last_prompt
    assert len(out.responses) == 2
    assert all(r.error is None for r in out.responses)


@pytest.mark.asyncio
async def test_round_one_plus_uses_framing_template() -> None:
    p = FakeProvider(name="a", behavior="echo")

    await dispatch(
        RoundInput(
            prompt="what is X",
            round=1,
            prior_answers=[
                PriorAnswer(
                    model="claude",
                    source=Source.ORCHESTRATOR,
                    round=0,
                    answer="X is foo",
                ),
                PriorAnswer(
                    model="a",
                    source=Source.PANELIST,
                    round=0,
                    answer="X is bar",
                ),
            ],
        ),
        providers=[p],
    )

    assert ROUND_1_PLUS_HEADER in p.last_prompt
    assert "PANEL ANSWERS (round 0):" in p.last_prompt
    assert "[claude]" in p.last_prompt
    assert p.last_prompt.endswith("This is round 1.")


@pytest.mark.asyncio
async def test_response_order_matches_provider_order() -> None:
    p1 = FakeProvider(name="alpha", behavior="echo", delay_seconds=0.05)
    p2 = FakeProvider(name="beta", behavior="echo", delay_seconds=0.0)
    p3 = FakeProvider(name="gamma", behavior="echo", delay_seconds=0.02)

    out = await dispatch(
        RoundInput(prompt="hi"),
        providers=[p1, p2, p3],
    )

    assert [r.model for r in out.responses] == ["alpha", "beta", "gamma"]


@pytest.mark.asyncio
async def test_cost_aggregation_sums_successful_responses() -> None:
    p1 = FakeProvider(name="a", behavior="echo", cost_usd=0.01)
    p2 = FakeProvider(name="b", behavior="echo", cost_usd=0.02)
    p3 = FakeProvider(name="c", behavior="echo", cost_usd=0.03)

    out = await dispatch(
        RoundInput(prompt="hi"),
        providers=[p1, p2, p3],
    )

    assert out.total_cost_usd == pytest.approx(0.06)


@pytest.mark.asyncio
async def test_failed_response_does_not_add_to_cost() -> None:
    p_ok = FakeProvider(name="ok", behavior="echo", cost_usd=0.02)
    p_err = FakeProvider(
        name="err", behavior="error", cost_usd=0.99
    )  # cost ignored

    out = await dispatch(
        RoundInput(prompt="hi"),
        providers=[p_ok, p_err],
    )

    assert out.total_cost_usd == pytest.approx(0.02)
    assert out.responses[1].error is ErrorClass.API_ERROR
    assert out.responses[1].estimated_cost_usd is None


@pytest.mark.asyncio
async def test_round_field_echoed_back() -> None:
    p = FakeProvider(name="a", behavior="echo")
    out = await dispatch(
        RoundInput(prompt="hi", round=3),
        providers=[p],
    )
    assert out.round == 3


@pytest.mark.asyncio
async def test_round_default_zero_when_unspecified() -> None:
    p = FakeProvider(name="a", behavior="echo")
    out = await dispatch(
        RoundInput(prompt="hi"),
        providers=[p],
    )
    assert out.round == 0
