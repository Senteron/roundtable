# Changelog

All notable changes to Roundtable will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial project scaffolding: repo structure, license, README, manifest,
  package metadata, contributor guidance.
- Pre-implementation decision record: [docs/review-concerns-plan.md](docs/review-concerns-plan.md)
  with binding decisions D1–D9 and the P0–P5 implementation sequence.
- Empirical evidence audit trail: [docs/empirical-evidence.md](docs/empirical-evidence.md).
- Working practices for agents: [CLAUDE.md](CLAUDE.md) "Independent
  pre-commit review for major changes" and "Privacy review before
  anything reaches GitHub" rules.
- Schemas, framing, dispatcher, FakeProvider, MCP server, manifest
  entry-point alignment — P0 through P2 plus P1.5 (D1 contract closure)
  per the plan.
- P3 truth-in-packaging: README v0.1 preview banner, manifest API keys
  marked optional with "not yet wired" labels.
- P3.5 schema validator: `RoundInput` rejects bundles where
  `prior_answers` and `prior_failures` carry mixed round numbers.
  User-visible behavior change — previously such bundles would have
  been accepted and produced a confused framing prompt; now they
  return a structured `invalid_input` payload at the MCP boundary.
- P5 packaging: `mcpb/build.sh` (auto-injects `TOOL_DESCRIPTION`
  from Python source into the manifest), `mcpb/pyproject.toml` for
  bundle runtime deps, `scripts/check_mcpb_freshness.sh` for the
  rebuild-discipline check. First installable bundle at
  `dist/roundtable-0.1.0.mcpb` (+ `.sha256` sidecar).
- P5 manifest format: `manifest_version` bumped from `0.2` to `0.3`,
  launcher switched to `uv run --directory ${__dirname} -m
  roundtable`, `${user_config.*}` substitution wired so configured
  API keys reach the server process (the keys still aren't read by
  v0.1 code — see P4), and a `compatibility` block declaring
  Claude Desktop >=0.10.0, Python >=3.11 <4, all major platforms.
  These format changes would normally trigger a minor version bump,
  but the bundle was never previously installable so there's no
  prior version to bump from.
- P5 CI: `.github/workflows/tests.yml` (lint + unit + integration on
  every push and PR) and `mcpb-up-to-date.yml` (bundle freshness
  diff + sidecar checksum verification, scoped to bundle-relevant
  paths so unrelated PRs don't pay the install-node tax).
- P5 sync tests: `test_version_sync.py` (pyproject ↔ manifest ↔
  `__version__`) and `test_tool_description_sync.py` (Python
  TOOL_DESCRIPTION ↔ manifest tools[0].description). The build
  script's auto-injection makes the second test mostly redundant
  for fresh builds, but it catches drift in the committed manifest
  before push.
- P5 manifest-launch integration test: launches the server via the
  manifest's actual `command` + `args` (with `${__dirname}` resolved
  to the repo root), not via `sys.executable -m roundtable`. This
  catches the class of defect that the existing `test_mcp_startup.py`
  bypasses by design.
- 66 unit + integration tests, no network, ~5s.

### Known limitations (v0.1 preview)

- **Default panel returns placeholder echoes, not real model responses.**
  `_resolve_panel()` returns `FakeProvider` instances; real OpenAI,
  Google, and DeepSeek clients land in v0.2 (P4 per the plan). The
  manifest's API key fields are now marked optional and labeled "not
  yet wired" so the install UI doesn't promise capability the code
  doesn't yet have.
- **No `.mcpb` bundle yet.** Build script lands in P5 atomically with
  the manifest's `manifest_version` bump, `uv`-shaped launcher, and
  `${user_config.*}` substitution. Until then, the package runs from
  source via `python -m roundtable`.
- **No CI yet.** Tests pass locally; GitHub Actions workflows land
  with P5.

## [0.1.0] — TBD

Initial release. Will include:

- One MCP tool, `roundtable_round`, for parallel dispatch to a panel of
  external models.
- Standardized round-1+ framing prompt embedding the cognitive task
  (revise your own answer informed by peers, do not synthesize).
- N-1 panel tolerance; failed models return error stubs and the round
  continues.
- Two-layer wall-clock timeouts: per-provider call (configurable,
  default 90s, max 180s) and whole-round (derived from per-call).
- Provider clients for OpenAI, Google, DeepSeek (and optionally Anthropic).
- `.mcpb` bundle for Claude Desktop install.
- No persistence: nothing is written to disk by the tool.
