"""TOOL_DESCRIPTION must match the committed manifest's tool description.

The Python source (`roundtable.mcp_server.TOOL_DESCRIPTION`) is the
source of truth; `mcpb/build.sh` injects it into the manifest at
bundle time. This test guards the COMMITTED manifest from drifting
between rebuilds. If `mcpb/build.sh` is invoked, this test would pass
trivially afterward; if a contributor edits one and not the other,
this catches it before push.

Pairs with D5 in docs/review-concerns-plan.md: the framing prompt
and the tool description are the two version-contract strings.
"""

from __future__ import annotations

import json
from pathlib import Path

from roundtable.mcp_server import TOOL_DESCRIPTION


def test_tool_description_in_manifest_matches_python_source() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with (repo_root / "mcpb" / "manifest.json").open() as f:
        manifest = json.load(f)

    assert len(manifest["tools"]) == 1, (
        f"manifest must declare exactly one tool; "
        f"found {len(manifest['tools'])}"
    )
    assert manifest["tools"][0]["name"] == "roundtable_round", (
        f"manifest tool name must be 'roundtable_round'; "
        f"found {manifest['tools'][0]['name']!r}"
    )

    manifest_description = manifest["tools"][0]["description"]
    assert manifest_description == TOOL_DESCRIPTION, (
        "mcpb/manifest.json tools[0].description has drifted from "
        "roundtable.mcp_server.TOOL_DESCRIPTION. Run ./mcpb/build.sh "
        "to inject the current TOOL_DESCRIPTION into the staged "
        "manifest, then copy the relevant change back to "
        "mcpb/manifest.json (the committed manifest)."
    )
