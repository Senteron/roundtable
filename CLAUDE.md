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

### Two strings get the version-bump discipline

Two load-bearing strings change the system's behavior even when the
surrounding code looks unchanged. Both require a **minor** version
bump and a CHANGELOG entry on any material change, even if the diff
looks trivial:

1. **The round-1+ framing prompt** — the text sent to each panel
   member when prior answers are included. It is the single most
   load-bearing piece of text in the system; changing it changes the
   deliberation dynamic.
2. **The tool description** in
   [mcpb/manifest.json](mcpb/manifest.json) `tools[].description`.
   This is the text Claude reads when deciding whether and how to
   invoke the tool, including the signal-density stop condition that
   replaces a vote field. It is as load-bearing as the framing
   prompt.

Both strings are part of the API contract (D5 in
[docs/review-concerns-plan.md](docs/review-concerns-plan.md)).

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

See [docs/design.md](docs/design.md) for the v0.1 contract and
implementation sequence; [docs/decisions.md](docs/decisions.md) for the
*why* behind each choice; [docs/handoff.md](docs/handoff.md) for a fresh
agent's read order.

## Working practices

These are the operating rules for any agent or human working in this
repo. They are tailored to Roundtable; many general "vibe coding"
practices (UI, auth, queues, migrations) don't apply because Roundtable
has no UI, no users-of-its-own, no persistence, and no async surface
beyond `asyncio.gather`.

### Prime directives

1. **Reproduce before you fix.** A failing test, a stack trace, a
   captured MCP request/response — never start debugging without a
   signal you can rerun. For Roundtable, "reproduce" usually means a
   pytest case against `FakeProvider`, not a live API call.
2. **Commit before risk.** Confirm a clean tree (`git status`) before
   non-trivial work. Before risky ops (manifest changes, version bumps,
   dependency upgrades, `.mcpb` rebuilds), make an explicit checkpoint
   commit so rollback is one command.
3. **Done means verified.** A summary without `pytest` output is a
   guess. State which tests ran and which were skipped.
4. **Stay in the slice.** No opportunistic refactors, renames, or
   "while I'm here" cleanup of adjacent code. [docs/design.md §8](docs/design.md)
   defines one commit per step; resist bundling unrelated changes.
5. **Never `--force` push to `main`.** Never `--no-verify` to skip
   hooks. Never `rm -rf` as a shortcut. Use `git revert` over history
   rewrites on shared branches.

### The slice loop

For every meaningful change:

1. **Map (read-only).** Inspect callers, tests, the relevant section of
   [docs/design.md](docs/design.md) or [docs/decisions.md](docs/decisions.md).
   Don't edit until you can name the slice and the verification command.
2. **Plan.** Smallest user-visible change. Verification command chosen
   *before* editing. If bigger than ~5 files, split it.
3. **Implement with local sympathy.** Match the existing module shape
   in [roundtable/](roundtable/) and test style in [tests/](tests/).
4. **Verify.** Narrowest unit test first; widen only if shared behavior
   changed. For live-provider changes, run the gated `pytest -m live`
   marker, not the default suite.
5. **Close.** State what changed, where, how verified, what's risky.

### Stop and ask before

- Changing the **round-1+ framing prompt** text. It's the load-bearing
  string of the system ([docs/decisions.md §6](docs/decisions.md)) and
  changes are a minor version bump + CHANGELOG entry.
- Changing the **tool description** Claude reads in [mcpb/manifest.json](mcpb/manifest.json).
  Same versioning discipline as the framing prompt.
- Changing the **tool input/output schema** in `roundtable/schemas.py`
  (when it exists) — this is the public contract.
- Adding **any form of persistence** (files, SQLite, cache dirs, log
  files containing prompts or answers). The no-persistence invariant
  is load-bearing; see [docs/decisions.md §3](docs/decisions.md).
- Adding a **runtime dependency** beyond what [pyproject.toml](pyproject.toml)
  already declares. Each new dep is lockfile churn, audit surface, and
  bundle-size impact.
- Adding a **new MCP tool** beyond `roundtable_round`. [docs/design.md §2.2](docs/design.md)
  is explicit that there is no health, list, or get tool.
- Adding **retries** inside a round. N-1 tolerance is the contract;
  the next round naturally re-attempts.
- Thrashing **3+ times** on the same failure without new evidence.
  Summarize the attempts and ask.

### Fast feedback

- Prefer `pytest tests/unit/` (fast, no network, no subprocess) during
  the slice loop. Reserve `tests/integration/` for the end of a slice
  and `pytest -m live` for changes that touch a real provider.
- Use `FakeProvider` for anything that doesn't require a real model.
  Hitting real APIs from the inner dev loop wastes credits and
  introduces flakiness.
- Use `pytest -x -k <name>` to stop on first failure with a substring
  match — far faster than the full suite.

### Independent pre-commit review for major changes

**Rule.** Before the **final commit** of a major change, the implementing
agent MUST launch a **parallel, independent code review** and address
its findings (or explicitly defer them with a written rationale) before
committing. This is a precondition for "done"; skipping it is a
process violation, not a judgement call.

**What counts as a major change** (review required):

- Completing a numbered phase (P0, P1, P1.5, P2, … as enumerated in
  [docs/design.md](docs/design.md) and [docs/review-concerns-plan.md](docs/review-concerns-plan.md)).
- Any change to the **public schema** in `roundtable/schemas.py`.
- Any change to the **round-1+ framing prompt** or the **tool
  description** in [mcpb/manifest.json](mcpb/manifest.json) (the two
  load-bearing strings from D5).
- Any change to the **dispatcher contract** (success/failure semantics,
  N-1 tolerance behavior, timeout handling).
- Any change that introduces a new **runtime dependency** or a new
  **MCP tool**.
- Any PR with more than ~10 changed files or ~500 changed lines.

**What does NOT require this review:** doc-only edits, test-only
additions that don't change production code, single-file bugfixes
under ~50 lines, dependency lockfile bumps, and the routine `.mcpb`
rebuild that accompanies a code change already reviewed.

**How to run the review.** Use the `Agent` tool with
`subagent_type: general-purpose` (or the `code-reviewer` agent if one
is registered in this repo). Independence is the point — the reviewer
must be a fresh agent with no prior knowledge of this session's
reasoning, attempts, or tradeoffs. **Do not** brief it with your
conclusions; brief it with the task that was supposed to be done and
let it judge the diff against the docs.

Prompt template for the review subagent:

> Independent pre-commit review of the staged changes on branch
> `BRANCH_NAME` for Roundtable. The change is supposed to deliver
> **ONE_SENTENCE_SCOPE** per [docs/design.md](docs/design.md) and
> [docs/review-concerns-plan.md](docs/review-concerns-plan.md).
>
> Read `git diff main...HEAD` (and any uncommitted changes via
> `git status -s` + `git diff`). Then judge the diff against the
> documented contract, the invariants in [CLAUDE.md](CLAUDE.md)
> (no persistence, stateless dispatch, N-1 tolerance, network-layer
> timeouts), and the relevant decisions in [docs/decisions.md](docs/decisions.md).
>
> Report findings by severity (high / medium / low) with file:line
> citations. Specifically check for: docs/implementation mismatches,
> unreachable code paths, schema fields that the dispatcher cannot
> populate, missing end-to-end tests for new behavior, and version
> bump / `.mcpb` rebuild discipline.
>
> Do NOT propose refactors outside the change's scope. Under 800 words.

**Handling the findings.** For each high or medium finding, either
(a) fix it in the same change before committing, or (b) record an
explicit deferral in the commit body or a follow-up issue with the
rationale ("deferred to P? because …"). Low findings can be noted
without action. **Do not commit if a high-severity finding is
unaddressed and undeferred.**

This rule exists because P1 shipped with a documented-but-unimplemented
D1 contract (dispatcher always passed `failed=[]` to
`render_round_1_plus`), and an independent reviewer caught it
immediately while the implementing agent's tests had passed. A
parallel review at phase boundaries is cheap insurance against
exactly that failure mode.

### Privacy review before anything reaches GitHub

**Rule.** Before any action that puts content onto github.com — `git
push` to any branch, `gh pr create`, `gh pr edit`, `gh pr comment`,
`gh release upload`, or any equivalent — the implementing agent MUST
run a privacy review of:

1. Every file changed in commits that aren't yet on origin (`git diff
   origin/<branch>...HEAD` when the branch exists remotely, or `git
   diff main...HEAD` for a new branch).
2. Every file referenced or excerpted in the PR/release/comment body
   itself.
3. Any untracked files about to be added (`git status -s` filtered to
   `??` lines).

The review checks for:

- **Absolute filesystem paths** containing the user's home directory
  (`/Users/<name>/`, `/home/<name>/`, `C:\Users\<name>\`). Redact to
  `~/.../` or remove.
- **Names, emails, phone numbers** that aren't already public (the
  git author trailer is fine; *content* references are not).
- **Personal prompt or answer content** from the user's own
  workflows, especially anything that hints at career, healthcare,
  finances, family, employer, or relationships. The Senteron corpus
  data and any prompt excerpts from it fall under this rule by
  default.
- **Secrets**: API keys, tokens, bearer values, private URLs, OAuth
  redirect URIs, signed-URL tokens, model-provider account IDs.
  Even partial fragments — assume rotation is required if any
  fragment leaks.
- **Customer or third-party identifying data**: real user IDs, real
  email addresses in test fixtures, real org names, real document
  IDs from internal systems.
- **Off-repo absolute paths** that reveal the user's machine layout
  even when no personal content sits at them (e.g.,
  `/Users/<name>/Documents/<private-project>/`). Redact.
- **Verbatim quotes from model responses** that mention specific
  domain context. The aggregate analysis is fine; the verbatim text
  may carry personal context. Truncate to a non-revealing fragment
  if the structural finding can survive truncation.

**What does NOT require this review:** content that's already on
github.com via an earlier merged PR (it's already public), the
existing committed CLAUDE.md/README.md/LICENSE, and standard
open-source boilerplate.

**How to run the review.** Three steps, in order:

1. **List the surfaces.** `git status -s`, `git diff --stat
   origin/<branch>...HEAD` (or `main...HEAD`), and the body text of
   any PR/release/comment you're about to post.
2. **Scan with grep first.** Run targeted regex sweeps against the
   changed files for the categories above. Suggested starters
   (extend as the project evolves):

   ```bash
   grep -nE '/Users/[^/]+/|/home/[^/]+/|C:\\Users\\' <files>
   grep -niE 'tom@|yackel|tom\.|@anthropic\.com' <files>
   grep -niE 'sk-[a-z0-9]{20,}|Bearer [a-zA-Z0-9._-]{20,}' <files>
   grep -niE 'career|health|physician|client|customer|employer' <files>
   ```

   Treat grep hits as candidates, not verdicts; check context.
3. **Read with eyes on.** Grep can't catch paraphrased personal
   context or non-obvious identifying details. For any new or
   substantially-changed doc, scan the prose at a glance — not
   line-by-line, but enough to notice "wait, that example is
   from my actual work."

**Findings handling.** Any positive finding must be resolved before
the action proceeds. Options: redact the content, move the file to
a gitignored location, drop the commit, or rewrite the PR body. Do
NOT push first and "clean it up later" — push history is
public-record from the moment it hits github.com, and force-push
rewrites are visible in the API. If the finding is in already-merged
content, that's a separate incident requiring rotation and a public
acknowledgment, not a routine fix.

**Scope note.** This rule fires on *every* push, not just PRs to
`main`. A feature branch on github.com is just as public as `main`
once pushed. The "before final commit" gate of the independent-review
rule and the "before any GitHub-bound action" gate of this rule are
different moments; both apply to a typical PR flow.

This rule exists because the `docs/empirical-evidence.md` doc, when
first surfaced for review, contained absolute paths to a private
project directory, prompt-content fragments revealing the author's
career-planning context, and a "physician executive" prompt label
that hinted at personal professional context. None of these were
load-bearing for the doc's analytic value; all were caught and
redacted in a fixup commit before the PR merged. A standing rule
catches the next instance before it gets that far.

### Definition of done

Before saying "done":

- [ ] `pytest tests/unit/` passes.
- [ ] `pytest tests/integration/` passes (if the change touches the
      MCP server, dispatcher, or framing).
- [ ] If [roundtable/](roundtable/) was touched: `.mcpb` bundle
      rebuilt and `dist/roundtable-<version>.mcpb` + `.sha256` staged.
- [ ] If the framing prompt or tool description changed: minor version
      bump in *both* [pyproject.toml](pyproject.toml) and
      [mcpb/manifest.json](mcpb/manifest.json), and a CHANGELOG entry.
- [ ] If this is a major change per **Independent pre-commit review**
      above: review launched, findings addressed or deferred with
      rationale, before the final commit.
- [ ] **Privacy review** run before `git push`, `gh pr create`, or any
      other action that puts content on github.com. See
      **Privacy review before anything reaches GitHub** above.
- [ ] `git diff` reviewed for: secrets, `.env*` content, debug prints,
      scratch files, accidental formatting on unrelated files.
- [ ] No skipped tests without an explanation, no `# type: ignore`
      without a reason.

### Closing template

> **Changed.** One sentence; concrete files and functions.
> **Verified.** Commands run, what passed, what was skipped and why.
> **Risk.** Honest residual uncertainty.
> **Next step.** The single obvious follow-up, or stop.

If verification failed, report the failing command and the smallest
next diagnostic step. Don't call it done.

### Context discipline

- New unrelated task = new session. Don't stack a manifest change on
  top of a debugging session and a docs edit.
- When referencing code, point at paths and line ranges, not vibes.
- Don't load `dist/*.mcpb` (binary), `.venv/`, or generated artifacts
  into context. [.gitignore](.gitignore) blocks most of these; the
  bundle artifacts are intentionally committed but shouldn't be read.
