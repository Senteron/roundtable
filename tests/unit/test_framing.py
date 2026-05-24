"""Framing-prompt golden tests.

The ROUND_1_PLUS_HEADER constant and the rendered template structure
are part of the API contract. Changes here require a minor version
bump in pyproject.toml AND mcpb/manifest.json plus a CHANGELOG entry
(CLAUDE.md "Two strings get the version-bump discipline").

If a test in this file is intentionally updated, the same commit MUST
also touch pyproject.toml + mcpb/manifest.json + CHANGELOG.md. The
CI bundle-freshness check (P5) will mechanically enforce part of
this; this test is the human-readable guard.
"""

from __future__ import annotations

import pytest

from roundtable.framing import ROUND_1_PLUS_HEADER, render_round_1_plus
from roundtable.schemas import ErrorClass, PriorAnswer, Source


HEADER_GOLDEN = """\
You are participating in a multi-model deliberation. Below is the
original question, followed by every participant's latest answer
(yours included).

Read all of them carefully. Then produce YOUR revised answer to the
original question. Integrate what is correct from the others. Reject
what is wrong, naming what specifically you reject and why. Defend
your distinctive choices when the others would smooth them away.

Do NOT produce a synthesis or summary of the panel. Produce your own
answer, as if you were the only respondent, but informed by what the
others have said. Keep your voice; do not adopt the panel's."""


def test_header_golden() -> None:
    """If this fails, you changed the framing prompt header.

    Confirm the change is intentional, then bump the minor version
    in pyproject.toml AND mcpb/manifest.json and add a CHANGELOG
    entry before updating this constant.
    """
    assert ROUND_1_PLUS_HEADER == HEADER_GOLDEN


def _orchestrator(answer: str, round_: int = 0) -> PriorAnswer:
    return PriorAnswer(
        model="claude",
        source=Source.ORCHESTRATOR,
        round=round_,
        answer=answer,
    )


def _panelist(model: str, answer: str, round_: int = 0) -> PriorAnswer:
    return PriorAnswer(
        model=model,
        source=Source.PANELIST,
        round=round_,
        answer=answer,
    )


def test_round_1_full_success_no_unavailable_section() -> None:
    rendered = render_round_1_plus(
        prompt="What is the capital of France?",
        successful=[
            _orchestrator("Paris."),
            _panelist("gpt-4o", "Paris is the capital."),
            _panelist("gemini-2.5-pro", "The capital is Paris."),
        ],
        failed=[],
        current_round=1,
    )
    # D1: UNAVAILABLE PARTICIPANTS section omitted entirely when no
    # failures.
    assert "UNAVAILABLE PARTICIPANTS" not in rendered
    assert "PANEL ANSWERS (round 0):" in rendered
    assert "[claude]" in rendered
    assert "[gpt-4o]" in rendered
    assert "[gemini-2.5-pro]" in rendered
    assert rendered.endswith("This is round 1.")
    assert rendered.startswith(ROUND_1_PLUS_HEADER)


def test_round_2_with_one_failure_renders_unavailable_section() -> None:
    rendered = render_round_1_plus(
        prompt="What is the capital of France?",
        successful=[
            _orchestrator("Paris.", round_=1),
            _panelist("gpt-4o", "Paris is the capital.", round_=1),
        ],
        failed=[("gemini-2.5-pro", ErrorClass.TIMEOUT)],
        current_round=2,
    )
    assert "UNAVAILABLE PARTICIPANTS (round 1):" in rendered
    assert "[gemini-2.5-pro] timeout" in rendered
    # The failed panelist must NOT appear in PANEL ANSWERS (D1).
    panel_section = rendered.split("UNAVAILABLE PARTICIPANTS")[0]
    assert "[gemini-2.5-pro]" not in panel_section
    assert rendered.endswith("This is round 2.")


def test_unavailable_section_uses_stable_error_strings() -> None:
    rendered = render_round_1_plus(
        prompt="Q?",
        successful=[_panelist("gpt-4o", "A")],
        failed=[
            ("gemini-2.5-pro", ErrorClass.CONTEXT_OVERFLOW),
            ("deepseek-v3", ErrorClass.API_ERROR),
        ],
        current_round=1,
    )
    assert "[gemini-2.5-pro] context_overflow" in rendered
    assert "[deepseek-v3] api_error" in rendered


def test_all_failed_renders_placeholder_in_panel_section() -> None:
    rendered = render_round_1_plus(
        prompt="Q?",
        successful=[],
        failed=[
            ("gpt-4o", ErrorClass.TIMEOUT),
            ("gemini-2.5-pro", ErrorClass.API_ERROR),
        ],
        current_round=1,
    )
    assert "(no successful answers from prior round)" in rendered
    assert "UNAVAILABLE PARTICIPANTS" in rendered


def test_render_rejects_empty_prior_round() -> None:
    with pytest.raises(ValueError):
        render_round_1_plus(
            prompt="Q?",
            successful=[],
            failed=[],
            current_round=1,
        )


def test_orchestrator_and_panelist_render_identically_in_panel() -> None:
    """D2 affects schema; framing renders both as bracketed model
    headers. Distinguishing the orchestrator in the rendered text is
    a v0.2 concern; v0.1 keeps the symmetric framing per
    decisions.md §4."""
    rendered = render_round_1_plus(
        prompt="Q?",
        successful=[
            _orchestrator("draft", round_=0),
            _panelist("gpt-4o", "answer", round_=0),
        ],
        failed=[],
        current_round=1,
    )
    assert "[claude]\ndraft" in rendered
    assert "[gpt-4o]\nanswer" in rendered
