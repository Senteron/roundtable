"""Google Gemini provider.

Calls the Gemini API via the official `google-genai` SDK
(`genai.Client(...).aio.models.generate_content`). Per-request timeout
is passed via the `GenerateContentConfig.http_options.timeout` field;
the SDK accepts milliseconds there. We convert from the seconds the
protocol speaks.

API key is read from `GOOGLE_API_KEY` at construction time; a missing
key raises immediately rather than deferring failure to `call()`.

Pricing constants are commit-time estimates from Google's public
pricing page. Update here when pricing changes; see CHANGELOG.
"""

from __future__ import annotations

import os
import time

from google import genai
from google.genai import types as genai_types

from .base import ProviderResponse, looks_like_unresolved_placeholder

# Gemini 2.5 Pro public pricing, USD per 1M tokens (commit-time
# estimate). Gemini has tiered pricing by prompt size; we use the
# <=200K tier as the rough estimator. Update when pricing changes.
# https://ai.google.dev/gemini-api/docs/pricing
_PRICE_INPUT_PER_M_USD = 1.25
_PRICE_OUTPUT_PER_M_USD = 10.00

DEFAULT_MODEL = "gemini-2.5-pro"
CONTEXT_WINDOW_TOKENS = 1_000_000

_ENV_KEY = "GOOGLE_API_KEY"


class GoogleProvider:
    """Provider implementation calling Gemini via google-genai."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        context_window_tokens: int = CONTEXT_WINDOW_TOKENS,
        api_key: str | None = None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get(_ENV_KEY)
        if not key:
            raise RuntimeError(
                f"{type(self).__name__}: environment variable {_ENV_KEY} is not set"
            )
        if looks_like_unresolved_placeholder(key):
            raise RuntimeError(
                f"{type(self).__name__}: {_ENV_KEY} looks like an "
                f"unresolved manifest placeholder ({key!r}). The "
                f"Claude Desktop install dialog likely has an empty "
                f"key field; paste your API key into Settings → "
                f"Extensions → Roundtable to enable real dispatch."
            )
        self.name = model
        self.context_window_tokens = context_window_tokens
        self._client = genai.Client(api_key=key)

    async def call(
        self,
        prompt: str,
        timeout_seconds: float,
    ) -> ProviderResponse:
        # HttpOptions.timeout is milliseconds per the SDK contract.
        # attempts=1: the dispatcher owns retry policy (N-1 tolerance:
        # the next round re-attempts naturally; no retry inside a round).
        config = genai_types.GenerateContentConfig(
            http_options=genai_types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retry_options=genai_types.HttpRetryOptions(attempts=1),
            ),
        )
        start = time.monotonic()
        resp = await self._client.aio.models.generate_content(
            model=self.name,
            contents=prompt,
            config=config,
        )
        elapsed = time.monotonic() - start

        text = resp.text or ""
        usage = resp.usage_metadata
        prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
        completion_tokens = (
            getattr(usage, "candidates_token_count", None) if usage else None
        )
        cost = _estimate_cost_usd(prompt_tokens, completion_tokens)
        return ProviderResponse(
            text=text,
            elapsed_seconds=elapsed,
            estimated_cost_usd=cost,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


def _estimate_cost_usd(
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    if prompt_tokens is None and completion_tokens is None:
        return None
    p = prompt_tokens or 0
    c = completion_tokens or 0
    return (p * _PRICE_INPUT_PER_M_USD + c * _PRICE_OUTPUT_PER_M_USD) / 1_000_000
