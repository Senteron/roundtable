# Roundtable review concerns and prioritized plan

Status: pre-implementation review follow-up.

This document consolidates the remaining concerns from the second review
pass. It intentionally does not repeat the broader product rationale already
covered in `docs/design.md` and `docs/decisions.md`. The goal is to identify
what still needs to be clarified or fixed before the v0.1 implementation
sequence proceeds.

## Summary

The core design is sound: Roundtable should remain a stateless MCP dispatcher
that returns raw panel answers, with Claude acting as orchestrator. The design
docs now cover the tool contract, framing prompt, N-1 behavior, no-persistence
policy, implementation sequence, and rationale.

The remaining work is mostly contract sharpness and release hygiene:

- Decide how failed model stubs flow into later rounds.
- Distinguish orchestrator drafts from panel answers in the schema.
- Keep the manifest, entry points, launcher command, and build plan aligned.
- Apply version discipline to both provider-facing framing and Claude-facing
  tool descriptions.
- Reconcile changelog/version state before shipping.
- Keep no-disk-write tests scoped to Roundtable-owned behavior.

## Concerns

### 1. Failed model stubs in later rounds

`docs/design.md` specifies that model failures return per-model error stubs and
that each response contains one entry per requested model. It does not yet say
whether those error stubs should be included in `prior_answers` on the next
round.

This choice affects `framing.py` directly. If error stubs are included in the
panel answer bundle, later panelists may treat "GPT timed out" as deliberation
signal even though no peer reasoning exists. If error stubs are omitted without
any indication, the panel appears to shrink silently across rounds.

Recommended decision: exclude failed responses from `PANEL ANSWERS`, but include
a separate metadata section such as `UNAVAILABLE PARTICIPANTS` when appropriate.
That preserves transparency without presenting errors as peer reasoning.

### 2. Orchestrator versus panelist identity

The planned `prior_answers` schema uses a `model` field, with examples such as
`"claude"`. This works while Claude is only the orchestrator and Anthropic
models are not panel members. It becomes ambiguous if Claude-as-panelist is ever
allowed via an override.

Recommended decision: add a source/role field now, before schema compatibility
matters. For example:

```python
{
    "model": "claude",
    "source": "orchestrator",  # "orchestrator" | "panelist"
    "round": 0,
    "answer": "..."
}
```

This keeps Claude's draft distinguishable from an answer produced by a dispatched
Claude-family provider later.

### 3. Manifest entry point and launcher alignment

The current manifest references `roundtable/mcp_server.py` and runs
`python -m roundtable.mcp_server`, but those files do not exist yet. The design
plan says to add `roundtable/__main__.py` and use `-m roundtable`, likely via
`uv run` in the bundle.

This is a known planned fix, but it must land atomically with the MCP server
implementation. Step 2 should add `mcp_server.py`, `__main__.py`, and update the
manifest so the declared entry point and actual startup command match.

Checkout tests should use `sys.executable` rather than assuming a `python`
binary exists. Bundle tests should separately validate the exact manifest
command.

### 4. Version discipline for tool descriptions

`CLAUDE.md` already says the tool description is part of the API. The explicit
version-bump rule, however, focuses mostly on the round-1+ framing prompt.

The tool description is also load-bearing: it tells Claude when to call
Roundtable, how to interpret rounds, and when to stop. Changes to the tool
description should therefore receive the same discipline as provider-facing
framing changes.

Recommended rule: any material change to either the provider-facing framing
prompt or the Claude-facing tool description requires a changelog entry and the
appropriate version bump.

### 5. Changelog and version state

`pyproject.toml` and `mcpb/manifest.json` currently declare `0.1.0`, while
`CHANGELOG.md` still has `0.1.0 - TBD`. That is acceptable during scaffolding,
but it becomes confusing once implementation begins.

Recommended decision: treat `0.1.0` as the first working MCP bundle, not the
scaffold. Before release, align `CHANGELOG.md`, `pyproject.toml`,
`mcpb/manifest.json`, and the committed bundle artifact.

If pre-release versions are useful during development, use an explicit dev
version rather than implying the incomplete scaffold is the release.

### 6. Timeout terminology

The changelog promises per-call, per-round, and per-run wall-clock timeouts.
In v0.1, one MCP invocation equals one round, so per-round and per-run are the
same boundary.

Recommended decision: document that equivalence for v0.1, or narrow the promise
to per-provider call timeout plus whole-round timeout. Avoid promising a third
timeout layer unless it has distinct behavior.

### 7. No-disk-write test scope

The no-persistence invariant is central. The planned test using `FakeProvider`
is the right v0.1 check for Roundtable-owned writes.

Avoid expanding that test into a blanket "real SDKs write no files" assertion.
Provider SDKs may read credentials, touch caches, or create config files outside
Roundtable's control. A stronger real-provider privacy test should check that no
prompt or answer content is written, not that no filesystem activity occurs.

### 8. Repository metadata

The repository metadata currently points to `https://github.com/Senteron/roundtable`,
and the local `origin` remote matches that URL. If the intended public home is a
different repository, update the remote, `pyproject.toml`, and `mcpb/manifest.json`
together. If `Senteron/roundtable` is intentional, no action is needed.

## Prioritized plan

### P0: Resolve schema decisions before Step 1

Do this before implementing `schemas.py`, `framing.py`, or the dispatcher.

1. Decide and document whether failed model responses are eligible for
   `prior_answers`.
2. Add `source` or `role` to prior-answer entries.
3. Rename `prior_answers[i].version` to `round` or `source_round` to avoid
   confusion with provider/model versions.

Deliverable: updated `docs/design.md` contract, then implementation can start
against a stable schema.

### P1: Implement the thin vertical slice

Build the testable core without real provider SDK calls.

1. Add `schemas.py`.
2. Add `framing.py`, including the round-1+ prompt and bundle formatting.
3. Add provider base types and `FakeProvider`.
4. Add `dispatcher.py` with parallel calls, timeout handling, N-1 tolerance,
   and response aggregation.
5. Add unit tests for validation, framing, timeout, N-1 tolerance, ordering,
   cost aggregation, and no Roundtable-owned disk writes.

Deliverable: `pytest tests/unit/` passes without network credentials.

### P2: Add MCP startup and manifest alignment

Make the declared package entry point real.

1. Add `roundtable/mcp_server.py`.
2. Add `roundtable/__main__.py`.
3. Update `mcpb/manifest.json` to match the final command shape.
4. Add integration tests for startup, `tools/list`, round 0, and round 1+ using
   fake providers.
5. Use `sys.executable` in checkout startup tests; separately test the manifest
   command used by the bundle.

Deliverable: the MCP server starts locally and the manifest no longer points at
missing files.

### P3: Tighten release and version discipline

Do this before adding real providers or producing a bundle.

1. Extend version-bump discipline to tool description changes.
2. Align `CHANGELOG.md`, `pyproject.toml`, and `mcpb/manifest.json`.
3. Add tests for version sync. Include changelog checks if practical.
4. Clarify timeout terminology in the docs and changelog.
5. Confirm repository URLs are intentional.

Deliverable: release metadata no longer carries ambiguity into the first bundle.

### P4: Add real providers

Only after the fake-provider path is stable.

1. Add OpenAI provider.
2. Add Google provider.
3. Add DeepSeek provider.
4. Add provider availability detection from environment variables.
5. Add live tests gated by explicit env vars and pytest markers.

Deliverable: real provider calls work, but ordinary tests still run offline.

### P5: Build and bundle

Mirror the proven Senteron bundle pattern.

1. Add `mcpb/pyproject.toml` for bundle runtime dependencies.
2. Add `mcpb/build.sh`.
3. Add bundle freshness check script.
4. Produce `dist/roundtable-0.1.0.mcpb` and `.sha256`.
5. Add CI for tests and bundle freshness.

Deliverable: installable v0.1.0 MCP bundle with committed checksum.

## Definition of done for v0.1.0

Roundtable v0.1.0 is ready when:

- `roundtable_round` exists and is callable through MCP.
- Round 0 sends the raw prompt unchanged.
- Round 1+ uses the committed framing prompt.
- Failed panelists return error stubs without blocking successful panelists.
- Later-round framing handles unavailable participants deliberately.
- The tool writes no prompt or answer content to disk.
- Manifest startup works in the bundle environment.
- Unit and integration tests pass without real network calls.
- Live provider tests pass when credentials are explicitly supplied.
- Version, changelog, manifest, and bundle artifact are aligned.
