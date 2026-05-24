# Handoff notes

For a fresh agent or contributor picking up this project. Read this
first; it's a map, not the work.

## Read order

1. [README.md](../README.md) — what this is for, in 30 seconds.
2. [CLAUDE.md](../CLAUDE.md) — operational invariants (no persistence,
   stateless dispatch, version discipline, framing-prompt-as-API) and
   working practices for any agent in this repo.
3. [docs/review-concerns-plan.md](./review-concerns-plan.md) — the
   authoritative pre-implementation plan. Decisions D1–D9 are binding;
   P0–P5 supersedes design.md §8 on sequencing. **Read this before
   touching code.**
4. [docs/design.md](./design.md) — what v0.1 looks like, the contract,
   and rationale. §8's step list is preserved for historical context
   but defer to the plan in (3) above for sequencing.
5. [docs/decisions.md](./decisions.md) — the *why* behind each design
   choice. Long but high signal; read at least §3, §6, §7, §15.
6. [docs/empirical-evidence.md](./empirical-evidence.md) — the
   receipts. Only read this if you're about to re-litigate a settled
   design question (vote-to-continue, persistence, synthesis stage,
   timeout defaults, panel composition) or if a reviewer asks where
   a specific number came from.

## Current state

- **P0 through P2 plus P1.5 have shipped.** The testable core is in
  place: schemas, framing, dispatcher, FakeProvider, MCP server,
  manifest entry-point alignment, D1 contract closure. 53 unit and
  integration tests pass against `FakeProvider` in roughly 5 seconds
  with no network calls.
- **The default panel still returns placeholder responses.** P4 (real
  OpenAI / Google / DeepSeek clients) has not landed. The manifest's
  API key fields are now marked optional and labeled "not yet wired"
  per P3. A user installing the bundle today gets working MCP
  protocol with fake echo answers, not real multi-model dispatch.
- **No `.mcpb` bundle yet.** Build script lands in P5 atomically with
  the manifest's `manifest_version` bump, `uv`-shaped launcher, and
  `${user_config.*}` substitution. Until then the package runs from
  source via `python -m roundtable`.
- **No CI yet.** Tests pass locally; GitHub Actions workflows land
  with P5.

Original code-review defects, with current status:

1. Missing `roundtable/mcp_server.py` → **done** in P2.
2. Brittle `python -m` launcher → entry-point fix done in P2; full
   `uv`-shaped launcher → P5.
3. Undefined tool contract → **done** (D1–D4 propagated into
   design.md by P0).
4. Missing `mcpb/build.sh` → P5.
5. No tests → unit tests **done** in P1, integration tests **done**
   in P2. CI workflows still in P5.

## What to build next

[docs/review-concerns-plan.md](./review-concerns-plan.md) carries the
official P0–P5 order. Following the May 2026 re-review the live
sequence is:

- **P3 — Truth in packaging** (this PR or the one before yours):
  disclosure-only edits to README, manifest user_config, CHANGELOG,
  and this handoff. **Status: in progress / just shipped.**
- **P3.5 — Schema semantic validation:** add a `model_validator` on
  `RoundInput` requiring that `prior_answers` and `prior_failures`
  share a single round number. Closes a contract gap the tool
  description currently promises but the schema doesn't enforce.
  Small surface, no architectural risk.
- **P5 — Build, bundle, version sync, CI:** `mcpb/build.sh` and
  `mcpb/pyproject.toml`, manifest to v0.3 with `uv` launcher and
  `${user_config.*}` substitution, first committed `.mcpb` artifact,
  test that pyproject / manifest / `__version__` agree, test that
  `TOOL_DESCRIPTION` matches the manifest, integration test that
  launches the server via the manifest's actual command rather than
  bypassing it, and CI freshness gate. `build.sh` injects
  `TOOL_DESCRIPTION` from the Python source into the manifest at
  bundle time so the two cannot drift.
- **P4 — Real providers (largest block):** OpenAI / Google /
  DeepSeek clients, `INVALID_OUTPUT` error class actually emitted on
  malformed provider output, default-panel resolution from env vars
  with a clear stderr warning when keys are missing. After P4 lands,
  remove the v0.1 preview banner from README.

The P5-before-P4 ordering is deliberate: real providers need to ship
through a manifest that actually substitutes API keys into the
server environment.

## What to never break

From [docs/decisions.md §15](./decisions.md):

- Never add a synthesis stage to the tool.
- Never add a vote field.
- Never persist prompt or answer content to disk.
- Never silently truncate prompts to fit context windows.
- Never let "while I'm here" refactors of the framing prompt land
  without a minor version bump.

## Where the design came from

[docs/decisions.md §13](./decisions.md) documents three pieces of
empirical evidence that produced this shape: a 72-run Senteron
corpus analysis (67 historical + 5 fresh verification runs), a
voicemail flash-fiction test, and a log architecture test.
[docs/empirical-evidence.md](./empirical-evidence.md) holds the
receipts (run IDs, verbatim quotes, percentile tables). If you find
yourself disagreeing with a design choice, check §13 first — there
may be evidence behind it that predates the current question.

## Where the patterns came from

Many infrastructure choices (build script shape, manifest format,
bundle freshness CI, version sync) mirror the sibling project
[**Senteron**](https://github.com/Senteron/senteron). When in doubt
about how to do something operational, look there first.

## Things explicitly deferred to v0.2+

- Streaming responses
- File-based telemetry (metadata-only, opt-in)
- A `roundtable_critique` mode variant
- Anthropic models in the default panel
- Per-question-type panel composition
- Sonnet-as-orchestrator testing

See [docs/decisions.md §14](./decisions.md) for fuller list.

## Outside-the-repo evidence

The design conversation that produced this project is preserved in a
Claude.ai chat transcript (not checked in). If you need to reconstruct
the *why* behind a choice that isn't documented here, that transcript
is the source. But the goal of `decisions.md` is to make the
transcript unnecessary — if you find a gap, fix `decisions.md` rather
than fetching the transcript.
