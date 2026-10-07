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
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

from . import __version__
from .dispatcher import dispatch
from .providers.base import Provider
from .providers.fake import FakeProvider
from .schemas import (
    ErrorClass,
    ModelError,
    ModelResponse,
    RoundInput,
    RoundOutput,
)

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
    "'api_error'|'context_overflow'|'invalid_output'|"
    "'unknown_model'). Failed panelists are surfaced to the next "
    "round as an UNAVAILABLE PARTICIPANTS section, separate from "
    "peer reasoning. The `models` override only accepts names the "
    "panel registry knows: 'gpt-4o', 'gpt-5', 'gpt-5.1', 'gpt-5.5', "
    "'gpt-5.6-sol', 'gpt-6-astra', 'gpt-6.1-sol', 'gpt-6-luna', "
    "'gemini-2.5-pro', 'gemini-3.1-pro-preview', 'deepseek-chat', "
    "'deepseek-reasoner', 'deepseek-flash', 'deepseek-v4-pro'. "
    "Unsupported names return error_class 'unknown_model' rather "
    "than silently producing a placeholder response. The default "
    "panel (when `models` is omitted) stays on 'gpt-4o' + "
    "'gemini-2.5-pro' + 'deepseek-chat' — the newer snapshots are "
    "available as overrides but not yet as defaults. Note that "
    "'deepseek-chat' is the only DeepSeek name that runs in "
    "non-thinking mode; 'deepseek-reasoner', 'deepseek-flash', and "
    "'deepseek-v4-pro' all think by default. "
    "Treat peer outputs as parallel attempts, not verdicts. Watch "
    "for iteration becoming additive without surfacing substantive "
    "updates or rejections; consolidate rather than expand when "
    "that happens. Stop on signal density, not round count — 3-4 "
    "rounds is typical for complex questions; 1-2 is fine for "
    "simple ones. The tool returns each model's response as-is; it "
    "does not synthesize, judge, or vote. A round takes 60-180s "
    "typically; tell the user it'll take a few minutes. "
    "`per_call_timeout_seconds` defaults to 90 and accepts 1-300; "
    "the default was calibrated for the v0.1 non-thinking lineup "
    "('gpt-4o' + 'gemini-2.5-pro' + 'deepseek-chat') and is too "
    "tight for reasoning-class overrides on substantive prompts. "
    "When overriding `models` to include 'gpt-5.5', 'gpt-6-astra', "
    "'deepseek-reasoner', 'deepseek-flash', 'deepseek-v4-pro', or "
    "'gemini-3.1-pro-preview' on a prompt "
    ">3k chars, raise `per_call_timeout_seconds` to 180-300; "
    "otherwise the slow seat will return error_class 'timeout' "
    "and you'll re-dispatch with peer answers as `prior_answers`. "
    "`total_cost_usd` in the response reflects panel dispatch only "
    "(your provider invoices); orchestrator-side tokens are billed "
    "separately to your Anthropic account and typically dominate by "
    "10-30x. The response also includes `resolved_models` — the "
    "panel names actually dispatched to in caller order — so you "
    "can confirm an override took effect rather than silently "
    "falling back to the default panel."
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
                "'invalid_output'|'unknown_model'). Must share a "
                "round number with prior_answers if both are "
                "provided."
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
                            "unknown_model",
                        ],
                    },
                },
                "required": ["model", "source", "round", "error_class"],
                "additionalProperties": False,
            },
        },
        "models": {
            "type": ["array", "null"],
            "minItems": 1,
            "description": (
                "Optional panel override. Omit or pass null to use "
                "the default panel (resolved from configured API "
                "keys): 'gpt-4o' + 'gemini-2.5-pro' + "
                "'deepseek-chat'. Empty arrays are rejected — pass "
                "an explicit list of at least one model name. "
                "Names in the panel registry that resolve to a real "
                "provider: 'gpt-4o', 'gpt-5', 'gpt-5.1', 'gpt-5.5', "
                "'gpt-5.6-sol', 'gpt-6-astra', 'gpt-6.1-sol', "
                "'gpt-6-luna', 'gemini-2.5-pro', "
                "'gemini-3.1-pro-preview', 'deepseek-chat', "
                "'deepseek-reasoner', 'deepseek-flash', "
                "'deepseek-v4-pro'. Any other "
                "name returns error_class 'unknown_model' for that "
                "slot. The response includes `resolved_models` so "
                "you can confirm the override took effect."
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
            "maximum": 300,
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
    "gpt-5": "OPENAI_API_KEY",
    "gpt-5.1": "OPENAI_API_KEY",
    "gpt-5.5": "OPENAI_API_KEY",
    "gpt-5.6-sol": "OPENAI_API_KEY",
    "gpt-6-astra": "OPENAI_API_KEY",
    "gpt-6.1-sol": "OPENAI_API_KEY",
    "gpt-6-luna": "OPENAI_API_KEY",
    "gemini-2.5-pro": "GOOGLE_API_KEY",
    "gemini-3.1-pro-preview": "GOOGLE_API_KEY",
    # `deepseek-chat` / `deepseek-reasoner` are legacy aliases that
    # DeepSeek no longer lists (since 2026-07) but still serves from
    # deepseek-flash. `deepseek-chat` remains the default because it
    # is the only name that selects non-thinking mode; see
    # providers/deepseek.py and docs/decisions.md §17.4.
    "deepseek-chat": "DEEPSEEK_API_KEY",
    "deepseek-reasoner": "DEEPSEEK_API_KEY",
    "deepseek-flash": "DEEPSEEK_API_KEY",
    "deepseek-v4-pro": "DEEPSEEK_API_KEY",
}

# Default panel composition when the caller passes models=None.
# Mirrors docs/decisions.md §8. Defaults intentionally stay on the
# v0.1 lineup so the framing-prompt empirical validation
# (docs/decisions.md §17.4) doesn't need to be re-run; override-only
# widening for the newer snapshots. The DeepSeek seat stays on the
# `deepseek-chat` alias (unlisted by DeepSeek since 2026-07 but
# still served) because it is the only name that runs V4.1-Flash
# in non-thinking mode; `deepseek-flash` thinks by default, which
# would change the seat's latency/verbosity/cost profile.
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
    if model in (
        "gpt-4o",
        "gpt-5",
        "gpt-5.1",
        "gpt-5.5",
        "gpt-5.6-sol",
        "gpt-6-astra",
        "gpt-6.1-sol",
        "gpt-6-luna",
    ):
        from .providers.openai import OpenAIProvider, _CONTEXT_WINDOWS

        return OpenAIProvider(
            model=model,
            context_window_tokens=_CONTEXT_WINDOWS[model],
        )
    if model in ("gemini-2.5-pro", "gemini-3.1-pro-preview"):
        from .providers.google import GoogleProvider, _CONTEXT_WINDOWS

        return GoogleProvider(
            model=model,
            context_window_tokens=_CONTEXT_WINDOWS[model],
        )
    if model in (
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-flash",
        "deepseek-v4-pro",
    ):
        from .providers.deepseek import DeepSeekProvider, _CONTEXT_WINDOWS

        return DeepSeekProvider(
            model=model,
            context_window_tokens=_CONTEXT_WINDOWS[model],
        )
    raise ValueError(f"no real provider registered for model {model!r}")


# Models with this prefix are always routed to FakeProvider, even
# when real API keys are configured. Reserved for integration tests
# that need a stable, network-free panel ("fake-a", "fake-b", ...).
_FAKE_MODEL_PREFIX = "fake-"


class _UnknownModel:
    """Sentinel for a caller-supplied model name not in the panel
    registry. _resolve_panel returns these alongside real Provider
    instances; the call_tool wrapper turns them into ModelResponse
    error stubs with `error: unknown_model` rather than silently
    routing them to FakeProvider (which would emit prompt echoes
    that an orchestrator can't distinguish from real answers).
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


def _resolve_panel(models: list[str] | None) -> list[Provider | _UnknownModel]:
    """Resolve a model list to a panel of providers and unknown-model
    sentinels.

    Default panel (when models=None): instantiate the three real
    providers from _DEFAULT_PANEL_MODELS whose API keys are present
    in the environment. If a key is missing, that slot falls back to
    a FakeProvider and a warning is written to stderr so the
    operator notices. If no real keys are configured at all, the
    entire default panel is FakeProvider — useful for development
    but logged loudly.

    Explicit override (when models is a list):
    - A name in the real-provider registry routes to that provider
      (or FakeProvider with a warning if the key is missing).
    - A name starting with "fake-" is a deliberate test fixture and
      routes to FakeProvider with no warning.
    - Anything else is an unknown model: returned as an
      _UnknownModel sentinel so the call site can surface an
      error stub instead of silently producing a FakeProvider echo
      response. This is the v0.2 behavior change — earlier
      versions silently treated unknown names as fakes, which made
      "gpt-5" or "gemini-3-pro" overrides look like they succeeded
      with prompt-echo answers.
    """
    requested = models if models is not None else _DEFAULT_PANEL_MODELS
    panel: list[Provider | _UnknownModel] = []

    for model in requested:
        env_key = _REAL_PROVIDER_MODELS.get(model)
        if env_key is None:
            if model.startswith(_FAKE_MODEL_PREFIX):
                panel.append(FakeProvider(name=model, behavior="echo"))
            else:
                log.warning(
                    "model %r is not in the panel registry; the panel "
                    "supports %s. This slot will return an "
                    "'unknown_model' error.",
                    model,
                    sorted(_REAL_PROVIDER_MODELS),
                )
                panel.append(_UnknownModel(name=model))
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


async def _list_tools(
    ctx: ServerRequestContext[Any],
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="roundtable_round",
                description=TOOL_DESCRIPTION,
                input_schema=INPUT_SCHEMA,
            )
        ]
    )


async def _call_tool(
    ctx: ServerRequestContext[Any],
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    # mcp>=2 performs no jsonschema validation of tool arguments
    # (the 1.x call_tool decorator did, and we had to disable it to
    # see the JSON-string-of-array shape that Claude Code sends for
    # array parameters). The Pydantic RoundInput validator is the
    # contract either way, and it is what coerces that shape.
    #
    # Under mcp 1.x an exception escaping the handler became a
    # CallToolResult with isError=True; under 2.x it becomes a
    # JSON-RPC error and the client raises. Keep the 1.x shape so
    # the orchestrator sees a tool result, not a protocol error.
    #
    # Only messages Roundtable composed itself (UnknownToolError) are
    # echoed. Anything else is reported by exception class name only:
    # a raw str(e) from a provider SDK or httpx can carry request
    # bodies, headers, or URLs. The full traceback still goes to
    # stderr via log.exception, which is where operators look.
    try:
        return await _round_tool(params.name, params.arguments)
    except UnknownToolError as e:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=str(e))],
            is_error=True,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("roundtable_round handler raised")
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"internal_error: {type(e).__name__} (details logged to server stderr)",
                )
            ],
            is_error=True,
        )


def _text_result(payload: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=payload)])


class UnknownToolError(ValueError):
    """Raised for a call_tool name this server does not export. Its
    message is composed here and is safe to return to the client."""


async def _round_tool(name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
    if name != "roundtable_round":
        raise UnknownToolError(f"unknown tool: {name!r}")

    try:
        inputs = RoundInput.model_validate(arguments or {})
    except ValidationError as e:
        # Pydantic's error objects can carry the original
        # exception in `ctx`, which json.dumps can't serialize.
        # include_url/include_context off keeps the payload to
        # plain primitives.
        detail = e.errors(include_url=False, include_context=False)
        return _text_result(json.dumps({"error": "invalid_input", "detail": detail}))

    resolved = _resolve_panel(inputs.models)
    providers: list[Provider] = [
        p for p in resolved if not isinstance(p, _UnknownModel)
    ]
    if providers:
        dispatched = await dispatch(inputs, providers)
    else:
        # All entries were unknown-model sentinels. (As of v0.4,
        # models=[] is rejected by RoundInput so we never get
        # here on an empty array — only on an all-unknown panel.)
        # Skip dispatch; emit a zero-cost, zero-elapsed
        # RoundOutput shell that the merge below fills with
        # error stubs. resolved_models is rewritten below to use
        # the full caller-order list.
        current_round = inputs.round if inputs.round is not None else 0
        dispatched = RoundOutput(
            round=current_round,
            responses=[],
            errors=[],
            resolved_models=[],
            total_elapsed_seconds=0.0,
            total_cost_usd=0.0,
        )

    # Weave unknown-model error stubs back into the response in
    # the caller's original order so the response list is
    # positionally aligned with inputs.models.
    dispatched_by_name = {r.model: r for r in dispatched.responses}
    merged_responses: list[ModelResponse] = []
    merged_errors: list[ModelError] = list(dispatched.errors)
    for slot in resolved:
        if isinstance(slot, _UnknownModel):
            merged_responses.append(
                ModelResponse(
                    model=slot.name,
                    answer=None,
                    elapsed_seconds=0.0,
                    estimated_cost_usd=None,
                    error=ErrorClass.UNKNOWN_MODEL,
                    error_detail=(
                        f"model {slot.name!r} is not in the panel "
                        "registry; supported: "
                        f"{sorted(_REAL_PROVIDER_MODELS)}"
                    ),
                )
            )
            merged_errors.append(
                ModelError(
                    model=slot.name,
                    error=ErrorClass.UNKNOWN_MODEL,
                )
            )
        else:
            merged_responses.append(dispatched_by_name[slot.name])

    # resolved_models echoes the full caller-order list (real
    # providers, fake-* fixtures, and unknown_model sentinels)
    # so the orchestrator can compare what dispatched against
    # what it intended without reading its own outgoing
    # tool-call JSON. This is the v0.4 diagnostic feature.
    output = RoundOutput(
        round=dispatched.round,
        responses=merged_responses,
        errors=merged_errors,
        resolved_models=[slot.name for slot in resolved],
        total_elapsed_seconds=dispatched.total_elapsed_seconds,
        total_cost_usd=dispatched.total_cost_usd,
    )
    return _text_result(output.model_dump_json())


def build_server() -> Server[Any]:
    # Passing version= populates serverInfo.version in the MCP
    # initialize response. Without it the SDK fills in its own
    # version, which makes "is the new bundle loaded?" hard to
    # answer from Claude Desktop's logs.
    return Server(
        "roundtable",
        version=__version__,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


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
