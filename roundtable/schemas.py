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
- P3.5: `RoundInput` enforces that all `prior_answers` and
  `prior_failures` entries share a single round number. The tool
  description and the framing template both presume a coherent
  prior-round bundle; mixed rounds would produce a confusing
  "PANEL ANSWERS (round ?)" header and almost certainly indicate
  a caller mistake.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Source(str, Enum):
    ORCHESTRATOR = "orchestrator"
    PANELIST = "panelist"


class ErrorClass(str, Enum):
    TIMEOUT = "timeout"
    API_ERROR = "api_error"
    CONTEXT_OVERFLOW = "context_overflow"
    INVALID_OUTPUT = "invalid_output"


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
    total_elapsed_seconds: float = Field(ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0)
