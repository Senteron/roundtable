"""error_detail surfaces actionable diagnostics on failed responses.

Closes the v0.1.0 observability gap where api_error stubs carried
no detail beyond the error class. The orchestrator now sees a
short (<=200 char) diagnostic alongside the error class:

- TIMEOUT: "timeout after 90.0s"
- API_ERROR: "AuthenticationError: 401 ..."
- CONTEXT_OVERFLOW: "framed prompt exceeds N token context window"
- INVALID_OUTPUT: the provider's own message

error_detail must NEVER contain prompt or answer content. It's
drawn from the exception's str() (truncated and flattened) and
from dispatcher-generated descriptions of internal failure modes.
"""

from __future__ import annotations

import pytest

from roundtable.dispatcher import dispatch
from roundtable.providers.fake import FakeProvider
from roundtable.schemas import ErrorClass, RoundInput


@pytest.mark.asyncio
async def test_success_response_has_no_error_detail() -> None:
    p = FakeProvider(name="ok", behavior="echo")

    out = await dispatch(RoundInput(prompt="hi"), providers=[p])

    assert out.responses[0].error is None
    assert out.responses[0].error_detail is None


@pytest.mark.asyncio
async def test_api_error_carries_exception_class_and_message() -> None:
    p = FakeProvider(
        name="bad",
        behavior="error",
        error_message="something went wrong",
    )

    out = await dispatch(RoundInput(prompt="hi"), providers=[p])

    assert out.responses[0].error is ErrorClass.API_ERROR
    detail = out.responses[0].error_detail
    assert detail is not None
    # Detail should name the exception type so the orchestrator can
    # distinguish auth from rate-limit from network errors.
    assert "RuntimeError" in detail
    assert "something went wrong" in detail


@pytest.mark.asyncio
async def test_timeout_detail_names_the_deadline() -> None:
    fast = FakeProvider(name="fast", behavior="echo")
    slow = FakeProvider(name="slow", behavior="timeout")

    out = await dispatch(
        RoundInput(prompt="hi", per_call_timeout_seconds=1),
        providers=[fast, slow],
    )

    timeout_resp = out.responses[1]
    assert timeout_resp.error is ErrorClass.TIMEOUT
    assert timeout_resp.error_detail is not None
    # The orchestrator can read "timeout after 1.0s" and know
    # whether the deadline was generous or tight.
    assert "timeout" in timeout_resp.error_detail.lower()
    assert "1" in timeout_resp.error_detail


@pytest.mark.asyncio
async def test_context_overflow_detail_names_the_window() -> None:
    tiny = FakeProvider(
        name="tiny", behavior="echo", context_window_tokens=100
    )

    out = await dispatch(
        RoundInput(prompt="x" * 40_000),
        providers=[tiny],
    )

    resp = out.responses[0]
    assert resp.error is ErrorClass.CONTEXT_OVERFLOW
    assert resp.error_detail is not None
    assert "context window" in resp.error_detail.lower()
    assert "100" in resp.error_detail


@pytest.mark.asyncio
async def test_invalid_output_carries_provider_message() -> None:
    p = FakeProvider(
        name="schemafail",
        behavior="invalid_output",
        error_message="expected JSON object, got list",
    )

    out = await dispatch(RoundInput(prompt="hi"), providers=[p])

    resp = out.responses[0]
    assert resp.error is ErrorClass.INVALID_OUTPUT
    assert resp.error_detail is not None
    assert "expected JSON object" in resp.error_detail


@pytest.mark.asyncio
async def test_error_detail_truncated_to_field_cap() -> None:
    """Pydantic enforces max_length=200 on error_detail. The
    dispatcher truncates aggressively so a long exception message
    (e.g., a 5KB stack trace from a malformed API response) cannot
    inflate the round's JSON payload or break serialization.
    """
    huge_message = "boom! " * 200  # ~1200 chars
    p = FakeProvider(
        name="verbose", behavior="error", error_message=huge_message
    )

    out = await dispatch(RoundInput(prompt="hi"), providers=[p])

    detail = out.responses[0].error_detail
    assert detail is not None
    assert len(detail) <= 200


@pytest.mark.asyncio
async def test_error_detail_strips_newlines() -> None:
    """Tracebacks contain newlines. JSON serialization tolerates
    them, but multi-line error_detail clutters orchestrator displays.
    The dispatcher flattens to a single line.
    """
    multiline = "first line\nsecond line\n\n\nthird"
    p = FakeProvider(
        name="multiline", behavior="error", error_message=multiline
    )

    out = await dispatch(RoundInput(prompt="hi"), providers=[p])

    detail = out.responses[0].error_detail
    assert detail is not None
    assert "\n" not in detail
    # Words preserved, whitespace collapsed.
    assert "first line second line third" in detail


@pytest.mark.asyncio
async def test_unsafe_exception_class_does_not_leak_message() -> None:
    """Privacy guard: exception classes NOT on the allowlist must
    return only the class name, never the message body.

    SDK exceptions like BadRequestError sometimes echo the
    triggering input fragment in their message. The dispatcher's
    _classify_exception_detail policy returns just the class name
    for unknown exception types so input fragments cannot leak
    into error_detail. This test pins the policy: a custom
    exception class with a sensitive-looking message must produce
    an error_detail that contains the class name but NOT the
    message body.
    """

    # Subclass with a message that looks like an echoed prompt.
    class BadRequestError(Exception):  # name matches a real SDK class
        pass

    class _RaisesBadRequest:
        name = "leaky"
        context_window_tokens = 100_000
        last_prompt = ""

        async def call(self, prompt: str, timeout_seconds: float):  # type: ignore[no-untyped-def]
            self.last_prompt = prompt
            raise BadRequestError(
                "Invalid prompt: contains restricted content "
                "'<<SECRET FROM PROMPT>>'"
            )

    p = _RaisesBadRequest()

    out = await dispatch(RoundInput(prompt="hi"), providers=[p])

    detail = out.responses[0].error_detail
    assert detail is not None
    # Class name preserved so the orchestrator can still
    # diagnose the failure mode.
    assert "BadRequestError" in detail
    # Message body NOT included — the prompt fragment must not leak.
    assert "SECRET" not in detail
    assert "restricted content" not in detail
    assert "Invalid prompt" not in detail


@pytest.mark.asyncio
async def test_safe_exception_class_keeps_full_message() -> None:
    """Counterpart to the above: for exception classes that ARE on
    the allowlist (RuntimeError, AuthenticationError, etc.), the
    full message DOES come through. This is what makes
    error_detail actionable for the common case.
    """
    p = FakeProvider(
        name="auth-fail",
        behavior="error",
        error_message="401 Unauthorized — invalid API key",
    )
    # FakeProvider raises RuntimeError, which is on the allowlist.

    out = await dispatch(RoundInput(prompt="hi"), providers=[p])

    detail = out.responses[0].error_detail
    assert detail is not None
    assert "RuntimeError" in detail
    assert "401 Unauthorized" in detail
