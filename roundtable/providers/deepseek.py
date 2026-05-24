"""DeepSeek provider.

DeepSeek exposes an OpenAI-compatible API, so this provider reuses the
`openai` SDK with a custom `base_url`. The constructor reads
`DEEPSEEK_API_KEY` at construction time; a missing key raises
immediately. Per-request timeout passes through the SDK's `timeout=`
keyword, same pattern as `OpenAIProvider`.

Pricing constants are commit-time estimates from DeepSeek's public
pricing page. Update here when pricing changes; see CHANGELOG.
"""

from __future__ import annotations

import os
import time

from openai import AsyncOpenAI

from .base import ProviderResponse

# DeepSeek public pricing for deepseek-chat, USD per 1M tokens
# (commit-time estimate; non-cache prices).
# https://api-docs.deepseek.com/quick_start/pricing
_PRICE_INPUT_PER_M_USD = 0.27
_PRICE_OUTPUT_PER_M_USD = 1.10

DEFAULT_MODEL = "deepseek-chat"
CONTEXT_WINDOW_TOKENS = 64_000
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
    ) -> None:
        key = api_key if api_key is not None else os.environ.get(_ENV_KEY)
        if not key:
            raise RuntimeError(
                f"{type(self).__name__}: environment variable {_ENV_KEY} is not set"
            )
        self.name = model
        self.context_window_tokens = context_window_tokens
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
