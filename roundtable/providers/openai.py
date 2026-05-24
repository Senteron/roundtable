"""OpenAI Chat Completions provider.

Calls the OpenAI Chat Completions API via the official `openai` SDK
(`AsyncOpenAI`). Per-request timeout is honored via the SDK's
`timeout=` keyword on `.chat.completions.create()`, which maps to the
underlying `httpx` timeout. The dispatcher catches any exception this
raises and converts it to a per-model error stub.

API key is read from `OPENAI_API_KEY` at construction time; a missing
key raises immediately rather than deferring failure to `call()`.

Pricing is a per-model lookup table (`_PRICING`) keyed by model name,
with `(input_per_M_USD, output_per_M_USD)` tuples. Models not in the
table get `None` cost — better to omit a cost than to bill an override
at the wrong rate. Update here when pricing changes; see CHANGELOG.
"""

from __future__ import annotations

import os
import time

from openai import AsyncOpenAI

from .base import ProviderResponse, looks_like_unresolved_placeholder

# OpenAI public pricing, USD per 1M tokens (as of 2026-05).
# https://openai.com/api/pricing/
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
}

DEFAULT_MODEL = "gpt-4o"
CONTEXT_WINDOW_TOKENS = 128_000

_ENV_KEY = "OPENAI_API_KEY"


class OpenAIProvider:
    """Provider implementation calling OpenAI Chat Completions."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        context_window_tokens: int = CONTEXT_WINDOW_TOKENS,
        api_key: str | None = None,
        base_url: str | None = None,
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
        # Stored only so subclasses (DeepSeek) can override; not part of
        # the Provider protocol.
        self._base_url = base_url
        # max_retries=0: the dispatcher owns retry policy (N-1 tolerance:
        # the next round re-attempts naturally; no retry inside a round).
        self._client = AsyncOpenAI(api_key=key, base_url=base_url, max_retries=0)

    async def call(
        self,
        prompt: str,
        timeout_seconds: float,
    ) -> ProviderResponse:
        start = time.monotonic()
        resp = await self._client.chat.completions.create(
            model=self.name,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout_seconds,
        )
        elapsed = time.monotonic() - start

        text = resp.choices[0].message.content or ""
        prompt_tokens = getattr(resp.usage, "prompt_tokens", None) if resp.usage else None
        completion_tokens = (
            getattr(resp.usage, "completion_tokens", None) if resp.usage else None
        )
        cost = _estimate_cost_usd(self.name, prompt_tokens, completion_tokens)
        return ProviderResponse(
            text=text,
            elapsed_seconds=elapsed,
            estimated_cost_usd=cost,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


def _estimate_cost_usd(
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    prices = _PRICING.get(model)
    if prices is None:
        return None
    if prompt_tokens is None and completion_tokens is None:
        return None
    input_per_m, output_per_m = prices
    p = prompt_tokens or 0
    c = completion_tokens or 0
    return (p * input_per_m + c * output_per_m) / 1_000_000
