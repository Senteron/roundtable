# Changelog

All notable changes to Roundtable will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(none yet)

## [0.1.0] — 2026-05-24

Initial release. Roundtable v0.1 is an MCP tool that dispatches a
prompt to a panel of other LLMs in parallel and returns their raw
answers; the orchestration loop lives in Claude's conversation, not
in the tool.

### Added

- **One MCP tool, `roundtable_round`**, with a typed
  input/output contract (Pydantic v2). Round 0 sends the raw
  prompt; round 1+ uses the committed framing template (see
  below) and a structured prior-round bundle.
- **Round-1+ framing prompt** that positions peer outputs as
  parallel attempts rather than verdicts, asks each model to
  revise its own answer (not synthesize), explicitly invites
  rejection of peer suggestions, and renders an
  `UNAVAILABLE PARTICIPANTS` section for prior-round failures
  so error stubs are not treated as peer reasoning. The exact
  text is part of the version contract (CLAUDE.md "Two strings
  get the version-bump discipline") and is pinned by a golden
  snapshot test.
- **Provider clients** for OpenAI (`gpt-4o`), Google
  (`gemini-2.5-pro`), and DeepSeek (`deepseek-chat`) against
  their respective SDKs, with SDK-level retries disabled to
  honor the no-retry-in-round invariant. Per-call timeout is
  honored via each SDK's per-request timeout.
- **Default panel resolution from environment variables.**
  `_resolve_panel()` instantiates real providers for any model
  whose API key is configured; missing keys fall back to a
  placeholder `FakeProvider` with a stderr warning, so the
  server boots and runs even with no keys. Explicit overrides
  via the `models` argument always resolve unknown names to
  `FakeProvider` for test stability.
- **N-1 panel tolerance.** Failed models return per-model error
  stubs with stable `error_class` strings (`timeout`,
  `api_error`, `context_overflow`, `invalid_output`); the round
  always returns one entry per requested model.
- **Two-layer wall-clock timeouts:** per-provider call
  (configurable, default 90s, max 180s) and whole-round
  (derived). No retries within a round.
- **Pre-dispatch context-window check.** Oversize framed
  prompts produce a per-model `context_overflow` stub before
  any network call.
- **`.mcpb` bundle for Claude Desktop install.** Committed at
  `dist/roundtable-0.1.0.mcpb` (+ `.sha256` sidecar). The
  bundle launches the server via `uv run --directory
  ${__dirname} -m roundtable`; Claude Desktop's extension
  runtime provisions dependencies from
  [mcpb/pyproject.toml](mcpb/pyproject.toml).
- **No persistence.** The tool writes no prompt or answer
  content to disk during a round. This is a core invariant
  (CLAUDE.md "No persistence") and is tested.
- **Build infrastructure:** `mcpb/build.sh` auto-injects the
  load-bearing `TOOL_DESCRIPTION` constant from the Python
  source into the manifest at bundle time, eliminating drift
  between the two API-contract strings.
- **CI:** lint + unit + integration on every push and PR;
  bundle freshness gate scoped to bundle-relevant paths.
- **Documentation:** [docs/design.md](docs/design.md) for the
  v0.1 contract, [docs/decisions.md](docs/decisions.md) for the
  *why* behind each choice, [docs/empirical-evidence.md](docs/empirical-evidence.md)
  for the 72-run corpus that justifies the no-vote and no-synthesis
  invariants, [docs/handoff.md](docs/handoff.md) for fresh-agent
  orientation, [docs/review-concerns-plan.md](docs/review-concerns-plan.md)
  for the binding decisions and implementation sequence.
- **Agent discipline:** [CLAUDE.md](CLAUDE.md) "Independent
  pre-commit review for major changes" and "Privacy review
  before anything reaches GitHub" rules.

### Known limitations

- The three real provider implementations do not yet raise
  `InvalidProviderOutput` on empty or malformed responses; an
  empty real-provider response currently surfaces as a
  successful empty-text answer rather than as the
  `INVALID_OUTPUT` error class. The dispatcher path is wired
  and tested via `FakeProvider`; emission from real providers
  is a v0.2 follow-up.
- The pre-dispatch context-overflow check uses a rough
  character-per-token heuristic (`3.5 chars/token`). Real
  tokenizer-aware checks (tiktoken etc.) land in v0.2.
- No project icon (`icon.png`) yet; the manifest omits the
  `icon` field. Cosmetic only.

### Test counts

94 unit + integration tests pass in ~9 seconds with no network
calls. 3 live smoke tests are gated by the `live` pytest marker
and per-provider API key env vars; not run in CI per D8.
