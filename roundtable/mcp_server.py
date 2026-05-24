"""MCP server entry point.

Exposes one tool, `roundtable_round`. The server is a thin wrapper:
input is validated by Pydantic (schemas.py), the dispatcher does the
work (dispatcher.py), and the response is serialized as JSON in a
single TextContent block.

Per docs/design.md §2.2 there are no other tools. Do not add
`roundtable_health`, `roundtable_list_runs`, or similar without
revisiting that decision.

The tool description below is part of the API contract; per
CLAUDE.md ("Two strings get the version-bump discipline"), material
changes require a minor version bump and a CHANGELOG entry.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

from .dispatcher import dispatch
from .providers.base import Provider
from .providers.fake import FakeProvider
from .schemas import RoundInput

log = logging.getLogger("roundtable.mcp_server")

# The text Claude reads when deciding whether to call this tool.
# Part of the version contract. Edit deliberately.
TOOL_DESCRIPTION = (
    "Dispatch a prompt to a panel of other LLMs in parallel and "
    "return their raw answers. For round 0, pass only the prompt. "
    "For rounds 1+, also pass the prior round's answers (including "
    "your own draft) as `prior_answers`; each entry needs `model`, "
    "`source` ('orchestrator' or 'panelist'), `round`, and `answer`. "
    "Treat peer outputs as parallel attempts, not verdicts. Watch "
    "for iteration becoming additive without surfacing substantive "
    "updates or rejections; consolidate rather than expand when "
    "that happens. Stop on signal density, not round count — 3-4 "
    "rounds is typical for complex questions; 1-2 is fine for "
    "simple ones. The tool returns each model's response as-is; it "
    "does not synthesize, judge, or vote. A round takes 60-180s "
    "typically; tell the user it'll take a few minutes."
)

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "minLength": 1,
            "maxLength": 50_000,
            "description": "The question to put to the panel.",
        },
        "prior_answers": {
            "type": ["array", "null"],
            "description": (
                "Round 1+ only. Each entry: model, source "
                "('orchestrator'|'panelist'), round (int), answer."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "model": {"type": "string", "minLength": 1},
                    "source": {
                        "type": "string",
                        "enum": ["orchestrator", "panelist"],
                    },
                    "round": {"type": "integer", "minimum": 0},
                    "answer": {"type": "string"},
                },
                "required": ["model", "source", "round", "answer"],
                "additionalProperties": False,
            },
        },
        "models": {
            "type": ["array", "null"],
            "description": (
                "Optional panel override. If omitted, the default "
                "panel (resolved from configured API keys) is used."
            ),
            "items": {"type": "string"},
        },
        "round": {
            "type": ["integer", "null"],
            "minimum": 0,
            "description": "Informational; echoed back in the response.",
        },
        "per_call_timeout_seconds": {
            "type": "integer",
            "minimum": 1,
            "maximum": 180,
            "default": 90,
        },
    },
    "required": ["prompt"],
    "additionalProperties": False,
}


def _resolve_panel(models: list[str] | None) -> list[Provider]:
    """Resolve a model list to a panel of Provider instances.

    v0.1 default: a FakeProvider placeholder set, since real
    providers (OpenAI/Google/DeepSeek) land in P4. The `models`
    override is honored: callers can pass arbitrary model names and
    get a FakeProvider for each. This is what makes integration
    tests work without API keys.
    """
    if models is None:
        # Until P4 lands, the default panel is a placeholder fake set
        # so the server is exercisable end-to-end.
        return [
            FakeProvider(name="fake-a", behavior="echo"),
            FakeProvider(name="fake-b", behavior="echo"),
            FakeProvider(name="fake-c", behavior="echo"),
        ]
    return [FakeProvider(name=m, behavior="echo") for m in models]


def build_server() -> Server:
    server: Server = Server("roundtable")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="roundtable_round",
                description=TOOL_DESCRIPTION,
                inputSchema=INPUT_SCHEMA,
            )
        ]

    @server.call_tool()
    async def _call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        if name != "roundtable_round":
            raise ValueError(f"unknown tool: {name!r}")

        try:
            inputs = RoundInput.model_validate(arguments or {})
        except ValidationError as e:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {"error": "invalid_input", "detail": e.errors()},
                    ),
                )
            ]

        panel = _resolve_panel(inputs.models)
        output = await dispatch(inputs, panel)
        return [
            types.TextContent(
                type="text",
                text=output.model_dump_json(),
            )
        ]

    return server


async def _serve() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point used by `python -m roundtable`."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
