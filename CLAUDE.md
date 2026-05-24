# Claude Code project guidance — Roundtable

This file is loaded automatically by Claude Code at the start of every
session in this repo. The rules below apply to any agent or human
working on Roundtable.

## What Roundtable is

Roundtable is an MCP tool. It exposes one capability to Claude Desktop:
dispatch a prompt to a panel of other LLMs in parallel, return their raw
answers. Claude orchestrates the deliberation loop in conversation;
Roundtable does not synthesize, judge, vote, or persist.

This is deliberately a different product from Senteron. Senteron is a
CLI/web tool with a full peer-review pipeline, runs persistence, and a
synthesis stage. Roundtable is the MCP-shaped subset designed for
Claude-as-orchestrator. If a feature request would push Roundtable
toward Senteron's shape (persistence, synthesis, judge, web UI), it
probably belongs in Senteron instead.

## Core invariants

### No persistence

The tool returns; the conversation ends; nothing should remain on disk.
No `runs/` directory, no SQLite events DB, no checkpoint files, no
prompt/answer text in logs. The only optional persistence is a
metadata-only telemetry log (timestamps, model names, latency, cost,
errors) — never prompt or answer content.

This invariant simplifies the privacy story dramatically: with no file,
there is no leak surface, and the redaction machinery Senteron needs
becomes unnecessary here. Do not weaken this without an explicit
discussion of what the alternative privacy model looks like.

### Stateless dispatch

Roundtable's tool is a pure function from inputs to outputs. No session
state between calls. No memory of prior rounds inside the tool. If a
round-1+ call needs context from round 0, the caller (Claude) passes it
in the `prior_answers` bundle. The tool never reconstructs context from
its own history.

### N-1 panel tolerance

A model failure within a round returns an error stub for that model and
the round proceeds. Never block on a single provider's outage. Never
retry within a round; the next round naturally re-attempts.

### Network-layer timeouts, not subprocess isolation

Use provider SDK timeouts and `httpx.Client(timeout=...)` /
`asyncio.wait_for`. Do not spawn child processes for routine timeout
enforcement. Process isolation is reserved for cases where a dependency
genuinely cannot be trusted to respect timeouts — none should exist in
v0.1.

## ⚠️ Always rebuild the .mcpb bundle when MCP code changes

**Rule.** If a commit touches anything under `roundtable/` (the package
source), you MUST also rebuild `dist/roundtable-<version>.mcpb` and
stage it in the same commit. The bundle is a frozen copy of the
package; shipping a code change without rebuilding leaves Claude
Desktop users on the old version.

**How.**

```bash
./mcpb/build.sh                                  # produces dist/roundtable-<version>.mcpb
shasum -a 256 dist/roundtable-<version>.mcpb > dist/roundtable-<version>.mcpb.sha256
git add dist/roundtable-<version>.mcpb dist/roundtable-<version>.mcpb.sha256
```

(Build script not yet present — will be added in v0.1.)

**When to bump the version** (`mcpb/manifest.json` AND `pyproject.toml`,
kept in sync):

- **Patch (0.X.Y → 0.X.Y+1)** — bug fix, no behavior change visible to
  the MCP client.
- **Minor (0.X.0 → 0.X+1.0)** — new tool, new parameter, new env var,
  any user-visible behavior change, any change to the framing prompt
  text sent to panel models.
- **Major (0.X → 1.0+)** — breaking change to the tool's contract.

### The framing prompt counts as user-visible behavior

Roundtable's standardized round-1+ framing prompt — the text sent to
each panel member when prior answers are included — is the single most
load-bearing piece of text in the system. Changing it changes the
deliberation dynamic. Any modification to that text is a **minor**
version bump and a CHANGELOG entry, even if the code change looks
trivial.

## Other persistent rules

- **Never commit `.env` or any file matching `*.env`** other than
  `*.env.example`. The `.gitignore` covers this; check before pushing.
- **Bearer tokens never go in URL query strings**
  (`?token=…`, `?api_key=…`, `?key=…`). Only `Authorization: Bearer …`
  or provider-SDK-managed auth.
- **No persistence creep.** If a feature seems to require writing
  something to disk, stop and ask whether the feature belongs in
  Roundtable or in Senteron.
- **Tool description is part of the API.** The text Claude reads when
  deciding whether and how to invoke the tool is as important as the
  function signature. Treat changes to it with the same care as schema
  changes.

## Layout reminders

- `roundtable/` — Python package; the MCP server and dispatcher.
- `mcpb/` — bundle manifest and build script.
- `dist/` — committed artifacts (`*.mcpb` + `.sha256`).
- `tests/` — pytest tests; assume no real network calls unless marked.
- `docs/` — design notes, framing-prompt rationale, architecture.
- `scripts/` — local debugging and operator tooling.

## Design provenance

The architecture (stateless dispatch, no synthesis, no vote, Claude as
orchestrator-participant, single tool) was derived from empirical work
on Senteron's existing pipeline. The decisions worth knowing:

- The corpus showed Senteron's existing convergence-vote field was
  performative (99.3% stop, 32% exact-phrase boilerplate). Roundtable
  has no vote.
- Live tests with Opus 4.7 as orchestrator showed it could hold a
  thesis across multiple critique rounds without regressing to mean.
  The orchestrator-quality threshold is real; Roundtable's tool
  description should assume an Opus-class orchestrator.
- The single most important design choice is the framing prompt sent
  to panel members on rounds 1+ — it must position peer outputs as
  parallel attempts (not verdicts) and explicitly instruct each model
  to revise its own answer rather than synthesize.

See `docs/design.md` (to be written) for the longer version.
