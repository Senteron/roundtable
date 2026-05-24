# Handoff notes

For a fresh agent or contributor picking up this project. Read this
first; it's a map, not the work.

## Read order

1. [README.md](../README.md) — what this is for, in 30 seconds.
2. [CLAUDE.md](../CLAUDE.md) — operational invariants (no persistence,
   stateless dispatch, version discipline, framing-prompt-as-API).
3. [docs/design.md](./design.md) — what v0.1 looks like, the contract,
   the implementation sequence in §8.
4. [docs/decisions.md](./decisions.md) — the *why* behind each design
   choice. Long but high signal; read at least §3, §6, §7, §15.

## Current state

- Scaffold committed (`f9e5c5c`): README, LICENSE (Apache 2.0),
  pyproject.toml, mcpb/manifest.json, CLAUDE.md, CHANGELOG.md,
  `.gitignore`, empty `roundtable/__init__.py`.
- **No tool implementation yet.** The manifest declares
  `roundtable_round` but `roundtable/mcp_server.py` does not exist.
  A code review correctly flagged this; `docs/design.md` §8 lays out
  the implementation sequence to fix it.
- Five known defects from the code review, all addressed in
  `docs/design.md`:
  1. Missing `roundtable/mcp_server.py` (planned: design.md §8 Step 2)
  2. Brittle `python -m` launcher (planned: design.md §5.1, use
     `uv run` per Senteron's pattern)
  3. Undefined tool contract (planned: design.md §2 specifies it)
  4. Missing `mcpb/build.sh` (planned: design.md §5.3, mirror Senteron)
  5. No tests (planned: design.md §6 specifies the test suite)

## What to build first

[docs/design.md §8 Step 1](./design.md): schemas + framing + dispatcher
+ FakeProvider + all unit tests. One commit. This is the thin vertical
slice that makes the core abstraction testable before any real provider
is wired up. After that commit, every subsequent step builds on a
tested foundation.

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
