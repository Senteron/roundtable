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


def looks_like_unresolved_placeholder(value: str) -> bool:
    """Return True if `value` looks like a manifest substitution
    template that was not actually substituted at install time.

    Claude Desktop's manifest format uses `${user_config.FOO}` to
    inject install-dialog values into the server's environment. If
    the user leaves a key field blank, the substitution may produce
    either an empty string OR the literal placeholder text depending
    on the host. An empty string is caught by the existing
    truthy-check; the literal placeholder is NOT (it's a non-empty
    string) and was silently passed to provider SDKs as if it were a
    real API key — producing 401 Unauthorized at the upstream API
    and an indistinguishable api_error stub at the MCP boundary.

    This helper centralizes the detection so all three providers
    classify the case uniformly. Format examples this matches:
        - "${user_config.OPENAI_API_KEY}"
        - "${OPENAI_API_KEY}"
        - "$OPENAI_API_KEY"
    """
    if not value:
        return False
    stripped = value.strip()
    return stripped.startswith("${") or stripped.startswith("$user_config")
