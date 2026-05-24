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
