#!/usr/bin/env bash
# Verify dist/roundtable-<version>.mcpb is up to date with roundtable/.
#
# Used by CI (.github/workflows/mcpb-up-to-date.yml) and by humans
# before pushing. Run from the repo root:
#
#   ./scripts/check_mcpb_freshness.sh
#
# Behavior: builds the bundle into a temp dir, extracts both the live
# bundle (dist/) and the freshly-built one, diffs the packaged
# roundtable/ tree byte-for-byte. Non-zero exit (with a clear message)
# if they differ. Exits 0 silently when they match.
#
# This catches the common failure mode where a contributor edits
# roundtable/ but forgets to run `./mcpb/build.sh`. See CLAUDE.md
# "Always rebuild the .mcpb bundle when MCP code changes" for the
# rationale.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Read the declared bundle version from the manifest.
VERSION="$(python3 -c "import json; print(json.load(open('$ROOT/mcpb/manifest.json'))['version'])")"
ARTIFACT="$ROOT/dist/roundtable-${VERSION}.mcpb"

if [[ ! -f "$ARTIFACT" ]]; then
  echo "✘ Missing artifact: $ARTIFACT" >&2
  echo "  mcpb/manifest.json declares version $VERSION but dist/ has no matching bundle." >&2
  echo "  Run: ./mcpb/build.sh" >&2
  exit 1
fi

WORK="$(mktemp -d -t mcpb-freshness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
LIVE="$WORK/live"
FRESH_DIST="$WORK/fresh-dist"
FRESH_EXTRACT="$WORK/fresh-extract"
mkdir -p "$LIVE" "$FRESH_EXTRACT"

# Extract the live bundle.
unzip -q "$ARTIFACT" -d "$LIVE"

# Back up the committed artifact so we can restore it after the rebuild
# overwrites it.
COMMITTED_BACKUP="$WORK/committed-backup.mcpb"
COMMITTED_SHA_BACKUP=""
cp "$ARTIFACT" "$COMMITTED_BACKUP"
if [[ -f "$ARTIFACT.sha256" ]]; then
  COMMITTED_SHA_BACKUP="$WORK/committed-backup.sha256"
  cp "$ARTIFACT.sha256" "$COMMITTED_SHA_BACKUP"
fi

# Run the build (writes to $ROOT/dist/roundtable-${VERSION}.mcpb).
if ! "$ROOT/mcpb/build.sh" >/dev/null 2>&1; then
  echo "✘ ./mcpb/build.sh failed; cannot check freshness." >&2
  cp "$COMMITTED_BACKUP" "$ARTIFACT"
  [[ -n "$COMMITTED_SHA_BACKUP" ]] && cp "$COMMITTED_SHA_BACKUP" "$ARTIFACT.sha256"
  exit 1
fi

# Move the freshly-built artifact aside and restore the committed one.
mv "$ARTIFACT" "$FRESH_DIST.mcpb"
cp "$COMMITTED_BACKUP" "$ARTIFACT"
[[ -n "$COMMITTED_SHA_BACKUP" ]] && cp "$COMMITTED_SHA_BACKUP" "$ARTIFACT.sha256"

unzip -q "$FRESH_DIST.mcpb" -d "$FRESH_EXTRACT"

if diff -r --exclude=__pycache__ "$LIVE" "$FRESH_EXTRACT" >/dev/null; then
  echo "✔ dist/roundtable-${VERSION}.mcpb is up to date with roundtable/"
  exit 0
fi

echo "✘ dist/roundtable-${VERSION}.mcpb is stale." >&2
echo "  The committed bundle does not match what mcpb/build.sh would produce now." >&2
echo "  Run: ./mcpb/build.sh && git add dist/roundtable-${VERSION}.mcpb dist/roundtable-${VERSION}.mcpb.sha256" >&2
echo >&2
echo "Differences:" >&2
diff -r --exclude=__pycache__ "$LIVE" "$FRESH_EXTRACT" >&2 || true
exit 1
