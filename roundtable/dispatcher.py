"""Parallel dispatch with two-layer timeouts and N-1 tolerance.

Contract (docs/design.md §2.1, §4):

- Inputs validated by RoundInput (schemas.py).
- Round 0 sends the raw prompt; round 1+ uses the framing template.
- Per-provider call timeout enforced via asyncio.wait_for.
- Whole-round timeout is bounded by per-call + small overhead;
  asyncio.gather with return_exceptions=True ensures one slow model
  doesn't block faster ones past its own deadline.
- A model failure (timeout, API error, context overflow) produces a
  per-model error stub; the round still returns one entry per
  requested model.
- No retries within a round (CLAUDE.md invariant).
"""

from __future__ import annotations

import asyncio
import time

from .framing import render_round_1_plus
from .providers.base import Provider, ProviderResponse
from .schemas import (
    ErrorClass,
    ModelError,
    ModelResponse,
    PriorAnswer,
    RoundInput,
    RoundOutput,
)

# Rough char-per-token heuristic for the D4 pre-dispatch overflow check.
# Conservative on purpose: real tokenizers vary, and we'd rather flag
# a borderline prompt than silently send one that errors on the
# provider side. Reserve room for the model's response too.
_CHARS_PER_TOKEN = 3.5
_RESPONSE_RESERVE_TOKENS = 4_000


def _build_prompt(
    user_prompt: str,
    prior_answers: list[PriorAnswer] | None,
    current_round: int,
) -> str:
    if not prior_answers:
        return user_prompt

    successful = [a for a in prior_answers if a.answer]
    # Round 1+ with no prior failures still uses the framing template.
    # The caller is responsible for not passing failed-but-zero
    # PriorAnswers; if all are empty, the dispatcher upstream still
    # produces a render but downstream models will see an empty
    # PANEL ANSWERS section.
    return render_round_1_plus(
        prompt=user_prompt,
        successful=successful,
        failed=[],
        current_round=current_round,
    )


def _exceeds_context_window(prompt: str, provider: Provider) -> bool:
    """D4: per-model pre-dispatch overflow check."""
    estimated_tokens = len(prompt) / _CHARS_PER_TOKEN
    budget = provider.context_window_tokens - _RESPONSE_RESERVE_TOKENS
    return estimated_tokens > budget


async def _call_one(
    provider: Provider,
    prompt: str,
    timeout_seconds: float,
) -> tuple[ProviderResponse | None, ErrorClass | None, float]:
    """Single-provider call with timeout + error classification.

    Returns (response, error_class, elapsed_seconds). Exactly one of
    response/error_class is non-None.
    """
    if _exceeds_context_window(prompt, provider):
        return None, ErrorClass.CONTEXT_OVERFLOW, 0.0

    start = time.monotonic()
    try:
        response = await asyncio.wait_for(
            provider.call(prompt, timeout_seconds),
            timeout=timeout_seconds,
        )
        return response, None, time.monotonic() - start
    except asyncio.TimeoutError:
        return None, ErrorClass.TIMEOUT, time.monotonic() - start
    except Exception:
        return None, ErrorClass.API_ERROR, time.monotonic() - start


async def dispatch(
    inputs: RoundInput,
    providers: list[Provider],
) -> RoundOutput:
    """Run one round across `providers`.

    `providers` is the resolved panel for this call. The caller
    (mcp_server) is responsible for resolving inputs.models -> panel
    composition; the dispatcher operates on the resolved list.
    """
    current_round = inputs.round if inputs.round is not None else 0
    prompt = _build_prompt(
        user_prompt=inputs.prompt,
        prior_answers=inputs.prior_answers,
        current_round=current_round,
    )

    round_start = time.monotonic()
    results = await asyncio.gather(
        *(
            _call_one(p, prompt, float(inputs.per_call_timeout_seconds))
            for p in providers
        ),
        return_exceptions=False,
    )
    total_elapsed = time.monotonic() - round_start

    responses: list[ModelResponse] = []
    errors: list[ModelError] = []
    total_cost = 0.0

    for provider, (response, error_class, elapsed) in zip(providers, results):
        if response is not None:
            cost = response.estimated_cost_usd or 0.0
            total_cost += cost
            responses.append(
                ModelResponse(
                    model=provider.name,
                    answer=response.text,
                    elapsed_seconds=response.elapsed_seconds,
                    estimated_cost_usd=response.estimated_cost_usd,
                    error=None,
                )
            )
        else:
            assert error_class is not None
            responses.append(
                ModelResponse(
                    model=provider.name,
                    answer=None,
                    elapsed_seconds=elapsed,
                    estimated_cost_usd=None,
                    error=error_class,
                )
            )
            errors.append(ModelError(model=provider.name, error=error_class))

    return RoundOutput(
        round=current_round,
        responses=responses,
        errors=errors,
        total_elapsed_seconds=total_elapsed,
        total_cost_usd=total_cost,
    )
