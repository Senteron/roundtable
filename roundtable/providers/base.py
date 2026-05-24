"""Provider protocol and shared types.

`Provider.call` may raise; the dispatcher wraps every call in a
try/except and converts exceptions into per-model error stubs. This
is the only place where exceptions cross a layer boundary (per
docs/design.md §4.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    elapsed_seconds: float
    estimated_cost_usd: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Provider(Protocol):
    """Protocol every provider implements.

    Attributes:
        name: canonical model name used in responses, e.g. "gpt-4o".
        context_window_tokens: provider's input context window, used
            by the dispatcher for D4 (context_overflow) checks before
            dispatch. Set to a conservative value if exact size is
            unclear.
    """

    name: str
    context_window_tokens: int

    async def call(
        self,
        prompt: str,
        timeout_seconds: float,
    ) -> ProviderResponse: ...


class InvalidProviderOutput(Exception):
    """Raised when a provider returned a response that violates the
    expected shape (e.g., empty completion when content was required,
    malformed JSON when structured output was requested).

    The dispatcher catches this and emits ErrorClass.INVALID_OUTPUT
    rather than the generic API_ERROR, so callers can distinguish
    "the provider was reachable but its answer was unusable" from
    "the provider call itself failed."
    """
