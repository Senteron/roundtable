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

- Scaffold committed (`f9e5c5c`): README, LICENSE (Apache 2.0),
  pyproject.toml, mcpb/manifest.json, CLAUDE.md, CHANGELOG.md,
  `.gitignore`, empty `roundtable/__init__.py`.
- **No tool implementation yet.** The manifest declares
  `roundtable_round` but `roundtable/mcp_server.py` does not exist.
  [docs/review-concerns-plan.md](./review-concerns-plan.md) sequences
  the fix as P0 (apply contract decisions to design docs) → P1 (build
  the testable core) → P2 (MCP startup + manifest entry-point
  alignment) → P3–P5.
- Original-review defects, all addressed in the plan:
  1. Missing `roundtable/mcp_server.py` → P2.
  2. Brittle `python -m` launcher → P5 (full manifest bundle-readiness;
     entry-point fix lands in P2).
  3. Undefined tool contract → resolved by D1–D4 in the plan,
     propagated into design.md by P0.
  4. Missing `mcpb/build.sh` → P5.
  5. No tests → P1 (unit) and P2 (integration).

## What to build first

[docs/review-concerns-plan.md P0](./review-concerns-plan.md): apply
contract decisions D1–D8 to [docs/design.md](./design.md) and
[CLAUDE.md](../CLAUDE.md) in one commit. No code yet. After P0, the
design docs and the binding decisions agree, and P1 (the thin vertical
slice — schemas, framing, FakeProvider, dispatcher, unit tests) can
land against a stable contract.

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
empirical evidence that produced this shape: the 67-run Senteron
corpus analysis, a voicemail flash-fiction test, and a log
architecture test. If you find yourself disagreeing with a design
choice, check §13 first — there may be evidence behind it that
predates the current question.

## Where the patterns came from

Many infrastructure choices (build script shape, manifest format,
bundle freshness CI, version sync) mirror the sibling project
**Senteron** at `/Users/tom/Documents/GitHub/senteron`. When in doubt
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
