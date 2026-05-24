# Roundtable design plan

**Status:** working design, pre-implementation.
**Target:** ship v0.1.0 with a thin, testable vertical slice and a clear
contract. Provider SDK integration deliberately deferred until the MCP
contract, timeout behavior, and N-1 tolerance are testable against fakes.

This document responds to a code review of the initial scaffold, which
flagged five concrete defects (missing server module, brittle launcher
command, undefined tool contract, missing build script, no tests). It
also captures the architectural decisions derived from the conversation
that produced this project, so future contributors and future-me have a
record of why the shape is what it is.

---

## 1. What v0.1.0 ships

A `.mcpb` bundle installable in Claude Desktop that exposes exactly one
tool, `roundtable_round`, with a typed input/output schema, real
provider clients for OpenAI, Google, and DeepSeek, network-layer
timeouts, and N-1 panel tolerance. No persistence. No synthesis stage.
No CLI, no web UI, no FastAPI.

**Out of scope for v0.1.0**, with rationale:

- **CLI.** Roundtable is an MCP tool. A debug CLI may land in v0.2; for
  v0.1 the way to invoke the dispatcher outside Claude Desktop is via
  pytest fixtures.
- **Multi-round bundle persistence.** Each round is a stateless call;
  Claude passes prior answers in `prior_answers` on every round.
- **Synthesis, judge, vote.** These belong in Senteron, not here. The
  loop's exit condition is Claude's judgment, not a tool-side
  mechanism. See §6.
- **Streaming responses.** The tool returns when all panel members
  complete or time out. Streaming is a v0.2+ concern.
- **Telemetry to disk.** A stdout-only metadata log (timestamps, model
  names, latency, cost — never content) is acceptable in v0.1 if it
  helps debugging. A file-based telemetry log is v0.2+ and needs a
  separate privacy review.
- **Anthropic as a panel member.** Possible but not the primary
  use case; Claude is the orchestrator. Skipped in v0.1 to keep the
  default panel composition clear.

---

## 2. The contract

### 2.1 Tool: `roundtable_round`

**Input schema** (validated server-side, JSON Schema in MCP terms):

```python
{
    "prompt": str,                       # required, 1..50_000 chars
    "prior_answers": list[dict] | None,  # optional; None for round 0
    "models": list[str] | None,          # optional; default panel if None
    "round": int | None,                 # optional; informational only
    "per_call_timeout_seconds": int      # optional; default 90, max 180
}
```

Each entry in `prior_answers` has shape:

```python
{
    "model": str,    # e.g. "gpt-4o", "gemini-2.5-pro", "claude"
    "version": int,  # which round produced this answer
    "answer": str    # raw text, verbatim
}
```

**Output schema:**

```python
{
    "round": int,                # echoed back; 0 if not supplied
    "responses": [
        {
            "model": str,
            "answer": str | None,            # None if errored
            "elapsed_seconds": float,
            "estimated_cost_usd": float | None,
            "error": str | None              # None on success
        }
    ],
    "errors": [                              # convenience subset
        {"model": str, "error": str}
    ],
    "total_elapsed_seconds": float,
    "total_cost_usd": float
}
```

**Semantics:**

- Round 0: `prior_answers` is `None` or absent. The raw `prompt` is
  sent to each panel member with no Roundtable-added framing.
- Round 1+: `prior_answers` is non-empty. Each panel member receives a
  standardized round-1+ framing prompt (see §3) that includes the
  original prompt, the bundle of prior answers (including the panel
  member's own), and explicit instructions to revise *its own* answer
  rather than synthesize.
- A model failure (timeout, API error, schema validation failure on
  output) returns an error stub for that model only. The round
  proceeds; `responses` always contains one entry per requested model.
- The tool never raises through to the MCP client unless input
  validation fails. A round where 3 of 3 panelists time out returns a
  valid response object with three error stubs and `total_elapsed_seconds`
  equal to the per-call timeout. Claude decides what that means.

**Tool description** (the text Claude reads when deciding whether to
invoke): the current manifest description is close but needs the
following additions before v0.1 ships:

1. Treat peer outputs as parallel attempts, not verdicts.
2. When deciding whether to run another round, watch for the iteration
   becoming additive without surfacing substantive updates or
   substantive rejections; consolidate rather than expand when that
   happens.
3. Stop on signal-density, not round count. 3–4 rounds is typical for
   complex questions; 1–2 is fine for simple ones.

These are not optional; the two live tests we ran (voicemail and log
architecture) showed Opus 4.7 doing exactly these things when prompted
to, and not reliably doing them when prompted only to "consider these
critiques."

### 2.2 Tool: nothing else

There is no `roundtable_list_runs`, no `roundtable_get_run`, no
`roundtable_health`. Roundtable is one function. If a use case
emerges that needs another tool, that is a v0.2+ scope decision and
needs justification against "should this just be in Senteron."

---

## 3. The round-1+ framing prompt

This is the single most load-bearing piece of text in the system.
Empirically (from the corpus work that preceded this project) the
existing Senteron pipeline's vote-to-continue field was performative
because the prompt asked for binary stop/continue and gave a boilerplate
prefix that models defaulted to. Roundtable replaces that with a prompt
designed to elicit substantive revision and explicit reject-or-integrate
reasoning.

**Working draft (v0.1.0 candidate):**

```
You are participating in a multi-model deliberation. Below is the
original question, followed by every participant's latest answer
(yours included).

Read all of them carefully. Then produce YOUR revised answer to the
original question. Integrate what is correct from the others. Reject
what is wrong, naming what specifically you reject and why. Defend
your distinctive choices when the others would smooth them away.

Do NOT produce a synthesis or summary of the panel. Produce your own
answer, as if you were the only respondent, but informed by what the
others have said. Keep your voice; do not adopt the panel's.

---
ORIGINAL QUESTION:
{prompt}

---
PANEL ANSWERS (round {previous_round}):

[{model_1}]
{answer_1}

[{model_2}]
{answer_2}

[{model_n}]
{answer_n}

---
This is round {current_round}.
```

Notes:

- No `CONVERGED:` / `NEEDS_ANOTHER_ROUND:` sentinel. Empirically those
  produced 99.3% performative stops in 67 real runs of Senteron's
  existing pipeline.
- "Defend your distinctive choices when the others would smooth them
  away" is the explicit anti-regression instruction. The voicemail
  test showed Opus could do this with the right framing.
- "Reject what is wrong, naming what specifically you reject" matters
  as much as "integrate what is correct." Asking only for integration
  produces averaging. The technical architecture test showed Opus
  doing this organically when the framing prompt allowed it.
- Round count is informational, not a cap. The cap (if any) lives in
  Claude's orchestration prompt, not in the tool.

**The framing prompt is part of the version contract.** Any change to
the text above is a minor version bump and a CHANGELOG entry, per
[CLAUDE.md](../CLAUDE.md). It is too important to be silently tuned.

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Claude Desktop  (MCP client; orchestrator)             │
└────────────────────┬────────────────────────────────────┘
                     │  stdio MCP protocol
                     ▼
┌─────────────────────────────────────────────────────────┐
│  roundtable.mcp_server                                   │
│  - registers tool: roundtable_round                      │
│  - validates input against JSON schema                   │
│  - calls dispatcher                                      │
│  - serializes response                                   │
└────────────────────┬────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────┐
│  roundtable.dispatcher                                   │
│  - composes per-model prompts (raw vs round-1+ framing)  │
│  - asyncio.gather over panel members                     │
│  - per-call timeout via asyncio.wait_for                 │
│  - per-model error capture; never raises out             │
│  - aggregates response object                            │
└──────┬──────────┬──────────┬──────────┬─────────────────┘
       ▼          ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│ openai   │ │ google   │ │ deepseek │ │ FakeProvider │
│ client   │ │ client   │ │ client   │ │ (for tests)  │
└──────────┘ └──────────┘ └──────────┘ └──────────────┘
```

**Module layout** (target after v0.1 implementation):

```
roundtable/
  __init__.py          # version export, package docstring
  mcp_server.py        # MCP entry point; "python -m roundtable.mcp_server"
  __main__.py          # forwards to mcp_server.main()
  dispatcher.py        # parallel call orchestration, timeout, N-1 tolerance
  framing.py           # round-1+ prompt template + bundle formatting
  schemas.py           # Pydantic models for tool input/output, ModelAnswer
  panel.py             # default panel composition, model→provider mapping
  providers/
    __init__.py        # Provider protocol/ABC
    base.py            # shared types: ProviderRequest, ProviderResponse
    openai_provider.py
    google_provider.py
    deepseek_provider.py
    fake.py            # in-memory provider for tests
  errors.py            # typed exceptions; never raise these out of the tool
  config.py            # env var loading, panel defaults
tests/
  unit/
    test_framing.py
    test_dispatcher.py
    test_schemas.py
    test_n_minus_one_tolerance.py
    test_no_disk_writes.py
    test_version_sync.py
  integration/
    test_mcp_startup.py        # subprocess launches the server cleanly
    test_round_zero_e2e.py     # FakeProvider, full MCP round trip
    test_round_one_plus_e2e.py # FakeProvider, with prior_answers bundle
mcpb/
  manifest.json
  pyproject.toml        # bundle's runtime deps (uv-provisioned)
  build.sh              # builds dist/roundtable-<version>.mcpb
docs/
  design.md             # this file
```

### 4.1 The `Provider` protocol

```python
class Provider(Protocol):
    name: str               # canonical model name, e.g. "gpt-4o"
    display_name: str

    async def call(
        self,
        prompt: str,
        timeout_seconds: float,
    ) -> ProviderResponse: ...
```

`ProviderResponse` is a small dataclass: `text: str`, `elapsed_seconds:
float`, `estimated_cost_usd: float | None`, `prompt_tokens: int | None`,
`completion_tokens: int | None`.

`Provider.call` is permitted to raise; the dispatcher wraps every call
in a try/except and converts exceptions into per-model error stubs.
This is the only place where exceptions cross a layer boundary.

### 4.2 Timeouts

Three layers, all enforced via `asyncio.wait_for` and provider SDK
timeout parameters where available:

- **Per-call**: default 90s, max 180s, set via `per_call_timeout_seconds`
  on the tool input.
- **Per-round**: derived from per-call; the dispatcher gathers with
  `return_exceptions=True` so a slow model doesn't block a fast one
  past its own deadline. Total round time is bounded by
  `per_call_timeout_seconds` plus small overhead.
- **No subprocess isolation.** Network-layer timeouts only. This is a
  CLAUDE.md invariant.

### 4.3 N-1 tolerance

A model that times out or errors returns an error stub for that model.
The round always returns one entry per requested model. No retries
within a round. If the model recovers, the next round will naturally
include it again.

This is tested explicitly with `FakeProvider(behavior="timeout")` and
`FakeProvider(behavior="error")` fixtures.

### 4.4 No filesystem writes

The tool never writes to disk during a call. This is testable:
`tests/unit/test_no_disk_writes.py` runs a real round (against
`FakeProvider`) inside a pyfakefs context with the cwd, tempdir, and
home all snapshotted before and after; the round must not produce any
new files.

Stdout/stderr is allowed (MCP protocol uses stdio for transport, and
debug logging goes to stderr). The invariant is files, not all I/O.

---

## 5. Manifest and build

### 5.1 Manifest fixes

The current `mcpb/manifest.json` has two defects called out by the
review and one I want to fix proactively, aligning with the Senteron
0.4.0 manifest that has been deployed and works in Claude Desktop:

1. **Bump `manifest_version` to `0.3`** to match what Claude Desktop
   currently expects (Senteron is at `0.3`; we landed on `0.2` by
   mistake).
2. **Replace `"command": "python"` with `"command": "uv"`** and use the
   Senteron-shape args: `["run", "--directory", "${__dirname}", "-m",
   "roundtable"]`. This is the only command shape Claude Desktop knows
   how to provision dependencies for via `mcpb/pyproject.toml`. The
   `python`-direct shape the review correctly flagged as brittle.
3. **Move user_config from top-level keys to `${user_config.foo}`
   substitution** inside `server.mcp_config.env`. This is how Senteron
   wires API keys to the server process; doing it any other way means
   keys reach the user's keychain UI but not the running server.
4. **Add `compatibility` block** specifying Claude Desktop version,
   platforms, and Python runtime range. Match Senteron's exactly.
5. **Make `OPENAI_API_KEY` and `GOOGLE_API_KEY` optional, not
   required.** A user with only one key configured should be able to
   install the bundle; the server reports which providers are available
   at startup and the default panel composition narrows to whatever's
   configured. Hard-requiring both blocks single-provider experimentation.

### 5.2 The `__main__` entry point

The manifest says `entry_point: roundtable/mcp_server.py` and runs `-m
roundtable.mcp_server`. Both should work, but the cleaner shape (per
Senteron) is `-m roundtable`, which requires `roundtable/__main__.py`
to exist and call `mcp_server.main()`. Doing this means:

- `python -m roundtable` works from a checkout
- `uv run -m roundtable` works from the bundle
- Importing `roundtable.mcp_server` still works for tests

Both files get created in the next commit.

### 5.3 The build script

`mcpb/build.sh` follows Senteron's pattern with the obvious adaptations
(roundtable instead of senteron, no engine + core/ split, no
`SENTERON_REPO_ROOT` equivalent). The script:

1. Stages `manifest.json`, `pyproject.toml`, and the `roundtable/`
   package tree in a tempdir
2. Strips `__pycache__`
3. Reads version from `manifest.json` via `python3 -c`
4. Runs `npx -y @anthropic-ai/mcpb pack` to produce
   `dist/roundtable-<version>.mcpb`

A `mcpb/pyproject.toml` (distinct from the repo-root `pyproject.toml`)
declares the bundle's *runtime* dependencies. The repo-root one
declares the *dev* dependencies (pytest, ruff, mypy). This is the
Senteron split and it's worth preserving.

### 5.4 Version sync test

A unit test reads both `pyproject.toml` and `mcpb/manifest.json` and
asserts the versions match. This catches a class of release bug that
has hit Senteron at least once already.

---

## 6. Testing strategy

The review correctly noted that no tests exist. The right shape, in
priority order:

### 6.1 Unit tests (fast, no network, no subprocess)

- `test_framing.py` — round-0 passes through the raw prompt unchanged;
  round-1+ produces the standardized framing prompt with the bundle
  correctly interpolated. Edge cases: empty answers in bundle, very
  long answers, special characters in model names. The framing template
  itself has a golden snapshot test that pins the exact string; any
  change requires intentional update + version bump.
- `test_dispatcher.py` — given a panel of 3 `FakeProvider`s, the
  dispatcher returns 3 responses. Order matches input. Elapsed times
  are reasonable. Total cost sums correctly.
- `test_schemas.py` — Pydantic input validation: rejects empty prompt,
  rejects oversized prompt, rejects malformed `prior_answers`, accepts
  the canonical happy path.
- `test_n_minus_one_tolerance.py` — when one of three panelists raises,
  the response still has three entries; the failed entry has
  `answer=None` and `error != None`; the others succeed.
- `test_no_disk_writes.py` — pyfakefs context; run a real round against
  `FakeProvider`; assert no new files appear in cwd, tempdir, or home.
- `test_version_sync.py` — `pyproject.toml` version equals
  `mcpb/manifest.json` version.
- `test_timeout.py` — `FakeProvider(delay_seconds=5)` with
  `per_call_timeout_seconds=1` produces an error stub for that
  provider, not a hang. The other panelists complete normally.

### 6.2 Integration tests

- `test_mcp_startup.py` — `subprocess.run(["python", "-m", "roundtable",
  "--help"])` (or whatever stdio probe is appropriate) exits 0 and
  prints something MCP-ish. This is the test that would have caught
  the "module doesn't exist" defect the review flagged.
- `test_round_zero_e2e.py` — start the MCP server, send a
  `tools/list` request, see `roundtable_round` listed; send a
  `tools/call` with a real prompt and `models=["fake-a", "fake-b"]`;
  assert the response has two entries with non-empty answers.
- `test_round_one_plus_e2e.py` — same setup with `prior_answers`
  populated; assert the prompt seen by the `FakeProvider`s contains
  the round-1+ framing text and the bundle.

### 6.3 Live tests (manual, gated by env vars)

A `pytest -m live` marker runs a single end-to-end test against real
providers. It is *not* run in CI. It exists so the maintainer can
verify a real round trip after a credential or SDK change.

### 6.4 What's not tested in v0.1

- Stress / load behavior (irrelevant for an MCP tool invoked
  conversationally)
- Cost-accuracy assertions against real provider invoices (handled by
  rough sanity checks, not exact-match)
- Memory leaks (irrelevant; each MCP call is short-lived)

---

## 7. Default panel composition

Three external models, picked from corpus data and from the live tests:

- **GPT-4o** (OpenAI) — strongest "mainstream LLM consensus" voice;
  good baseline for what the conventional answer looks like
- **Gemini 2.5 Pro** (Google) — different training distribution from
  the OpenAI lineage; tends to produce more analytical/structured
  output
- **DeepSeek V3** (DeepSeek) — non-Western training distribution;
  in the technical architecture test it caught a factual error
  (compression ratio) that GPT and Gemini both missed

Anthropic models (Claude family) are intentionally excluded from the
panel because Claude is the orchestrator. Putting Claude in the panel
is technically possible but introduces self-referential dynamics
that need a deliberate design pass before being defaulted on.

The panel can be overridden per-call via the `models` parameter. If a
user has only one provider configured, the panel narrows automatically
to what's available; if none are configured the tool returns a clear
error from input validation rather than from a provider call.

---

## 8. Implementation sequence

**Superseded by [docs/review-concerns-plan.md](./review-concerns-plan.md).**
The plan there (P0–P5) is the authoritative sequencing for v0.1, and
incorporates contract decisions (D1–D9) that post-date this section.
The original step list below remains as historical context, but read
the plan first.

Each step is one commit, reviewable independently. Steps build on each
other but don't combine unrelated changes.

### Step 1: Schemas, framing, FakeProvider, dispatcher (one commit)

- `schemas.py` (Pydantic models for input/output, ModelAnswer)
- `framing.py` (round-1+ template + bundle formatter + golden test)
- `providers/base.py` and `providers/fake.py`
- `dispatcher.py` (async dispatch with timeout + N-1 tolerance)
- All unit tests under `tests/unit/`
- All pass with `pytest tests/unit/`

This is the thin vertical slice the review recommended. After this
commit, the core abstraction is real and tested even though no real
provider is wired up.

### Step 2: MCP server + integration tests (one commit)

- `mcp_server.py` and `__main__.py`
- Integration tests under `tests/integration/`
- `pytest tests/integration/` passes (uses FakeProvider via the
  `models` override)

After this commit, the manifest's declared entry point actually exists
and starts. The review's #1 defect is resolved.

### Step 3: Real providers (one commit per provider, or one commit total
if they go quickly)

- `providers/openai_provider.py`
- `providers/google_provider.py`
- `providers/deepseek_provider.py`
- `panel.py` (default composition; provider→client wiring; available-
  provider detection from env vars)
- Live test (gated, not in CI)

### Step 4: Manifest and build (one commit)

- Update `manifest.json` per §5.1
- Add `mcpb/pyproject.toml`
- Add `mcpb/build.sh`
- Add `scripts/check_mcpb_freshness.sh` (mirrors Senteron)
- First successful build produces `dist/roundtable-0.1.0.mcpb` and
  `.sha256`; both committed

### Step 5: GitHub Actions (one commit)

- `mcpb-up-to-date.yml` — rebuild in clean checkout, diff against the
  committed bundle, fail PR on drift
- `tests.yml` — run pytest on push and PR

### Step 6: README polish + tag v0.1.0

- Update README to remove "Not yet ready for use" — replace with
  install instructions
- Tag `v0.1.0`, attach the `.mcpb` and `.sha256` to the GitHub release

Estimated wall time: 1–2 days of focused work for steps 1–4; steps 5–6
are short. None of these steps unblock further design conversations;
the design is settled enough to build.

---

## 9. What this design explicitly rejects

A handful of options were considered and rejected; recording them here
to save future-me from re-litigating:

- **Synthesis tool returning a single answer.** Belongs in Senteron.
- **Convergence-vote field in the tool output.** Empirically performative.
- **Hard round cap enforced server-side.** The orchestrator's judgment
  is the right stop signal; a cap is friction with Opus-class
  orchestrators and a band-aid for weaker ones.
- **Streaming responses.** Useful eventually; not v0.1.
- **Persistence of any kind.** The whole privacy story collapses if we
  add this. A v0.2+ telemetry log can write structured metadata only
  (no prompt/answer text) and only with explicit opt-in.
- **A web UI or FastAPI surface.** Not what Roundtable is.
- **Reasoning-content extraction (DeepSeek-R1 style).** v0.2+ if useful.
- **Per-model prompt optimization.** Empirically the synthesis-by-
  averaging dynamic this introduces costs more than it adds. Pass the
  same prompt to all panel members.

---

## 10. Open questions for v0.2+

Things known to be unresolved, not blocking v0.1:

- Whether `prior_answers` should be capped by token budget (some
  models have small context windows; a 4-round bundle of long answers
  could exceed limits). v0.1 trusts the caller to manage this.
- Whether to add a separate `roundtable_critique` mode that asks panel
  members to critique a draft rather than produce their own answer.
  The voicemail and architecture tests suggest this is sometimes more
  useful than the "everyone produces their own answer" pattern. Real
  usage will reveal which mode matters more.
- Whether to expose token-usage estimates pre-call so Claude can decide
  whether a round is worth it. The decision today is "always run it if
  the user asked"; cost gating is a v0.2+ concern.
- Whether to handle Anthropic models in the panel (Claude calling
  Claude). Has self-referential dynamics worth thinking about; not in
  v0.1.

---

## 11. Where the empirical evidence lives

The design choices in this document are not arbitrary. They derive
from:

- **The 67-real-run Senteron corpus** that showed the existing
  pipeline's convergence-vote field was 99.3% stop with 32% exact-phrase
  boilerplate. This is the evidence behind §3's rejection of vote
  sentinels.
- **The voicemail flash-fiction test** that showed Opus 4.7 can hold a
  distinctive creative thesis across two rounds of pasted peer
  critiques when the framing positions them as parallel attempts
  rather than verdicts. This is the evidence behind the §3 framing
  prompt's "defend your distinctive choices" instruction.
- **The log architecture test** that showed Opus 4.7 can integrate
  specific corrections (metrics-derived alerting, partitioning fix,
  dedup gap) across four rounds while explicitly rejecting
  over-engineering (continuous classifier sidecar) and naming the
  meta-pattern of additive review pressure becoming counterproductive.
  This is the evidence behind §4's no-hard-cap stance and the §2.1
  tool-description additions about consolidation.

The two live tests are the strongest evidence; they are documented in
the conversation transcripts that produced this project but are not
checked into the repo. If we ever want to reproduce or extend the
evidence, the test prompts and the Opus transcripts are recoverable;
the design rationale that emerged is captured here.
