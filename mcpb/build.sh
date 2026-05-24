#!/usr/bin/env bash
# Build the Roundtable MCP bundle (.mcpb) for Claude Desktop.
#
# Usage:  ./mcpb/build.sh
# Output: dist/roundtable-<version>.mcpb
#
# Requires Node.js (for `npx @anthropic-ai/mcpb pack`).
#
# This script also injects the TOOL_DESCRIPTION constant from
# roundtable/mcp_server.py into the staged manifest. The runtime
# server reads TOOL_DESCRIPTION from the Python source at startup
# (via list_tools); the manifest needs the same string baked in so
# Claude Desktop's install UI shows the current text without
# launching the server first. Auto-injection prevents the two from
# drifting silently between releases.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/mcpb"
PKG="$ROOT/roundtable"
BUILD="$(mktemp -d -t roundtable-mcpb.XXXXXX)"
OUT_DIR="$ROOT/dist"

trap 'rm -rf "$BUILD"' EXIT

if [[ ! -d "$PKG" ]]; then
  echo "ERROR: $PKG not found — run from a clean checkout." >&2
  exit 1
fi
if [[ ! -f "$PKG/mcp_server.py" ]]; then
  echo "ERROR: $PKG/mcp_server.py not found — bundle requires the server module." >&2
  exit 1
fi
if [[ ! -f "$SRC/manifest.json" ]]; then
  echo "ERROR: $SRC/manifest.json not found." >&2
  exit 1
fi
if [[ ! -f "$SRC/pyproject.toml" ]]; then
  echo "ERROR: $SRC/pyproject.toml not found." >&2
  exit 1
fi

echo "Staging bundle in $BUILD"
cp -R "$PKG"             "$BUILD/roundtable"
cp "$SRC/pyproject.toml" "$BUILD/"

# Strip __pycache__ that may have been created by tests.
find "$BUILD" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Inject TOOL_DESCRIPTION from the Python source into the staged
# manifest. The Python source is the source of truth; the committed
# manifest at mcpb/manifest.json is kept in sync via a unit test,
# but this step ensures the SHIPPED bundle cannot diverge even if
# the test was bypassed.
echo "Injecting TOOL_DESCRIPTION from roundtable/mcp_server.py into manifest"
ROOT="$ROOT" SRC="$SRC" python3 - <<'PYEOF' > "$BUILD/manifest.json"
import json
import os
import sys

root = os.environ["ROOT"]
src = os.environ["SRC"]
sys.path.insert(0, root)

from roundtable.mcp_server import TOOL_DESCRIPTION

with open(os.path.join(src, "manifest.json")) as f:
    manifest = json.load(f)

# Roundtable has exactly one tool. If that ever changes, this script
# needs to grow a name match.
assert len(manifest["tools"]) == 1, (
    f"build.sh expects exactly one tool in the manifest; "
    f"found {len(manifest['tools'])}"
)
assert manifest["tools"][0]["name"] == "roundtable_round", (
    f"build.sh expects tool name 'roundtable_round'; "
    f"found {manifest['tools'][0]['name']!r}"
)

manifest["tools"][0]["description"] = TOOL_DESCRIPTION

print(json.dumps(manifest, indent=2))
PYEOF

# Derive output filename from manifest version.
VERSION="$(python3 -c "import json; print(json.load(open('$BUILD/manifest.json'))['version'])")"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/roundtable-${VERSION}.mcpb"

echo "Packing $OUT"
(cd "$BUILD" && npx -y @anthropic-ai/mcpb pack . "$OUT")

# Generate the sha256 alongside, using just the basename so the
# sidecar is path-independent (works in CI, doesn't leak the
# author's home directory).
(cd "$OUT_DIR" && shasum -a 256 "$(basename "$OUT")" > "$(basename "$OUT").sha256")

echo
echo "Built: $OUT"
echo "Size:  $(du -h "$OUT" | awk '{print $1}')"
echo "SHA:   $(cat "$OUT.sha256")"
