"""Schema validation: rejects malformed input, accepts canonical shape.

D2 (source enum), D3 (round rename), D4 (context_overflow error class),
and P3.5 (single-round-per-bundle invariant) are exercised here so the
contract can't regress without breaking these.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from roundtable.schemas import (
    ErrorClass,
    ModelError,
    ModelResponse,
    PriorAnswer,
    PriorFailure,
    RoundInput,
    RoundOutput,
    Source,
)


class TestRoundInput:
    def test_minimal_round_zero(self) -> None:
        inp = RoundInput(prompt="hello")
        assert inp.prompt == "hello"
        assert inp.prior_answers is None
        assert inp.per_call_timeout_seconds == 90

    def test_round_1_plus_with_prior_answers(self) -> None:
        inp = RoundInput(
            prompt="hello",
            prior_answers=[
                PriorAnswer(
                    model="gpt-4o",
                    source=Source.PANELIST,
                    round=0,
                    answer="hi",
                )
            ],
            round=1,
        )
        assert inp.prior_answers is not None
        assert inp.prior_answers[0].source is Source.PANELIST

    def test_rejects_empty_prompt(self) -> None:
        with pytest.raises(ValidationError):
            RoundInput(prompt="")

    def test_rejects_oversized_prompt(self) -> None:
        with pytest.raises(ValidationError):
            RoundInput(prompt="x" * 50_001)

    def test_rejects_negative_round(self) -> None:
        with pytest.raises(ValidationError):
            RoundInput(prompt="hi", round=-1)

    def test_rejects_timeout_below_one(self) -> None:
        with pytest.raises(ValidationError):
            RoundInput(prompt="hi", per_call_timeout_seconds=0)

    def test_rejects_timeout_above_max(self) -> None:
        with pytest.raises(ValidationError):
            RoundInput(prompt="hi", per_call_timeout_seconds=181)

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            RoundInput(prompt="hi", unknown_field="x")  # type: ignore[call-arg]


class TestPriorAnswer:
    def test_source_required(self) -> None:
        with pytest.raises(ValidationError):
            PriorAnswer(
                model="gpt-4o",
                round=0,
                answer="hi",
            )  # type: ignore[call-arg]

    def test_source_enum_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            PriorAnswer(
                model="gpt-4o",
                source="observer",  # type: ignore[arg-type]
                round=0,
                answer="hi",
            )

    def test_orchestrator_source_accepted(self) -> None:
        a = PriorAnswer(
            model="claude",
            source=Source.ORCHESTRATOR,
            round=0,
            answer="draft",
        )
        assert a.source is Source.ORCHESTRATOR

    def test_round_field_replaces_version(self) -> None:
        # D3: the field is `round`, not `version`. Old name should not
        # accidentally be accepted.
        with pytest.raises(ValidationError):
            PriorAnswer(
                model="gpt-4o",
                source=Source.PANELIST,
                version=0,  # type: ignore[call-arg]
                answer="hi",
            )

    def test_negative_round_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PriorAnswer(
                model="gpt-4o",
                source=Source.PANELIST,
                round=-1,
                answer="hi",
            )


class TestErrorClass:
    def test_context_overflow_present(self) -> None:
        # D4: context_overflow must be a stable enum value.
        assert ErrorClass("context_overflow") is ErrorClass.CONTEXT_OVERFLOW

    def test_all_classes(self) -> None:
        assert {e.value for e in ErrorClass} == {
            "timeout",
            "api_error",
            "context_overflow",
            "invalid_output",
            "unknown_model",
        }


class TestJsonSchemaEnumSync:
    """The MCP INPUT_SCHEMA hand-rolls JSON Schema enums. If the
    Pydantic Source or ErrorClass enums change and the JSON Schema
    isn't updated, callers will get validation errors that don't
    match the server's actual contract. These tests prevent silent
    drift between the two enum sources of truth.
    """

    def test_error_class_jsonschema_matches_pydantic(self) -> None:
        from roundtable.mcp_server import INPUT_SCHEMA

        jsonschema_values = set(
            INPUT_SCHEMA["properties"]["prior_failures"]["items"][
                "properties"
            ]["error_class"]["enum"]
        )
        assert jsonschema_values == {e.value for e in ErrorClass}

    def test_source_jsonschema_matches_pydantic(self) -> None:
        from roundtable.mcp_server import INPUT_SCHEMA
        from roundtable.schemas import Source

        for field_name in ("prior_answers", "prior_failures"):
            jsonschema_values = set(
                INPUT_SCHEMA["properties"][field_name]["items"][
                    "properties"
                ]["source"]["enum"]
            )
            assert jsonschema_values == {s.value for s in Source}


class TestRoundOutput:
    def test_minimal_output(self) -> None:
        out = RoundOutput(
            responses=[
                ModelResponse(
                    model="gpt-4o",
                    answer="hi",
                    elapsed_seconds=0.1,
                )
            ],
            errors=[],
            total_elapsed_seconds=0.1,
        )
        assert out.round == 0
        assert out.total_cost_usd == 0.0

    def test_error_stub_shape(self) -> None:
        out = RoundOutput(
            responses=[
                ModelResponse(
                    model="gpt-4o",
                    answer=None,
                    elapsed_seconds=0.1,
                    error=ErrorClass.TIMEOUT,
                )
            ],
            errors=[ModelError(model="gpt-4o", error=ErrorClass.TIMEOUT)],
            total_elapsed_seconds=0.1,
        )
        assert out.responses[0].answer is None
        assert out.responses[0].error is ErrorClass.TIMEOUT
        assert out.errors[0].error is ErrorClass.TIMEOUT


class TestRoundInputSingleRoundInvariant:
    """P3.5: prior_answers and prior_failures must share a single
    round number. The framing template renders one
    "PANEL ANSWERS (round N):" header; mixed N values would produce
    a confusing bundle. The schema enforces it at the boundary.
    """

    def _ans(self, model: str, round_: int) -> PriorAnswer:
        return PriorAnswer(
            model=model,
            source=Source.PANELIST,
            round=round_,
            answer="x",
        )

    def _fail(self, model: str, round_: int) -> PriorFailure:
        return PriorFailure(
            model=model,
            source=Source.PANELIST,
            round=round_,
            error_class=ErrorClass.TIMEOUT,
        )

    def test_matching_rounds_accepted(self) -> None:
        """Canonical happy path: answers and failures all from
        round 0.
        """
        inp = RoundInput(
            prompt="Q?",
            round=1,
            prior_answers=[self._ans("a", 0), self._ans("b", 0)],
            prior_failures=[self._fail("c", 0)],
        )
        assert inp.prior_answers is not None
        assert inp.prior_failures is not None

    def test_only_answers_no_failures_accepted(self) -> None:
        """Validator must not require both fields populated."""
        inp = RoundInput(
            prompt="Q?",
            round=1,
            prior_answers=[self._ans("a", 0), self._ans("b", 0)],
        )
        assert inp.prior_failures is None

    def test_only_failures_no_answers_accepted(self) -> None:
        """Failures alone (all panelists failed last round) is a
        valid bundle.
        """
        inp = RoundInput(
            prompt="Q?",
            round=1,
            prior_failures=[self._fail("a", 0), self._fail("b", 0)],
        )
        assert inp.prior_answers is None

    def test_mixed_rounds_in_prior_answers_rejected(self) -> None:
        """Two answers from different rounds → ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            RoundInput(
                prompt="Q?",
                round=2,
                prior_answers=[self._ans("a", 0), self._ans("b", 1)],
            )
        assert "share a single round number" in str(exc_info.value)

    def test_mixed_rounds_across_answers_and_failures_rejected(self) -> None:
        """Answer from round 0 + failure from round 1 → ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            RoundInput(
                prompt="Q?",
                round=2,
                prior_answers=[self._ans("a", 0)],
                prior_failures=[self._fail("b", 1)],
            )
        msg = str(exc_info.value)
        assert "share a single round number" in msg
        assert "[0, 1]" in msg

    def test_empty_bundles_accepted(self) -> None:
        """No prior entries at all = round 0. Both fields None is
        the canonical round-0 input.
        """
        inp = RoundInput(prompt="Q?")
        assert inp.prior_answers is None
        assert inp.prior_failures is None

    def test_single_entry_passes_trivially(self) -> None:
        """One entry can't conflict with itself."""
        inp = RoundInput(
            prompt="Q?",
            round=1,
            prior_answers=[self._ans("a", 0)],
        )
        assert len(inp.prior_answers) == 1
