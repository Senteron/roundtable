"""Launch the MCP server via the manifest's actual command and args.

The existing `test_mcp_startup.py` bypasses the manifest entirely by
calling `sys.executable -m roundtable` directly. That's fine for
testing the server code, but it cannot catch a bug where the
manifest's `command` and `args` are themselves broken (wrong shape,
missing substitution, wrong binary name).

This test reads `mcpb/manifest.json`, extracts `server.mcp_config`,
resolves `${__dirname}` to the repo root (the v0.1 bundle layout
places `roundtable/` at the same level as the manifest, so the repo
root is a valid stand-in), and launches the server through the
declared command. This catches the exact defect class that the
original code review flagged: the manifest claims an entry point or
launcher shape that doesn't actually work.

Requires `uv` on PATH — the same requirement Claude Desktop has at
install time. The test is skipped (not failed) if `uv` is absent.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_manifest_command() -> tuple[str, list[str]]:
    """Read mcpb/manifest.json and return (command, args) with
    ${__dirname} substituted to point at the repo root."""
    with (_repo_root() / "mcpb" / "manifest.json").open() as f:
        manifest = json.load(f)
    cfg = manifest["server"]["mcp_config"]
    command = cfg["command"]
    args = [
        a.replace("${__dirname}", str(_repo_root()))
        for a in cfg["args"]
    ]
    return command, args


@pytest.mark.asyncio
async def test_manifest_command_launches_server() -> None:
    """The exact `command` + `args` Claude Desktop will use must
    launch a working MCP server. This is the test that would catch
    a broken manifest command shape regardless of whether
    `python -m roundtable` (the dev path) still works.
    """
    command, args = _resolve_manifest_command()

    if shutil.which(command) is None:
        pytest.skip(
            f"manifest command {command!r} is not on PATH; "
            f"skipping (this is the same requirement Claude Desktop "
            f"has at install time)"
        )

    params = StdioServerParameters(command=command, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    assert len(tools.tools) == 1
    assert tools.tools[0].name == "roundtable_round"
