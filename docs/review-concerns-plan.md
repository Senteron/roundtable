# Roundtable review concerns and prioritized plan

Status: pre-implementation. This document supersedes
[docs/design.md §8](./design.md) on sequencing; design.md still owns the
v0.1 contract, framing prompt, and rationale.

This document consolidates the remaining concerns from the second review
pass, takes binding positions on each, and sequences the work as P0–P5.
The goal is to enter implementation with a stable contract and no
re-litigated decisions.

## Decisions

Binding for v0.1. Future work that contradicts any of these is a
contract change, not a refactor.

### D1. Failed-stub flow into later rounds

Failed responses **do not appear in `PANEL ANSWERS`** on the next round.
Instead, the round-1+ framing template includes an `UNAVAILABLE
PARTICIPANTS` section listing model name and error class when at least
one panelist failed the prior round.

Rationale: presenting an error stub as peer reasoning distorts
deliberation; silently omitting it makes the panel appear to shrink.
The named-but-empty section preserves transparency without producing
fake signal.

### D2. Orchestrator vs panelist identity

Each `prior_answers` entry carries a required `source` field with enum
`"orchestrator" | "panelist"`. No `participant_id` in v0.1 —
`(model, source)` is unique under the current constraint that the
orchestrator is always Claude and panelists are distinct models per
call. Revisit if and when Claude-as-panelist override ships.

### D3. Rename `version` → `round` in the bundle schema

`prior_answers[i].version` becomes `prior_answers[i].round`. The
existing name collided with provider/model versioning concepts. This is
the only schema rename before v0.1 ships.

### D4. Context-window overflow contract

An oversize framed prompt produces a **per-model `error: "context_overflow"`
stub** for the affected provider only. The round proceeds normally for
other panelists. Never silently truncate. Never split a single round
into multiple sub-rounds inside the dispatcher.

Implementation: each `Provider` carries a `context_window_tokens`
constant; `framing.py` exposes a `framed_size(provider, prompt,
prior_answers)` helper; the dispatcher checks before dispatch and
short-circuits to the error stub when the framed prompt exceeds the
window minus a configured response reserve. This matches the N-1
tolerance contract — overflow is just another per-model failure mode.

### D5. Version-bump discipline covers two strings

The framing-prompt version-bump rule in [CLAUDE.md](../CLAUDE.md) and
[docs/design.md §3](./design.md) extends to **two** load-bearing
strings:

- The round-1+ framing prompt sent to panel models.
- The tool description Claude reads in
  [mcpb/manifest.json](../mcpb/manifest.json).

Material changes to either require a minor version bump in both
[pyproject.toml](../pyproject.toml) and
[mcpb/manifest.json](../mcpb/manifest.json) and a CHANGELOG entry.

### D6. Timeout terminology

v0.1 has exactly two timeout layers:

- **Per-provider call** (default 90s, max 180s, configurable via the
  tool's `per_call_timeout_seconds` input).
- **Whole-round** (the MCP-call wall clock — derived, not separately
  configurable in v0.1).

The earlier CLAUDE.md language of "per-call, per-round, and per-run" is
narrowed to these two. CLAUDE.md is updated as part of P3.

### D7. No-disk-write test scope

`tests/unit/test_no_disk_writes.py` asserts that **Roundtable-owned
code** wrote nothing during a round, using `FakeProvider` so real SDKs
are out of the picture. Provider SDK cache behavior is out of scope.

A stronger real-provider privacy test — assert no *prompt or answer
content* lands on disk during a live call — is **deferred to v0.2** and
listed in [docs/decisions.md](./decisions.md) deferrals.

### D8. Live provider tests are a maintainer smoke check

`pytest -m live` is **not a release gate**. It is a maintainer-only
smoke check before tagging. The tag-time procedure is: run live tests
locally, paste results into the release PR description, tag.

Rationale: provider APIs are routinely flaky (cold-start latencies,
intermittent 5xx, regional quota limits). Gating release on a flaky
external dependency either invites forbidden retry logic or weakens the
gate silently. A documented smoke check gives the same signal without
the brittleness.

### D9. Repository URLs

`https://github.com/Senteron/roundtable` is the intended public home.
The local `origin` remote already matches.
[pyproject.toml](../pyproject.toml) and
[mcpb/manifest.json](../mcpb/manifest.json) URLs are correct as-is. No
action.

## Status table

| Concern | Decision | Blocks | Target file | Status |
| --- | --- | --- | --- | --- |
| Failed-stub flow | D1: separate `UNAVAILABLE PARTICIPANTS` section | P1 framing.py | docs/design.md §3 | Decided; pending design.md update |
| Orchestrator vs panelist | D2: required `source` enum | P1 schemas.py | docs/design.md §2.1 | Decided; pending design.md update |
| `version` → `round` rename | D3: rename in bundle entry | P1 schemas.py | docs/design.md §2.1 | Decided; pending design.md update |
| Context-window overflow | D4: per-model error stub | P1 framing.py + dispatcher.py | docs/design.md §2.1, §4 | Decided; pending design.md update |
| Tool-description versioning | D5: same rule as framing | P3 | CLAUDE.md, docs/design.md §3 | Decided; pending CLAUDE.md edit |
| Timeout terminology | D6: two layers, named | P3 | CLAUDE.md, CHANGELOG.md | Decided; pending CLAUDE.md/CHANGELOG edits |
| No-disk-write test scope | D7: Roundtable-owned writes only | P1 | docs/design.md §4.4 | Decided; pending design.md note |
| Live tests as release gate | D8: maintainer smoke check | P4 release procedure | docs/design.md §6.3, README | Decided; pending docs update |
| Repository URLs | D9: keep as-is | none | n/a | Decided; no action |
| Manifest entry-point alignment | n/a — execution detail | P2 | mcpb/manifest.json | Pending P2 |
| Changelog/version state | n/a — execution detail | P3 | CHANGELOG.md | Pending P3 |

## Prioritized plan

### P0: Apply decisions to design docs

Before any code lands, propagate D1–D8 into [docs/design.md](./design.md)
and [CLAUDE.md](../CLAUDE.md) so future agents see the contract
consistently. One commit.

1. Update [docs/design.md §2.1](./design.md) — add `source` field, rename
   `version` to `round`, add the `context_overflow` error class.
2. Update [docs/design.md §3](./design.md) — add the `UNAVAILABLE
   PARTICIPANTS` section to the framing template, with the empty-case
   omitted (the section appears only when at least one prior-round
   panelist failed).
3. Update [docs/design.md §4.2 and §4.4](./design.md) — narrow timeout
   terminology to per-call + per-round; clarify no-disk-write test
   scope.
4. Update [docs/design.md §6.3](./design.md) — note live tests are
   maintainer smoke, not release gate.
5. Update [CLAUDE.md](../CLAUDE.md) — extend version-bump rule to
   cover the tool description string (D5); narrow timeout language
   (D6).
6. Update [CHANGELOG.md](../CHANGELOG.md) — replace "per-call,
   per-round, and per-run wall-clock timeouts" with the two-layer
   language.

Deliverable: all design docs reflect D1–D8 consistently. No code
changes.

### P1: Thin vertical slice

Build the testable core without real provider SDK calls.

1. Add `schemas.py` reflecting D2 (`source`), D3 (`round`), and D4
   (`context_overflow` error class).
2. Add `framing.py` — round-1+ template, bundle formatter,
   `framed_size()` helper, `UNAVAILABLE PARTICIPANTS` rendering per D1.
3. Add `providers/base.py` (with `context_window_tokens` per D4) and
   `providers/fake.py`.
4. Add `dispatcher.py` — parallel calls, two-layer timeouts per D6,
   N-1 tolerance, pre-dispatch overflow check per D4, response
   aggregation.
5. Add unit tests: schema validation, framing (including golden
   snapshot), timeout, N-1 tolerance, ordering, cost aggregation,
   overflow producing a per-model stub, Roundtable-owned no-disk-write
   per D7.

Deliverable: `pytest tests/unit/` passes without network credentials.

### P2: MCP startup and manifest alignment

Make the declared package entry point real. **Scope-limited: this step
fixes only the `entry_point` and `args` mismatch — full manifest
bundle-readiness (manifest_version bump, `uv` switch, `compatibility`
block, env substitutions) lands in P5.**

1. Add `roundtable/mcp_server.py`.
2. Add `roundtable/__main__.py`.
3. Update [mcpb/manifest.json](../mcpb/manifest.json) — fix
   `entry_point` to `roundtable/__main__.py` and `args` to
   `["-m", "roundtable"]`. Do not touch `manifest_version`, `command`,
   `compatibility`, or `env` substitutions yet — those land in P5
   atomically with the build script and bundle artifact.
4. Add integration tests for startup (`subprocess.run([sys.executable,
   "-m", "roundtable"])`), `tools/list`, round 0, and round 1+ using
   `FakeProvider` via the `models` override.

Deliverable: the MCP server starts locally and the manifest's
`entry_point` matches reality.

### P3: Release and version discipline

Tighten release metadata before adding real providers or producing a
bundle.

1. Add a unit test asserting `pyproject.toml` version equals
   `mcpb/manifest.json` version.
2. Align [CHANGELOG.md](../CHANGELOG.md) — move feature list from
   `[Unreleased]` to `[0.1.0]` when v0.1 is actually shipped; until
   then, keep the scaffold under `[Unreleased]` and `[0.1.0]` as a
   forward-looking placeholder is acceptable.
3. Confirm CLAUDE.md and CHANGELOG language for D5 and D6 are in
   place (the P0 commit applies the doc edits; this step verifies and
   tests them).

Deliverable: release metadata carries no ambiguity into the first
bundle.

### P4: Real providers

Only after the fake-provider path is stable.

1. Add OpenAI provider (with `context_window_tokens` set per D4).
2. Add Google provider.
3. Add DeepSeek provider.
4. Add `panel.py` — default composition, provider availability
   detection from environment variables, automatic narrowing when keys
   are missing.
5. Add live tests under `tests/live/` gated by `pytest -m live` and
   the relevant API key env var. Per D8, these are maintainer smoke
   checks, not CI gates.

Deliverable: real provider calls work; ordinary tests run offline; CI
does not run `-m live`.

### P5: Build and bundle

Mirror the proven Senteron bundle pattern.

1. Add [mcpb/pyproject.toml](../mcpb/pyproject.toml) for bundle
   runtime dependencies (distinct from the repo-root
   [pyproject.toml](../pyproject.toml)'s dev dependencies).
2. Add `mcpb/build.sh`.
3. Add `scripts/check_mcpb_freshness.sh`.
4. Update [mcpb/manifest.json](../mcpb/manifest.json) for full
   bundle-readiness: bump `manifest_version` to `0.3`, switch
   `command` to `uv` with Senteron-shape args, add `compatibility`
   block, move user-config to `server.mcp_config.env`
   substitutions, make API keys optional (panel narrows
   automatically).
5. Produce `dist/roundtable-0.1.0.mcpb` and `.sha256`; commit both.
6. Add CI: `tests.yml` (push + PR, skips `-m live`),
   `mcpb-up-to-date.yml` (rebuild in clean checkout, diff against
   committed bundle, fail on drift).

Deliverable: installable v0.1.0 MCP bundle with committed checksum and
mechanical freshness enforcement.

## Definition of done for v0.1.0

Roundtable v0.1.0 is ready when:

- `roundtable_round` exists and is callable through MCP.
- Round 0 sends the raw prompt unchanged.
- Round 1+ uses the committed framing prompt, including the
  `UNAVAILABLE PARTICIPANTS` rendering per D1.
- The bundle schema uses `source` and `round` per D2 and D3.
- Failed panelists return error stubs without blocking successful
  panelists; oversize prompts produce `context_overflow` stubs per D4.
- The tool writes no prompt or answer content to disk during a
  `FakeProvider` round (D7).
- Manifest startup works in the bundle environment.
- Unit and integration tests pass without real network calls.
- Maintainer ran `pytest -m live` once before tagging and pasted the
  result into the release PR description (D8). Failure of `-m live` is
  not an automatic block but requires written justification.
- Version, changelog, manifest, and bundle artifact are aligned.
