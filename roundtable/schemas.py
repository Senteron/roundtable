"""Pydantic schemas for the roundtable_round tool.

The shapes here ARE the public contract. Changes require the same
version-bump discipline as the framing prompt and tool description
(see CLAUDE.md and docs/review-concerns-plan.md D5).

Decisions enforced by these models:

- D1: `RoundInput.prior_failures` carries failed-panelist info from
  the orchestrator into the dispatcher so the UNAVAILABLE
  PARTICIPANTS section of the round-1+ framing is reachable from
  real input (not just constructed inside tests).
- D2: `PriorAnswer.source` is a required enum; orchestrator drafts
  are distinguishable from panelist answers.
- D3: `PriorAnswer.round` (renamed from `version`) carries which
  round produced the answer.
- D4: `ErrorClass` includes `context_overflow` as a stable string
  for oversize framed prompts.
- v0.2: `ErrorClass.UNKNOWN_MODEL` distinguishes "the caller named a
  model the panel registry doesn't know about" from any in-flight
  provider failure. Emitted by `_resolve_panel` before dispatch, so
  the orchestrator can see the slot failed without having to sniff
  for a prompt-echo response from the old silent-FakeProvider path.
- P3.5: `RoundInput` enforces that all `prior_answers` and
  `prior_failures` entries share a single round number. The tool
  description and the framing template both presume a coherent
  prior-round bundle; mixed rounds would produce a confusing
  "PANEL ANSWERS (round ?)" header and almost certainly indicate
  a caller mistake.
- v0.4: `RoundInput` rejects `models=[]` as invalid_input. The
  protocol doesn't echo arguments, so an orchestrator that
  intended to override but had its field stripped by the harness
  cannot tell the difference between "I sent an empty array" and
  "my models field was dropped" without an explicit error.
- v0.4: `RoundOutput.resolved_models` echoes the panel names
  actually dispatched to (registry names, fake-* fixtures, or
  unknown_model sentinels). Lets the orchestrator confirm what
  ran versus what it intended without having to read its own
  outgoing tool-call JSON.
- v0.4: `RoundInput.models` accepts a JSON-encoded string of an
  array of strings (e.g. `'["gpt-5"]'`) in addition to a real
  array. Workaround for Claude Code's MCP client, which was
  observed shipping array parameters as JSON-stringified payloads
  even when the inputSchema declared `type: array`. The
  coercion is narrow and only fires when the value is a `str`
  that parses cleanly to `list[str]`; malformed input still
  fails the normal type check.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Source(str, Enum):
    ORCHESTRATOR = "orchestrator"
    PANELIST = "panelist"


class ErrorClass(str, Enum):
    TIMEOUT = "timeout"
    API_ERROR = "api_error"
    CONTEXT_OVERFLOW = "context_overflow"
    INVALID_OUTPUT = "invalid_output"
    UNKNOWN_MODEL = "unknown_model"


class PriorAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    source: Source
    round: int = Field(ge=0)
    answer: str


class PriorFailure(BaseModel):
    """A panelist that failed on a prior round.

    Threaded through to render_round_1_plus(failed=...) so the
    UNAVAILABLE PARTICIPANTS section is reachable from real input
    (D1). Separate from PriorAnswer so the dispatcher does not have
    to use a truthy-answer heuristic to classify entries.
    """

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    source: Source
    round: int = Field(ge=0)
    error_class: ErrorClass


class RoundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=50_000)
    prior_answers: list[PriorAnswer] | None = None
    prior_failures: list[PriorFailure] | None = None
    models: list[str] | None = None
    round: int | None = Field(default=None, ge=0)
    per_call_timeout_seconds: int = Field(default=90, ge=1, le=180)

    @field_validator("models", mode="before")
    @classmethod
    def _coerce_json_string_models(cls, v: Any) -> Any:
        """Workaround for Claude Code's MCP client (observed
        2026-05-24, claude-ai/0.1.0 protocol 2025-11-25): array
        parameters declared in the tool's inputSchema as
        `type: ["array", "null"]` are nonetheless shipped as
        JSON-encoded *strings* in the tools/call arguments. The
        result is a validation error like `'["gpt-5"]' is not of
        type 'array', 'null'` even though the caller and schema
        agreed on the array shape.

        This validator detects a string that parses as a JSON
        array of strings and accepts it. Everything else passes
        through unchanged for the normal pydantic type-check to
        handle (including the rejection of malformed input). The
        coercion is narrow: it only fires when `v` is a `str`
        that parses cleanly to a list of strings.
        """
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return v
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                return parsed
        return v

    @field_validator("models")
    @classmethod
    def _models_not_empty_if_present(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) == 0:
            raise ValueError(
                "models must be omitted (or null) to use the default "
                "panel; an empty array is rejected so an orchestrator "
                "whose models field was stripped by the harness can "
                "tell the difference between 'I sent an empty array' "
                "and 'my field was dropped'."
            )
        return v

    @model_validator(mode="after")
    def _prior_entries_share_a_round(self) -> RoundInput:
        """All prior_answers and prior_failures must come from the
        same prior round. Mixed rounds in a single bundle would
        produce a confusing framing prompt ("PANEL ANSWERS (round ?)")
        and almost certainly indicate a caller mistake.
        """
        rounds: set[int] = set()
        for a in self.prior_answers or []:
            rounds.add(a.round)
        for f in self.prior_failures or []:
            rounds.add(f.round)
        if len(rounds) > 1:
            raise ValueError(
                f"prior_answers and prior_failures must share a single "
                f"round number; got {sorted(rounds)}"
            )
        return self


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    answer: str | None
    elapsed_seconds: float = Field(ge=0)
    estimated_cost_usd: float | None = None
    error: ErrorClass | None = None
    # Short diagnostic string when error is set — e.g., "401
    # Unauthorized" or "context window exceeded". Capped at 200
    # chars by the validator below (silently truncated rather than
    # rejected, so a buggy callsite can't kill an entire round just
    # because the message was too long). Never carries prompt or
    # answer content beyond the exception-allowlist policy in
    # dispatcher._classify_exception_detail. Null on success.
    error_detail: str | None = None

    @field_validator("error_detail")
    @classmethod
    def _truncate_error_detail(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v[:200]


class ModelError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    error: ErrorClass


class RoundOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round: int = 0
    responses: list[ModelResponse]
    errors: list[ModelError]
    # v0.4: model names actually dispatched to, in caller order.
    # An orchestrator can compare this against the names it passed
    # in `models` to confirm the override took effect. When the
    # default panel runs (caller passed no `models` field), this
    # field still reports the resolved default lineup so the
    # orchestrator has explicit visibility into which panel ran.
    #
    # Two layers populate this field. `dispatcher.dispatch()` sets
    # it to the names of providers it actually dispatched to
    # (drops unknown_model sentinels). The MCP server wrapper in
    # `mcp_server._call_tool` overrides that with the full
    # caller-order list including unknown_model sentinels, so the
    # over-the-wire response reflects every slot the caller asked
    # for. Direct callers of `dispatch()` will see the dispatched-
    # only form; only the MCP-wrapped path includes sentinels.
    resolved_models: list[str]
    total_elapsed_seconds: float = Field(ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0)
