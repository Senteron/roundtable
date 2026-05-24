# Changelog

All notable changes to Roundtable will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] — 2026-05-24

### Added (orchestrator-visible)

- **`resolved_models` in `RoundOutput`.** Every successful round
  response now includes a `resolved_models: list[str]` field — the
  panel names actually dispatched to, in caller order, including
  `fake-*` fixtures and `unknown_model` sentinels. An orchestrator
  can compare this against the names it passed in `models` to
  confirm an override took effect without having to read its own
  outgoing tool-call JSON. Motivation: 2026-05-24 observation that
  an orchestrator running through Claude Code never actually sent
  a `models` field with its overrides, then spent three turns
  inventing a fictitious harness-bug root cause for "why the
  override was rejected" instead of inspecting its own payload.
  With `resolved_models` echoed back, the orchestrator can see
  "you got the default panel, your override never arrived" rather
  than blame imaginary marshalling bugs.

### Fixed

- **`models` field accepts JSON-encoded string of array** as a
  workaround for a Claude Code MCP-client bug observed
  2026-05-24 (claude-ai/0.1.0, protocol 2025-11-25). Despite the
  tool's inputSchema declaring `type: ["array", "null"]` on
  `models`, Claude Code shipped array parameters as JSON-encoded
  *strings* in the `tools/call` payload — e.g.
  `'["gpt-5.5", "gemini-3.1-pro-preview", "deepseek-reasoner"]'`
  arrived as a Python str, not a list. The server now detects a
  string that parses cleanly as a JSON array of strings and
  accepts it. A real array is still preferred and continues to
  work; this is a narrow compatibility shim. Other MCP clients
  (the test suite, Claude Desktop's bundled client) were
  unaffected; only the Claude Code SDK harness exhibited the
  string-serialization issue.

### Changed (orchestrator-visible)

- **`models=[]` (empty array) is now rejected as `invalid_input`.**
  Previously an empty array silently fell through to the default
  panel, indistinguishable from `models: null` or an omitted
  field. `RoundInput` now rejects empty arrays with a Pydantic
  validation error that explains the rationale: an orchestrator
  whose `models` field was stripped by the harness cannot tell
  the difference between "I sent an empty array" and "my field
  was dropped" unless the server distinguishes them. The JSON
  schema's `models.minItems: 1` declares the constraint to the
  client as well.
- **Tool description and `models` schema description** updated to
  document `resolved_models` and the empty-array rejection. One
  of the two version-bump-discipline strings per `CLAUDE.md`
  (framing prompt unchanged in this release).

## [0.3.1] — 2026-05-24

### Fixed

- **`serverInfo.version` in the MCP `initialize` response now
  reports the package version** (`__version__`) instead of the MCP
  SDK's own version string. Observed in Claude Desktop logs after
  the v0.3.0 install: the bundle correctly served the wider
  registry and the new tool description, but logs showed
  `"serverInfo":{"name":"roundtable","version":"1.27.1"}` (the SDK
  version), which made "did the new bundle load?" impossible to
  answer from the logs. Cosmetic-only — no change to the tool's
  observable behavior — but worth fixing because the version
  string is one of the few signals Claude Desktop users can check
  without opening a tool call.

## [0.3.0] — 2026-05-24

### Added

- **Wider panel registry.** The `models` override now accepts five
  additional snapshots in addition to the v0.1 defaults:
  - OpenAI: `gpt-5` (400K context), `gpt-5.1` (400K context),
    `gpt-5.5` (1.05M context; inputs over 272K cost 2× input /
    1.5× output per OpenAI's tier rule).
  - Google: `gemini-3.1-pro-preview` (1.05M context). The earlier
    `gemini-3-pro-preview` snapshot was shut down by Google on
    2026-03-09 and is not added here; `gemini-3.1-pro-preview` is
    the live successor.
  - DeepSeek: `deepseek-reasoner` (1M context). Both
    `deepseek-chat` and `deepseek-reasoner` now alias
    `deepseek-v4-flash` (non-thinking and thinking modes); the
    legacy names are scheduled for sunset 2026-07-24.

  Pricing entries for each new model are taken from the
  corresponding provider's public docs (May 2026). All new entries
  ride on the same `_PRICING` per-model lookup that the Unreleased
  refactor introduced — so an override pointed at a model whose
  price isn't yet calibrated continues to report `None` cost rather
  than be billed at the default model's rate.

### Changed (orchestrator-visible)

- **Tool description and `models` schema description** updated to
  list the wider registry. The default panel composition
  (`gpt-4o` + `gemini-2.5-pro` + `deepseek-chat`) is unchanged;
  newer snapshots are available only as overrides because the
  framing-prompt empirical validation (`docs/decisions.md §17.4`)
  was calibrated against the v0.1 lineup and a re-validation
  against the new snapshots is deferred to a later release. The
  tool description and framing prompt are the two version-bump-
  discipline strings per `CLAUDE.md`; the framing prompt is
  unchanged in this release.
- **`deepseek-chat` pricing and context window corrected** to
  reflect DeepSeek's May 2026 consolidation onto
  `deepseek-v4-flash`. Was `0.27 / 1.10 USD per 1M tokens` with a
  64K context window; now `0.14 / 0.28 USD per 1M tokens` (cache-
  miss tier) with a 1M context window. The default-panel slot for
  this provider now reports lower per-call cost and tolerates much
  longer prompts before triggering context-overflow guards.

### Refactor (no observable behavior change)

- **Per-model pricing tables in providers.** Each provider
  (`openai.py`, `google.py`, `deepseek.py`) now keys cost lookup off
  a `_PRICING: dict[str, tuple[float, float]]` table rather than
  module-global input/output constants. `_estimate_cost_usd` takes
  the model name and returns `None` when the name is absent — so a
  future override pointed at a model whose price isn't yet
  calibrated reports no cost rather than being billed at the
  default model's rate. Landed as PR #21 ahead of the registry
  widening so it could be reverted independently if a price entry
  turned out to be miscalibrated.

## [0.2.0] — 2026-05-24

### Changed (behavior; orchestrator-visible)

- **`models` override now rejects unknown names instead of silently
  routing them to FakeProvider.** A caller-supplied name that is
  not in the panel registry (`gpt-4o`, `gemini-2.5-pro`,
  `deepseek-chat`) and is not prefixed `fake-` now returns
  `error_class: "unknown_model"` for that slot, with no dispatch,
  no cost, and `answer: null`. Earlier versions treated unknown
  names as `FakeProvider(behavior="echo")`, which emitted a
  prompt-echo response indistinguishable from a real answer.
  Observed in production on 2026-05-24 when a request for
  `["gpt-5.5", "gemini-3-pro", "deepseek-chat", "deepseek-reasoner"]`
  ran only the one registry-known model (deepseek-chat) and
  silently echoed the prompt back from the other three at ~0.0001s
  each. Names with the `fake-` prefix remain the deliberate
  test-fixture pathway and continue to route to FakeProvider.

### Added

- **`ErrorClass.UNKNOWN_MODEL`** in `roundtable/schemas.py`, and
  the corresponding `unknown_model` enum value in the
  `prior_failures[].error_class` JSON schema in
  `roundtable/mcp_server.py`. Listed in the tool description so
  Claude understands the new failure mode without a docs round-trip.

### Documentation

- **README clarification** on the `models` override: the snippet
  showing `models=["gpt-5", "gemini-3-pro", "deepseek-chat"]` was
  misleading — those strings are not in the panel registry and
  resolve to `unknown_model`. Replaced with an honest description
  of which names work today and what to do about newer models.
- **`docs/decisions.md §19`** — "Live-run findings: post-deployment
  evidence." Records four observed patterns from three real
  deliberations run through the deployed v0.1.x bundle on
  2026-05-24: (A) GPT-4o is consistently the weakest seat for
  multi-round / design-reasoning deliberation; (B) DeepSeek's
  cost-per-insight ratio is anomalously strong (~15× cheaper than
  GPT/Gemini, yet repeatedly catches things the other two miss);
  (C) independent convergence on load-bearing flaws the user
  rationalized is the closest thing the architecture produces to
  a high-confidence signal; (D) three non-overlapping blind spots
  in section-5-style "what aren't you asking?" prompts is the
  modal output and not noise. Feeds into the v0.2 model-defaults
  re-validation in §17.4.
- **`docs/decisions.md §6` clarification** — the framing prompt
  is the panel-side instruction; the orchestrator's prompt is
  the other half. Live-run #2 (frontier-model comparison) showed
  premise-laundering: when the orchestrator's prompt asserts a
  claim, panel models accept and build on it. Live-run #3
  (charter review) showed the inverse — an explicit "you may
  disagree with stated principles" instruction defused the
  effect. The framing template can't fix a leading orchestrator
  prompt; the orchestrator has to write one that allows
  disagreement.
- **README cost magnitudes** tightened against actual observed
  costs from runs #1 and #3: substantive round 0 is ~$0.03-0.05
  panel + ~$0.50-2 orchestrator (was ~$0.03 + ~$0.30-1.00), and a
  brief note that output tokens dominate per-call cost so richer
  prompts inflate cost via the response size they elicit.

### Tests

- `tests/unit/test_panel_resolution.py` — replaced the test that
  asserted the silent-FakeProvider fallback with three new tests
  covering: unknown-name → `_UnknownModel` sentinel + warning;
  `fake-` prefix → FakeProvider, no warning; mixed input
  preserves order.
- `tests/unit/test_schemas.py` — `test_all_classes` now expects
  five enum values.
- `tests/integration/test_mcp_startup.py` — new end-to-end test
  confirms a request mixing `fake-a` with two unknown names
  returns a positionally-ordered response with one success and
  two `unknown_model` error stubs.

### Migration

For most callers nothing changes — the default panel and known
model names behave identically. Callers that were passing
newer-model strings (`gpt-5`, `gemini-3-pro`, etc.) and getting
prompt echoes back were already misreading those echoes as real
answers; the new error class makes the failure mode visible.

## [0.1.2] — 2026-05-24

Documentation release with one small tool-description change.
Focused on making cost behavior honest and discoverable without
adding new mechanisms.

### Added

- **README "What it costs" section** with the two-component cost
  model (panel dispatch is measured and reported in
  `total_cost_usd`; orchestrator-side Claude tokens are billed
  separately by Anthropic and typically dominate by 10-30×).
  Magnitudes calibrated against real runs from v0.1.1 deployment:
  trivial round ~$0.0001 panel + ~$0.05-0.10 orchestrator;
  substantive round ~$0.03 + ~$0.30-1.00; three-round deliberation
  ~$0.10-0.30 + ~$1-3.
- **README "What models does the panel use?" section** naming the
  default lineup (`gpt-4o`, `gemini-2.5-pro`, `deepseek-chat`)
  and acknowledging that newer models exist
  (`gpt-5`/`gpt-5.1`, `gemini-3-pro`) but aren't the default. The
  override path via `models=[...]` is fully wired; only the
  defaults are pinned.
- **[docs/decisions.md §17](docs/decisions.md)** capturing four
  cost-related decisions for the audit trail:
  17.1 — `total_cost_usd` reflects panel dispatch only (and why).
  17.2 — No dry-run cost estimator (five reasons it would mislead
  more than it helps).
  17.3 — Pricing constants are commit-time snapshots, not
  auto-updated.
  17.4 — Model defaults are validated, not latest; bumping is a
  v0.2 task requiring re-validation against the framing prompt's
  deliberation dynamics.

### Changed

- **Tool description** carries a one-line addition noting that
  `total_cost_usd` reflects panel dispatch only and that
  orchestrator-side tokens are billed separately. Per the
  "Two strings get the version-bump discipline" rule in
  CLAUDE.md, this is a load-bearing string change requiring a
  minor version bump in `pyproject.toml` + `mcpb/manifest.json` +
  `mcpb/pyproject.toml` + `roundtable/__init__.py` and a CHANGELOG
  entry. The manifest's `tools[0].description` is synced to match.
- README status line bumped from v0.1.0 to v0.1.2.

### Did not change

- No schema field changes. No new tool parameters. No framing
  prompt edits. No real provider code paths touched. v0.1.2 is
  doc-and-tool-description only on the user-facing contract.
- No `manifest_version` bump; still `0.3`.
- The bundle is freshly built for the release, but the only
  non-version-string bytes that differ from v0.1.1's bundle are
  the tool-description text in `mcp_server.py` and `manifest.json`.
  All dispatcher, schema, framing, provider, and test code paths
  inside the bundle are byte-identical to v0.1.1.

## [0.1.1] — 2026-05-24

Bugfix release responding to a real-world failure mode caught
minutes after v0.1.0 shipped: a Claude Desktop install with empty
API-key fields passed the unresolved literal placeholder strings
(e.g. `${user_config.OPENAI_API_KEY}`) into the provider SDKs as if
they were real keys. The SDKs constructed successfully, made real
HTTP calls, and got 401 Unauthorized back from every provider. The
panel returned three `api_error` stubs with no diagnostic detail,
so the orchestrator had no way to tell whether keys were stale,
missing, network was down, or providers were rate-limiting.

### Added

- **`error_detail` field on `ModelResponse`.** Short (≤200 char)
  diagnostic alongside the error class. Drawn from the exception's
  `str()` for a curated allowlist of exception classes whose
  message bodies are known not to echo input
  (`AuthenticationError`, `PermissionDeniedError`, `RateLimitError`,
  `InternalServerError`, `ServiceUnavailableError`,
  `APIConnectionError`, `APITimeoutError`, `ConnectionError`,
  `TimeoutError`, `RuntimeError`, `ValueError`); or from
  dispatcher-generated descriptions for internal failure modes
  (`timeout after Ns`, `framed prompt exceeds N token context
  window`). For exception classes NOT on the allowlist —
  notably `BadRequestError`, which some SDKs use for input-policy
  rejections and can include the triggering prompt fragment —
  `error_detail` carries only the class name, not the message
  body. This keeps the privacy claim ("error_detail never echoes
  prompt or answer content") policy-enforced rather than
  hope-based. Null on success. Schema-additive, backward
  compatible for callers that ignore the new field. Pydantic
  validator silently truncates to 200 chars rather than raising —
  a buggy callsite can't kill an entire round just because the
  message was too long.
- **`looks_like_unresolved_placeholder()` helper in
  `providers/base.py`** that detects values starting with `${` or
  `$user_config`. All three real providers
  (`OpenAIProvider`, `GoogleProvider`, `DeepSeekProvider`) call
  this in `__init__` and raise `RuntimeError` with a message
  pointing the user at the Claude Desktop install dialog. The
  existing `_resolve_panel()` fallback then routes the slot to
  FakeProvider with a warning instead of letting the placeholder
  reach the SDK.
- **README note explaining the `.env` non-feature.** Roundtable
  v0.1 does NOT read API keys from a `.env` file; only the Claude
  Desktop install dialog populates the server's environment. A
  Senteron-style `.env` directory picker is on the v0.2 roadmap.

### Changed

- **18 new tests:** 11 in `test_placeholder_keys.py` covering the
  detector, per-provider construction rejection, and
  `_resolve_panel()` fallback; 7 in `test_error_detail.py`
  covering success vs each error class, truncation to the 200-char
  cap, and newline flattening. Total suite: 110 unit +
  integration, ~9s, no network.
- **First bundle rebuild post-release.** `dist/roundtable-0.1.0.mcpb`
  removed from the working tree (still available on the v0.1.0
  GitHub release page); `dist/roundtable-0.1.1.mcpb` added.

### Did not change

- No framing-prompt edits, no tool-description edits, no schema
  field removals or renames. v0.1.1 is purely additive on the
  contract surface — orchestrators written against v0.1.0 keep
  working unchanged, and the new `error_detail` field is
  opt-in for the orchestrator to read.
- No version bump to `manifest_version`; still `0.3`.

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
