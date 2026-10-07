"""The call_tool catch-all must not echo raw exception text.

A provider SDK or httpx exception can carry request bodies, headers,
or URLs in str(e). The handler reports the exception class only and
leaves the detail on stderr. The one message the server composes
itself (unknown tool) is returned verbatim so the orchestrator can
tell a typo from a server fault.
"""

from __future__ import annotations

import pytest
from mcp import types

from roundtable import mcp_server


@pytest.mark.asyncio
async def test_unexpected_exception_text_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "Bearer sk-live-SHOULD-NOT-LEAK body={'prompt': 'private'}"

    async def boom(name: str, arguments: dict | None) -> types.CallToolResult:
        raise RuntimeError(secret)

    monkeypatch.setattr(mcp_server, "_round_tool", boom)
    params = types.CallToolRequestParams(name="roundtable_round", arguments={"prompt": "x"})

    result = await mcp_server._call_tool(None, params)  # type: ignore[arg-type]

    assert result.is_error
    text = result.content[0].text
    assert "RuntimeError" in text
    assert "internal_error" in text
    assert "sk-live" not in text
    assert "private" not in text


@pytest.mark.asyncio
async def test_unknown_tool_message_is_returned_verbatim() -> None:
    params = types.CallToolRequestParams(name="no_such_tool", arguments={})

    result = await mcp_server._call_tool(None, params)  # type: ignore[arg-type]

    assert result.is_error
    assert result.content[0].text == "unknown tool: 'no_such_tool'"
