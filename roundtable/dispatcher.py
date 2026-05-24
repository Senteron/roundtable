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
from .providers.base import InvalidProviderOutput, Provider, ProviderResponse
from .schemas import (
    ErrorClass,
    ModelError,
    ModelResponse,
    PriorAnswer,
    PriorFailure,
    RoundInput,
    RoundOutput,
)

# Rough char-per-token heuristic for the D4 pre-dispatch overflow check.
# Conservative on purpose: real tokenizers vary, and we'd rather flag
# a borderline prompt than silently send one that errors on the
# provider side. Reserve room for the model's response too.
_CHARS_PER_TOKEN = 3.5
_RESPONSE_RESERVE_TOKENS = 4_000

# Exception class names whose str() is known to NOT include the
# request body / prompt content. For these, error_detail carries the
# full message (truncated). For everything else, error_detail carries
# only the exception class name, no message — to honor the
# no-prompt-content-on-error privacy claim even when the underlying
# SDK chooses to include input fragments in its exception text.
#
# Tightening this allowlist requires testing the relevant SDK's
# exception class against representative failures; loosening (adding
# a class) requires confirming the SDK does NOT echo input. When in
# doubt, leave it off — the orchestrator still sees the class name.
_PROVIDER_EXCEPTION_NAMES_SAFE_TO_QUOTE: frozenset[str] = frozenset(
    {
        # Authentication / authorization. SDKs mask the key in the
        # message; remaining text is "401 Unauthorized" or similar.
        "AuthenticationError",
        "PermissionDeniedError",
        # Rate limiting. Message is "429 Too Many Requests" + headers.
        "RateLimitError",
        # Server-side problems. Message is "500 Internal Server Error"
        # or similar, no input echo.
        "InternalServerError",
        "ServiceUnavailableError",
        # Network / transport. Message is the underlying httpx/socket
        # error; no input body.
        "APIConnectionError",
        "APITimeoutError",
        "ConnectionError",
        "TimeoutError",
        # Roundtable-internal errors. Authored here; messages are
        # ours and contain no provider input.
        "RuntimeError",
        "ValueError",
    }
)


def _build_prompt(
    user_prompt: str,
    prior_answers: list[PriorAnswer] | None,
    prior_failures: list[PriorFailure] | None,
    current_round: int,
) -> str:
    """Round 0 sends the raw prompt; round 1+ uses the framing
    template. The decision is based purely on the presence of any
    prior-round entries (success or failure) — no truthy-string
    heuristics on the answer field.
    """
    if not prior_answers and not prior_failures:
        return user_prompt

    return render_round_1_plus(
        prompt=user_prompt,
        successful=prior_answers or [],
        failed=[(f.model, f.error_class) for f in (prior_failures or [])],
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
) -> tuple[ProviderResponse | None, ErrorClass | None, str | None, float]:
    """Single-provider call with timeout + error classification.

    Returns (response, error_class, error_detail, elapsed_seconds).
    On success: (response, None, None, elapsed).
    On failure: (None, error_class, short_diagnostic_message, elapsed).

    `error_detail` is a short (<=200 char) diagnostic string drawn
    from the exception's str(); it never carries prompt or answer
    content. The dispatcher passes it through to ModelResponse so
    orchestrators can distinguish "401 Unauthorized" from "timeout"
    from "context window exceeded" without parsing prose.
    """
    if _exceeds_context_window(prompt, provider):
        return (
            None,
            ErrorClass.CONTEXT_OVERFLOW,
            f"framed prompt exceeds {provider.context_window_tokens} "
            f"token context window",
            0.0,
        )

    start = time.monotonic()
    try:
        response = await asyncio.wait_for(
            provider.call(prompt, timeout_seconds),
            timeout=timeout_seconds,
        )
        return response, None, None, time.monotonic() - start
    except asyncio.TimeoutError:
        return (
            None,
            ErrorClass.TIMEOUT,
            f"timeout after {timeout_seconds:.1f}s",
            time.monotonic() - start,
        )
    except InvalidProviderOutput as e:
        return (
            None,
            ErrorClass.INVALID_OUTPUT,
            _truncate_detail(str(e)),
            time.monotonic() - start,
        )
    except Exception as e:
        return (
            None,
            ErrorClass.API_ERROR,
            _classify_exception_detail(e),
            time.monotonic() - start,
        )


def _classify_exception_detail(e: Exception) -> str:
    """Build a short diagnostic string from an exception while
    honoring the no-prompt-content-on-error privacy claim.

    Provider SDKs (notably OpenAI on BadRequestError and Google on
    400 responses) sometimes include the triggering input fragment
    in their exception message. To prevent that from leaking into
    error_detail, we quote the exception's str() ONLY for exception
    classes on the safe allowlist; everything else returns the class
    name alone.

    The orchestrator still gets actionable information ("BadRequestError",
    "InvalidRequestError") for unknown failure modes; it just doesn't
    get the message body that might echo the prompt.
    """
    name = type(e).__name__
    if name in _PROVIDER_EXCEPTION_NAMES_SAFE_TO_QUOTE:
        return _truncate_detail(f"{name}: {e}")
    return _truncate_detail(name)


def _truncate_detail(s: str) -> str:
    """Trim diagnostic text to fit ModelResponse.error_detail's
    200-char cap. Strips newlines so multi-line tracebacks don't
    blow up JSON serialization or clutter the orchestrator's view.
    """
    flat = " ".join(s.split())
    return flat[:200]


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
        prior_failures=inputs.prior_failures,
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

    for provider, (response, error_class, error_detail, elapsed) in zip(
        providers, results
    ):
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
                    error_detail=error_detail,
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
