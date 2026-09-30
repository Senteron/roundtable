"""DeepSeek provider.

DeepSeek exposes an OpenAI-compatible API, so this provider reuses the
`openai` SDK with a custom `base_url`. The constructor reads
`DEEPSEEK_API_KEY` at construction time; a missing key raises
immediately. Per-request timeout passes through the SDK's `timeout=`
keyword, same pattern as `OpenAIProvider`.

Pricing is a per-model lookup table (`_PRICING`) keyed by model name,
with `(input_per_M_USD, output_per_M_USD)` tuples. Models not in the
table get `None` cost — better to omit a cost than to bill an override
at the wrong rate. Entries here are commit-time estimates and use the
non-cache tier; DeepSeek prices cache hits separately. Update when
pricing changes; see CHANGELOG.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from .base import ProviderResponse, looks_like_unresolved_placeholder

if TYPE_CHECKING:
    import httpx2

# DeepSeek public pricing, USD per 1M tokens (cache-miss tier,
# PEAK rate). https://api-docs.deepseek.com/quick_start/pricing
# Since 2026-08-16 DeepSeek bills peak/off-peak (off-peak is half
# price, 01:00-04:00 and 06:00-10:00 UTC weekdays); we use the peak
# rate so the estimate is an upper bound.
# As of 2026-09 the documented model names are `deepseek-flash`
# (DeepSeek-V4.1-Flash) and `deepseek-v4-pro` (DeepSeek-V4-Pro), and
# both default to thinking mode. The legacy `deepseek-chat`
# (non-thinking) / `deepseek-reasoner` (thinking) aliases are no
# longer listed by the /models endpoint but still answer; responses
# report `model: "deepseek-flash"`, so they are billed at the Flash
# rate and priced identically here. `deepseek-chat` stays the
# default because it is the only name that selects non-thinking
# mode, which is what the v0.1 validation lineup ran (measured
# 2026-09-29: same prompt, 0 reasoning tokens via `deepseek-chat`
# vs 78 via `deepseek-flash`; see docs/decisions.md §17.4).
_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.30, 1.20),
    "deepseek-reasoner": (0.30, 1.20),
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4-pro": (1.32, 3.96),
}

# Per-model max input/context window in tokens, as reported by the
# /models endpoint (`context_window`).
_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-chat": 1_048_576,
    "deepseek-reasoner": 1_048_576,
    "deepseek-flash": 1_048_576,
    "deepseek-v4-pro": 1_048_576,
}

DEFAULT_MODEL = "deepseek-chat"
CONTEXT_WINDOW_TOKENS = _CONTEXT_WINDOWS[DEFAULT_MODEL]
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

_ENV_KEY = "DEEPSEEK_API_KEY"


class DeepSeekProvider:
    """Provider implementation calling DeepSeek via the OpenAI SDK."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        context_window_tokens: int = CONTEXT_WINDOW_TOKENS,
        api_key: str | None = None,
        base_url: str = DEEPSEEK_BASE_URL,
        http_client: httpx2.AsyncClient | None = None,
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
        # max_retries=0: the dispatcher owns retry policy (N-1 tolerance:
        # the next round re-attempts naturally; no retry inside a round).
        # http_client: an optional pre-built httpx2.AsyncClient. Tests
        # inject one with an httpx2.MockTransport so no request leaves
        # the process; production leaves it None and the SDK builds
        # its own. Per-request `timeout=` still applies either way.
        self._client = AsyncOpenAI(
            api_key=key,
            base_url=base_url,
            max_retries=0,
            http_client=http_client,
        )

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
