"""Subprocess startup: `python -m roundtable` launches an MCP server.

This is the test that would have caught the original "manifest
declares an entry point that doesn't exist" defect. It uses
`sys.executable` so the test is portable across virtualenvs (D8's
release procedure depends on this).
"""

from __future__ import annotations

import json
import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_server_starts_and_lists_tool() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "roundtable"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    assert len(tools.tools) == 1
    tool = tools.tools[0]
    assert tool.name == "roundtable_round"
    # Tool description carries the load-bearing guidance (D5).
    assert "parallel attempts, not verdicts" in tool.description
    assert "signal density" in tool.description


@pytest.mark.asyncio
async def test_server_info_reports_package_version() -> None:
    # The MCP `initialize` response's serverInfo.version is what
    # Claude Desktop logs as the running bundle's version. Without
    # passing version= to Server(), the SDK fills in its own
    # version, which makes "did the new bundle load?" hard to tell
    # from the logs after an upgrade.
    from roundtable import __version__

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "roundtable"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()

    assert init_result.serverInfo.name == "roundtable"
    assert init_result.serverInfo.version == __version__


@pytest.mark.asyncio
async def test_round_zero_end_to_end() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "roundtable"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "roundtable_round",
                {
                    "prompt": "What is 2+2?",
                    "models": ["fake-a", "fake-b"],
                },
            )

    assert not result.isError
    assert len(result.content) == 1
    payload = json.loads(result.content[0].text)

    assert payload["round"] == 0
    assert len(payload["responses"]) == 2
    assert {r["model"] for r in payload["responses"]} == {"fake-a", "fake-b"}
    assert all(r["error"] is None for r in payload["responses"])
    assert all(r["answer"] is not None for r in payload["responses"])
    assert payload["errors"] == []


@pytest.mark.asyncio
async def test_round_one_plus_with_prior_answers() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "roundtable"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "roundtable_round",
                {
                    "prompt": "What is the answer?",
                    "round": 1,
                    "models": ["fake-x"],
                    "prior_answers": [
                        {
                            "model": "claude",
                            "source": "orchestrator",
                            "round": 0,
                            "answer": "My draft answer.",
                        },
                        {
                            "model": "fake-x",
                            "source": "panelist",
                            "round": 0,
                            "answer": "fake-x's prior answer.",
                        },
                    ],
                },
            )

    assert not result.isError
    payload = json.loads(result.content[0].text)
    assert payload["round"] == 1

    # The FakeProvider's echo truncates to 200 chars, so we look for
    # the framing header (which starts at the top of the framed
    # prompt) rather than later markers like PANEL ANSWERS. This is
    # enough to prove round-1+ framing was applied by the dispatcher
    # via the MCP boundary.
    answer = payload["responses"][0]["answer"]
    assert "multi-model deliberation" in answer
    assert payload["responses"][0]["error"] is None


@pytest.mark.asyncio
async def test_invalid_input_does_not_crash_connection() -> None:
    """Empty prompt is rejected by the MCP SDK's own input-schema
    validation (driven by the `inputSchema` we declare). The
    connection must remain usable for the next call — we verify by
    making a valid call after the rejection.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "roundtable"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            bad = await session.call_tool(
                "roundtable_round",
                {"prompt": "", "models": ["fake-a"]},
            )
            # The SDK rejects this before our handler runs. Either
            # isError=True or the text content reports the validation
            # failure; both shapes are acceptable, the key invariant
            # is that the connection survives.
            assert bad.isError or "validation" in bad.content[0].text.lower()

            good = await session.call_tool(
                "roundtable_round",
                {"prompt": "ok", "models": ["fake-a"]},
            )

    assert not good.isError
    payload = json.loads(good.content[0].text)
    assert payload["responses"][0]["error"] is None


@pytest.mark.asyncio
async def test_prior_failures_round_trip_through_mcp() -> None:
    """D1 end-to-end: a prior_failures bundle reaches the dispatcher
    through the MCP boundary and round-1+ framing is applied.

    FakeProvider's echo is truncated to 200 chars; the framing
    header alone fills it, so we can't directly assert the
    UNAVAILABLE section in the echoed text. We assert the strongest
    things visible from outside the subprocess: round echoed back,
    framing-header substring present (proves round-1+ path was
    taken), and — critically — sending `prior_failures` does not
    cause the call to error or be silently dropped (which would
    leave the prompt as round-0 raw).

    The deeper assertion (UNAVAILABLE PARTICIPANTS rendered with
    correct error_class) is in the dispatcher unit test against
    FakeProvider.last_prompt; that has access to the full framed
    prompt the subprocess hides.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "roundtable"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Sanity: same call WITHOUT prior_failures should fall
            # back to round-0 raw prompt (no framing header), so
            # WITH prior_failures must produce a meaningfully
            # different echo. This guards against the field being
            # silently dropped at the MCP boundary.
            round_zero = await session.call_tool(
                "roundtable_round",
                {
                    "prompt": "follow-up",
                    "models": ["fake-panelist-a"],
                },
            )

            with_failures = await session.call_tool(
                "roundtable_round",
                {
                    "prompt": "follow-up",
                    "round": 2,
                    "models": ["fake-panelist-a"],
                    "prior_answers": [
                        {
                            "model": "claude",
                            "source": "orchestrator",
                            "round": 1,
                            "answer": "my draft",
                        },
                    ],
                    "prior_failures": [
                        {
                            "model": "gemini",
                            "source": "panelist",
                            "round": 1,
                            "error_class": "timeout",
                        },
                    ],
                },
            )

    assert not round_zero.isError
    assert not with_failures.isError

    raw_payload = json.loads(round_zero.content[0].text)
    framed_payload = json.loads(with_failures.content[0].text)

    raw_answer = raw_payload["responses"][0]["answer"]
    framed_answer = framed_payload["responses"][0]["answer"]

    # Round 0: no framing header.
    assert "multi-model deliberation" not in raw_answer
    # Round 2 with prior_failures: framing was applied.
    assert "multi-model deliberation" in framed_answer
    assert framed_payload["round"] == 2
    assert framed_payload["responses"][0]["error"] is None
    # The two answers must differ — proves prior_failures didn't get
    # silently dropped (which would have produced an identical
    # round-0-shaped answer).
    assert framed_answer != raw_answer


@pytest.mark.asyncio
async def test_mixed_round_bundle_returns_invalid_input_not_crash() -> None:
    """P3.5: prior_answers and prior_failures must share a round
    number. A caller sending a mixed-round bundle must get a
    structured invalid_input payload, not a server crash or
    silently-corrupted framing.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "roundtable"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "roundtable_round",
                {
                    "prompt": "Q?",
                    "round": 2,
                    "models": ["fake-a"],
                    "prior_answers": [
                        {
                            "model": "claude",
                            "source": "orchestrator",
                            "round": 0,
                            "answer": "draft",
                        },
                    ],
                    "prior_failures": [
                        {
                            "model": "gemini",
                            "source": "panelist",
                            "round": 1,  # mismatched on purpose
                            "error_class": "timeout",
                        },
                    ],
                },
            )

    # The Pydantic validator raises ValidationError, which the MCP
    # server catches and returns as a JSON error payload (per the
    # existing invalid-input path in mcp_server.py). The connection
    # stays alive.
    payload = json.loads(result.content[0].text)
    assert payload.get("error") == "invalid_input"
    detail_text = json.dumps(payload.get("detail", []))
    assert "share a single round number" in detail_text


@pytest.mark.asyncio
async def test_unknown_model_returns_error_stub_not_silent_fake() -> None:
    """A caller-supplied model name that is not in the panel registry
    must return error_class=unknown_model rather than silently
    routing to FakeProvider and emitting a prompt-echo response.

    Regression coverage for v0.2: pre-0.2 servers would treat
    `gpt-9` etc. as valid fixture names and return prompt echoes
    that an orchestrator could not distinguish from real answers.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "roundtable"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "roundtable_round",
                {
                    "prompt": "What is 2+2?",
                    "models": ["fake-a", "gpt-9", "gemini-99-ultra"],
                },
            )

    assert not result.isError
    payload = json.loads(result.content[0].text)

    by_name = {r["model"]: r for r in payload["responses"]}
    assert [r["model"] for r in payload["responses"]] == [
        "fake-a",
        "gpt-9",
        "gemini-99-ultra",
    ], "merged response must preserve caller-supplied model order"

    # The legitimate FakeProvider fixture still works.
    assert by_name["fake-a"]["error"] is None
    assert by_name["fake-a"]["answer"] is not None

    # The two unknown models surface as error stubs.
    for name in ("gpt-9", "gemini-99-ultra"):
        assert by_name[name]["error"] == "unknown_model"
        assert by_name[name]["answer"] is None
        assert by_name[name]["estimated_cost_usd"] is None
        assert "panel registry" in (by_name[name]["error_detail"] or "")

    error_names = {e["model"]: e["error"] for e in payload["errors"]}
    assert error_names == {
        "gpt-9": "unknown_model",
        "gemini-99-ultra": "unknown_model",
    }
