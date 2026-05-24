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
import os
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

from .dispatcher import dispatch
from .providers.base import Provider
from .providers.fake import FakeProvider
from .schemas import RoundInput

# Real provider classes are imported lazily inside _resolve_panel
# so the server can boot without the SDKs installed (e.g., in a
# minimal test environment where only FakeProvider is needed).

log = logging.getLogger("roundtable.mcp_server")

# The text Claude reads when deciding whether to call this tool.
# Part of the version contract. Edit deliberately.
TOOL_DESCRIPTION = (
    "Dispatch a prompt to a panel of other LLMs in parallel and "
    "return their raw answers. For round 0, pass only the prompt. "
    "For rounds 1+, also pass the prior round's results: "
    "`prior_answers` for successful panelists (each entry: `model`, "
    "`source` 'orchestrator'|'panelist', `round`, `answer`) and "
    "`prior_failures` for panelists that failed last round (each "
    "entry: `model`, `source`, `round`, `error_class` 'timeout'|"
    "'api_error'|'context_overflow'|'invalid_output'). Failed "
    "panelists are surfaced to the next round as an UNAVAILABLE "
    "PARTICIPANTS section, separate from peer reasoning. "
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
                "Round 1+ only. Successful prior-round answers. Each "
                "entry: model, source ('orchestrator'|'panelist'), "
                "round (int), answer."
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
        "prior_failures": {
            "type": ["array", "null"],
            "description": (
                "Round 1+ only. Panelists that failed on the prior "
                "round. Surfaced as UNAVAILABLE PARTICIPANTS in the "
                "round-1+ framing (D1). Each entry: model, source, "
                "round, error_class "
                "('timeout'|'api_error'|'context_overflow'|"
                "'invalid_output'). Must share a round number with "
                "prior_answers if both are provided."
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
                    "error_class": {
                        "type": "string",
                        "enum": [
                            "timeout",
                            "api_error",
                            "context_overflow",
                            "invalid_output",
                        ],
                    },
                },
                "required": ["model", "source", "round", "error_class"],
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


# Known real-provider model IDs and their corresponding env-var keys.
# Used to detect when a caller-supplied model name should be wired to
# a real SDK rather than FakeProvider.
_REAL_PROVIDER_MODELS: dict[str, str] = {
    "gpt-4o": "OPENAI_API_KEY",
    "gemini-2.5-pro": "GOOGLE_API_KEY",
    "deepseek-chat": "DEEPSEEK_API_KEY",
}

# Default panel composition when the caller passes models=None.
# Mirrors docs/decisions.md §8.
_DEFAULT_PANEL_MODELS: list[str] = [
    "gpt-4o",
    "gemini-2.5-pro",
    "deepseek-chat",
]


def _make_real_provider(model: str) -> Provider:
    """Lazy-import and construct the real provider for a given model.

    Each provider's __init__ reads its API key from the env var and
    raises if missing. The caller is responsible for verifying the
    key is present before calling this.
    """
    if model == "gpt-4o":
        from .providers.openai import OpenAIProvider

        return OpenAIProvider(model=model)
    if model == "gemini-2.5-pro":
        from .providers.google import GoogleProvider

        return GoogleProvider(model=model)
    if model == "deepseek-chat":
        from .providers.deepseek import DeepSeekProvider

        return DeepSeekProvider(model=model)
    raise ValueError(f"no real provider registered for model {model!r}")


def _resolve_panel(models: list[str] | None) -> list[Provider]:
    """Resolve a model list to a panel of Provider instances.

    Default panel (when models=None): instantiate the three real
    providers from _DEFAULT_PANEL_MODELS whose API keys are present
    in the environment. If a key is missing, that slot falls back to
    a FakeProvider and a warning is written to stderr so the
    operator notices. If no real keys are configured at all, the
    entire default panel is FakeProvider — useful for development
    but logged loudly.

    Explicit override (when models is a list): for each name, if it
    matches a known real-provider model and the corresponding key
    is set, instantiate the real provider; otherwise FakeProvider.
    This lets integration tests pass models like ["fake-a"] without
    needing API keys, while still routing "gpt-4o" through the real
    SDK when keys are configured.
    """
    requested = models if models is not None else _DEFAULT_PANEL_MODELS
    panel: list[Provider] = []

    for model in requested:
        env_key = _REAL_PROVIDER_MODELS.get(model)
        if env_key is None:
            # Unknown model name — treat as a fake fixture.
            panel.append(FakeProvider(name=model, behavior="echo"))
            continue

        if not os.environ.get(env_key):
            log.warning(
                "%s requested but %s is not set; using FakeProvider. "
                "Set %s to enable real dispatch.",
                model,
                env_key,
                env_key,
            )
            panel.append(FakeProvider(name=model, behavior="echo"))
            continue

        try:
            panel.append(_make_real_provider(model))
        except ImportError as e:
            log.error(
                "SDK for %s is not installed (%s); falling back to "
                "FakeProvider. This indicates a packaging bug — "
                "the bundle's mcpb/pyproject.toml should include the "
                "required SDK.",
                model,
                e,
            )
            panel.append(FakeProvider(name=model, behavior="echo"))
        except Exception as e:  # noqa: BLE001
            log.warning(
                "failed to construct real provider for %s (%s); "
                "falling back to FakeProvider",
                model,
                e,
            )
            panel.append(FakeProvider(name=model, behavior="echo"))

    return panel


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
            # Pydantic's error objects can carry the original
            # exception in `ctx`, which json.dumps can't serialize.
            # include_url/include_context off keeps the payload to
            # plain primitives.
            detail = e.errors(include_url=False, include_context=False)
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {"error": "invalid_input", "detail": detail},
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
