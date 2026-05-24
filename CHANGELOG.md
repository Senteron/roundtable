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
- P4 provider clients: real OpenAI (`gpt-4o`), Google
  (`gemini-2.5-pro`), and DeepSeek (`deepseek-chat`) provider
  implementations against their respective SDKs, with SDK-level
  retries disabled to honor the no-retry-in-round invariant.
  21 mocked unit tests cover constructor key-check, successful
  call shape, error propagation, cost estimation, and the
  no-retry regression guard.
- P4-wiring: `_resolve_panel()` now detects API keys in the
  environment and instantiates real providers when keys are
  present. Any missing key falls back to FakeProvider with a
  warning to stderr, so the server boots and runs even with no
  keys configured. Explicit `models=["fake-..."]` always
  resolves to FakeProvider regardless of env state — preserves
  integration-test stability.
- `InvalidProviderOutput` exception class in
  `roundtable.providers.base`. Providers raise it when a
  response is reachable but malformed (e.g., empty content,
  schema mismatch); the dispatcher maps it to
  `ErrorClass.INVALID_OUTPUT`. Closes the gap where the
  `invalid_output` enum value previously had no emitter.
- Live smoke tests under `tests/live/`, gated by the `live`
  pytest marker AND by per-provider API key env vars.
  Maintainer-only check per D8; NOT run in CI; not a release
  gate.
- README banner updated to reflect real-dispatch capability.
  Install instructions now describe configuring API keys.
- Manifest API key descriptions rewritten to explain the
  per-key opt-in behavior with FakeProvider fallback.
- 94 unit + integration tests, no network, ~9s. (3 live tests
  also exist; 1 skips automatically without API keys, the other 2
  resolve based on whichever provider keys are configured.)

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
