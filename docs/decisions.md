# Roundtable design decisions and provenance

This document is the *why* behind the *what*. `design.md` describes what
v0.1 is. This describes the decisions that produced that shape — the
evidence behind them, the alternatives that were considered and rejected,
and the things a future contributor or future-me needs to know to avoid
re-litigating questions that have already been settled with real data.

Read this before changing any of the design invariants. Read this before
proposing a v0.2 feature. If you find yourself disagreeing with something
here, the disagreement is fine but check whether it's overturning a
choice made with empirical evidence.

---

## 1. What Roundtable is replacing

Roundtable replaces a manual workflow. The flow:

> "I send a prompt to Claude and the same prompt to ChatGPT. Then I take
> Claude's answer to ChatGPT and vice versa and say, consider this
> alternative view; improve yours. And I may do this with other LLMs
> too, depending on the question. Often I'll pick one that will write
> things up and send it to the others saying, 'critique this and give
> me your prioritized suggestions to improve it,' then I pass that back
> to the original LLM; it creates v2, and I repeat until there's good
> agreement."

The user (Tom) has done this hundreds of times, across diverse domains,
with consistent results. Roundtable is the automation of *that* loop,
done by Claude in conversation with the user, not a generic "multi-model
consultation API."

This framing matters because it tells you what success looks like:
**Claude's next answer is meaningfully different — and better — because
it saw what the panel produced.** Not "a synthesis report was generated."
Not "the panel achieved consensus." Claude updated.

If a feature would help the synthesis report look polished but doesn't
help Claude update, it's the wrong feature. If a feature would help
Claude update but doesn't produce a report, ship it.

---

## 2. The pivot from Senteron to Roundtable

Senteron (the sibling project) is a CLI/web/MCP tool with a full
peer-review pipeline: optimize → dispatch → peer review → absorption →
head-to-head → synthesis → provenance. That shape made sense when
Senteron was a CLI tool where a human ran it from a terminal and came
back later to read the synthesis. The human had no orchestrator.

When Claude is the orchestrator, the pipeline does *double work*:

- The optimize stage rewrites the prompt per-model. Claude can do this.
- The peer-review stage scores each model. Claude can read four
  answers and form a view. The scoring adds nothing.
- The synthesis stage merges the best answers. Claude is going to fold
  the panel's input into its next message regardless.
- The provenance stage takes ~30% of total wall time in the corpus
  data and produces a report that Claude doesn't need.

Worse, the synthesis stage **destroyed the thing that made the manual
workflow valuable**: when Claude reads a smoothed-over synthesis, it
doesn't get confronted by another model's actual answer. The manual
workflow worked because Claude saw raw, unhedged peer answers and had
to update against them. The synthesis stage averages those away.

So Roundtable strips back to the one thing only the tool can do that
Claude cannot: **call other models in parallel and bring back their
raw answers.** Everything else is Claude's job.

**This is not a refactor of Senteron.** It is a different product
serving a different use case. Senteron stays whole and continues to
serve its own users (CLI / web / archival).

---

## 3. Why no persistence

This was the most consequential design decision in the project and it
deserves to be defended explicitly because the easy default is "save
the run, you might want it later."

The realization that drove this: when the consumer is Claude in a
conversation, the run has no further consumer after Claude reads it.
The user never opens the file. There is no `list_runs` UI they browse.
Each run's value is fully extracted at the moment Claude integrates
it into its next reply. The file on disk is *garbage that did its job
and is now pure exposure surface*.

That exposure surface is real:

1. Backups (Time Machine, iCloud) sync the runs directory off-machine.
2. A coding assistant pointed at the repo can read it.
3. A coworker borrowing the laptop can grep through it.
4. Six months later, a forgotten `.gitignore` line publishes it.

For Senteron-the-CLI, the file is the artifact and the user wants it.
For Roundtable, the file is collateral. Removing the file removes the
exposure without removing any value.

**The whole privacy redactor / privacy mode apparatus that Senteron
needs becomes unnecessary here, because there is nothing to redact.**
This is a feature, not a corner cut. If a v0.2 contributor proposes
adding persistence, they need to also propose the privacy model that
comes with it — see Senteron's `core/privacy.py` for the scope of
what that implies.

The one acceptable kind of persistence is **metadata-only telemetry**
(timestamps, model names, latency, cost, error counts — no prompt
content, no answer content). This is v0.2+ and even then requires
opt-in.

---

## 4. Symmetric panel design

A round 1+ call sends *every* panel member every other panel member's
prior answer (including the panel member's own prior answer, and
including Claude's own draft). All peers see all peers.

Considered and rejected: asymmetric design where only Claude sees the
panel's answers. The asymmetric version turns the panel into Claude's
advisors. The symmetric version makes Claude a peer in the panel.

Symmetric was chosen because:

1. **It mirrors the manual workflow.** Tom takes Claude's answer to
   ChatGPT and ChatGPT's answer to Claude. Both sides update.
2. **It lets the panel converge too, not just Claude.** In the
   asymmetric version, the panel's round-0 answers never improve. In
   the symmetric version, GPT in round 2 has seen what Gemini said,
   and produces a v2 informed by Gemini. This is closer to what
   actually happens when humans do this loop.
3. **It avoids putting Claude in a privileged epistemic position.**
   The whole point of the deliberation is to test Claude's reasoning;
   making Claude the meta-judge bakes in the assumption the test was
   supposed to surface.

Implementation: see `framing.py`. Round 1+ prompts include the full
bundle to every panel member. Claude's own answer is in the bundle but
Claude doesn't get dispatched-to (the tool doesn't call Claude; Claude
is calling the tool).

---

## 5. Memory via prompt reconstruction, not sessions

A round 1+ call to a panel model sends the full bundle of prior
answers as part of the prompt text. The panel model has no memory of
its own prior round; it is "remembering" via what's in the bundle.

Considered and rejected: maintaining real multi-turn sessions per
(run, model) pair using each provider's session APIs (OpenAI
Assistants, Anthropic conversations, Gemini chat). That approach has
better fidelity (the model continues its own reasoning rather than
re-engaging from a transcript) but:

1. Requires Roundtable to maintain session state, which violates the
   stateless-dispatcher invariant.
2. Cross-provider session semantics differ; the abstraction layer
   becomes a maintenance burden.
3. Empirically (in the manual workflow Tom has run hundreds of times)
   prompt-reconstruction works fine. The fidelity loss is mostly
   theoretical.

If a v0.2 contributor wants to revisit this: the right test is to run
the same prompt through both modes on a complex multi-round task and
compare round-3 quality. Until that evidence exists, don't add
sessions.

---

## 6. The framing prompt is the load-bearing string

The single most important text in the system is the round 1+ framing
prompt sent to panel members (the template in `framing.py`). Empirical
evidence from two live tests and the Senteron corpus says this is
where the design's quality lives or dies.

**Things the framing prompt must do:**

- Position peer outputs as **parallel attempts**, not verdicts. The
  exact phrase that worked in live tests was "consider these
  alternative perspectives and update your response." Anything that
  reads as "the panel says you're wrong, defend or update" produces
  defensiveness; anything that reads as "the panel agrees on X, you
  should too" produces regression.
- Ask each model to **revise its own answer**, not produce a
  synthesis. The instruction "Do NOT produce a synthesis or summary
  of the panel" is in the template for empirical reasons; models
  default to summarizing without it.
- Explicitly invite **rejection** of peer suggestions, not just
  integration. In the technical-architecture live test, Opus
  organically produced a "what I would integrate / what I would
  reject" structure. That posture is what produces refinement rather
  than averaging. The template's "Reject what is wrong, naming what
  specifically you reject and why" line is there to encode this.
- Tell each model to **defend distinctive choices when others would
  smooth them away**. This is the anti-regression-to-mean instruction.
  Without it, the loop will averages-out characterful work, especially
  in creative domains.

**Things the framing prompt must NOT do:**

- Ask for a binary stop/continue vote with a sentinel string. The
  Senteron corpus showed 99.3% stop with 32% exact-phrase boilerplate
  ("No material changes expected.") when the prompt had this pattern.
  Models obey the format and the format becomes performative.
- Ask the model to score the other panelists. Scoring produces
  competition framing rather than peer framing.
- Include Roundtable-side framing on round 0. Round 0 sends the raw
  user prompt only. Adding "you are participating in a deliberation"
  framing on round 0 distorts the initial answer with
  consensus-seeking pressure before the panel has produced anything
  to consense about.

**The framing prompt is part of the version contract.** Changes to it
require a minor version bump and a CHANGELOG entry. See `CLAUDE.md`.

---

## 7. The orchestrator-quality threshold

Live testing showed that **Opus 4.7 reliably does things Sonnet
probably does not.** Specifically, Opus:

- Held a contrarian-correct position (recommending ClickHouse over
  ELK at the described scale) across three rounds of panel pressure
  in the technical-architecture test.
- Defended a distinctive creative draft (the voicemail flash fiction)
  against more conventional peer versions, refining the spike rather
  than smoothing it.
- Caught factual errors in peer outputs and named them (a compression
  ratio claim that contradicted the same document's later math).
- Recognized when iteration had become additive without producing
  substantive updates and called out the meta-pattern explicitly:
  "Four rounds in, the pattern is worth naming before I edit: each
  review round is additive, and the document is now closer to the
  failure mode several of these critiques themselves warn against."

These are not generic "good model" behaviors. They are specific to a
model that holds positions and reasons across rounds. Smaller / older /
more-RLHF-tuned-to-agreeableness models often don't do this.

**Roundtable's tool description should assume Opus-class orchestration.**
This means:

- No hard round cap. Opus's "name the pattern and consolidate" move
  prevented runaway iteration in the test; a hard cap of 2 or 3 would
  have cut it off before the most valuable move.
- The stop condition is **signal density**, not round count.
  "Iteration produced no substantive update or substantive rejection"
  is the right exit. This is encoded in the tool description that
  Claude reads.
- The "name meta-patterns when iteration becomes counterproductive"
  capability is a first-class instruction in the tool description,
  not an emergent behavior we hope for.

For weaker orchestrators (Haiku, Sonnet, smaller models), the tool
will still work but with degraded outcomes. We accept this trade
because making the tool work well with Opus is much more valuable
than making it work mediocrely with everything.

---

## 8. The default panel composition

GPT-4o, Gemini 2.5 Pro, DeepSeek V3.

**Why these three specifically:**

- **GPT-4o** is the strongest "mainstream LLM consensus" voice.
  Including it gives Claude visibility into what the conventional
  answer looks like, which is useful even when the conventional
  answer is wrong (because then Claude can articulate why).
- **Gemini 2.5 Pro** has a different training distribution from the
  OpenAI lineage. Empirically in the live tests it produced more
  structured/analytical output and was the second-most-thorough
  reasoner. Gemini also has a habit of *explaining its own work*
  after producing it — useful for transparency, occasionally
  redundant.
- **DeepSeek V3** has a non-Western training distribution. In the
  technical-architecture test it caught a factual error that GPT and
  Gemini both missed. Tom's manual-workflow observation:
  "deepseek won the rounds" surprisingly often. Worth keeping in
  the default panel for non-redundancy alone.

**Models considered and not included by default:**

- **Anthropic models.** Claude is the orchestrator; including Claude
  in the panel introduces self-reference dynamics worth thinking
  about before defaulting on. Possible via `models=["claude"]`
  override.
- **Grok** (xAI). Less reliable API in the corpus data. Possible
  override.
- **Mistral.** Slow. In the Senteron corpus it was the *only* model
  that ever asked for another head-to-head round, which is
  interesting (suggests less RLHF compliance) and worth experimenting
  with in v0.2 as an "honest skeptic" panelist for cases where you
  want more pushback. Not default in v0.1.
- **Cheap models** (groq, together, cohere). Added little signal in
  the corpus data; mostly redundant with GPT/Gemini. Not default.

---

## 9. The 60-180s latency reality

This is the budget the design has to live within, not a constraint we
can engineer around.

From Senteron corpus data (n=63 real peer_review runs):

| Stage | Median wall time | p90 | Max |
|---|---|---|---|
| Dispatch (parallel, 3 models) | 61s | 182s | 709s |
| Peer review | 67s | 175s | 292s |
| Head-to-head (1 round) | 40s | 98s | 326s |

A single Roundtable round is the dispatch row: **60-180s for 3 models
in parallel.** That's the floor. A 3-round loop is 3-6 minutes of
wall time, p90 closer to 10 minutes.

This rules out a UX where Claude calls Roundtable and replies to the
user within seconds. The right UX is "Claude tells the user 'let me
consult the panel, this'll take a few minutes' and the user goes and
does something else."

Engineering implications:

- Per-call timeout default of 90s, max 180s. Anything lower will fail
  on the long-tail providers.
- Per-round timeout (round-wide cap) of ~200s, max ~360s for the
  pathological case.
- No need for streaming responses in v0.1. The bottleneck is the
  slowest panelist, not how fast we can render tokens.
- The tool description must tell Claude this is a slow tool, so
  Claude reaches for it deliberately and warns the user.

---

## 10. The creative-vs-convergent task question

The voicemail flash-fiction test was constructed to confirm a
hypothesis: **the multi-model loop regresses creative work to the
mean.** The result was more nuanced than expected.

**Strong form of the hypothesis (refuted):** "Creative loops regress
to the mean, full stop." Opus 4.7 with the right framing defended a
distinctive creative thesis across two rounds of pasted peer outputs.
The spike survived.

**Weaker form (supported):** Creative loops regress to the mean *when
specific conditions hold*:

- The orchestrator doesn't have a clear thesis to defend, OR
- The framing presents peer outputs as authoritative critiques rather
  than parallel attempts, OR
- The orchestrating model is more strongly RLHF-tuned toward
  agreeableness (Sonnet < Opus, GPT-4o < o-series, etc.), OR
- Convergence pressure is baked into the pipeline (vote-to-stop
  fields, synthesis stages, "merge these" framing — Senteron had all
  three).

Three of four conditions are about *framing and orchestration*, not
about the task. Roundtable's design (good framing, no synthesis, no
vote, assumes Opus-class orchestrator) addresses three of them.

**Important nuance from the voicemail test:** the regression isn't to
the *human mean* of competent creative writing. It's to the *LLM mean*,
which is a specifically degraded subset (over-explanatory,
under-trusting of the reader, prone to add analysis sections after
the piece). LLMs are RLHF'd toward helpfulness, completeness, and
explicitness. The multi-model loop amplifies exactly that pressure
because each peer enforces the same prior on every other peer.

**Tool description implication:** the guardrail "don't use this for
creative work" is too strong and not in the tool. Instead, the tool
description should say *what kinds of tasks the tool helps with*
(pressure-testing reasoning, finding things you missed, integrating
strong critiques) and leave the orchestrator to judge fit.

---

## 11. Per-model behavioral observations

From the corpus data and live tests, not exhaustive but useful for
panel composition decisions:

- **GPT-4o** tends toward conventional, pleasant, mid-of-the-road
  answers. Adds little to questions where the right answer is
  contrarian. Adds a lot to questions where you want a sanity check
  against drifting too far from mainstream practice.
- **Gemini 2.5 Pro** tends to be the most structured / analytical and
  the most likely to append meta-commentary about its own work. Often
  more thorough than necessary; sometimes that thoroughness catches
  things others missed.
- **DeepSeek V3** caught a compression-ratio factual error that GPT
  and Gemini both missed in the architecture test. Tom's manual-loop
  observation was that DeepSeek "won the rounds" surprisingly often.
  Worth treating as a high-signal panelist.
- **Mistral** is the only model in the Senteron corpus that ever
  voted for another head-to-head round (1 of 12 votes, 8%). Every
  other model voted stop 100% of the time. Suggests less RLHF
  compliance; potentially useful as a designated skeptic panelist.
- **Claude Sonnet 4.5** produced a distinctive (spiky) flash-fiction
  draft in parallel testing but we don't have data on whether Sonnet
  *holds* spiky positions across rounds the way Opus does. Assume
  not, pending evidence.
- **Cheap models** (groq, together, cohere): in the corpus data,
  scored similarly to each other and were largely redundant with the
  bigger models. Verbose but not differently-informative.

---

## 12. The MCP server is convenience, not service

A meta-point that drove the no-persistence decision but is worth
stating directly because it sounds obvious and gets violated quickly:

**Roundtable is a function Claude invokes, not a service with its own
identity.**

Compare to other MCP servers:

- *Gmail-style* MCP servers wrap an existing service with its own
  users, lifecycle, and reasons to persist data. Gmail-the-product
  exists outside any Claude session. The MCP server is a thin client
  over a fat service.
- *Roundtable-style* MCP servers expose a computation. There is no
  "Roundtable-the-product" that exists outside the Claude session
  invoking it. No other users. No archive Claude is one client of.

When a feature would only make sense if Roundtable had its own
identity ("let's show users their history," "let's let teams share
runs," "let's add an admin dashboard"), check whether you've drifted
into thinking of it as a service. If yes, the feature probably
belongs in Senteron, not Roundtable.

---

## 13. Tests we ran that produced this design

Three pieces of empirical evidence shaped this project. They're worth
knowing about because if they're contradicted by future evidence, the
design should update.

**13.1 The Senteron corpus analysis.** 67 real peer_review runs over
14 weeks, plus 5 fresh comparison runs added 2026-05-23/24 (72 total,
146 model votes). Key findings:

- 71 of 72 runs ended after 1 head-to-head round.
- 99.3% of vote events were "stop" (145 of 146).
- 32% of `continuation_reason` strings were the exact phrase "No
  material changes expected."
- The boilerplate phrase appeared as a *prefix* even on substantive
  reasons, suggesting the prompt was forcing it.
- One model (Mistral) was the only one that ever voted continue
  (8.3% of its own votes; 0% for every other model).
- 22663s (6+ hour) runaway in the provenance stage in one run; no
  timeout enforcement caught it.
- 10% per-call error rate from `MODEL_ERROR` events; justifies
  N-1 panel tolerance directly.

This is the evidence behind: no vote field, no synthesis stage, no
hard round cap, no provenance stage, network-layer timeouts only,
N-1 panel tolerance.

**Full receipts** — run IDs, verbatim boilerplate-vote citations,
per-model vote and cost tables, per-stage latency percentiles — are
in [empirical-evidence.md](./empirical-evidence.md). Read that doc
before re-litigating a settled design question.

**13.2 The voicemail flash-fiction test.** Same prompt sent to GPT-4o,
Claude Sonnet 4.5, and Gemini 2.5 Pro in parallel. Then a separate
Opus 4.7 session ran the consultation loop with those drafts as input.

Findings:

- GPT-4o produced a competent but mid-of-the-road version with
  emotional labels announced rather than enacted.
- Gemini produced a competent version *plus* a 400-word analysis
  section explaining its own choices (the over-explanation tendency).
- Sonnet produced a distinctive (spiky) version with structural risk:
  withholding, mid-sentence breaks, a one-word closing voicemail.
- Opus, given all three plus the original prompt, refined toward the
  spiky Sonnet shape rather than averaging toward GPT/Gemini.
- Opus explicitly named the basil-version's "discipline of objects"
  as the strongest move and adopted it, while preserving its own
  distinct engine (caller-as-perpetrator).
- In a second round of critique, Opus pushed back on the user's own
  revision when the revision had added explicit emotional labels the
  original had withheld.

This is the evidence behind: framing-positioning peer outputs as
parallel attempts (not verdicts), "defend distinctive choices" in the
framing prompt, assume Opus-class orchestrator.

**13.3 The log architecture test.** A real architecture question
(ELK vs ClickHouse vs Parquet+hot-tier at modest scale) routed through
a fresh Opus session that called the panel and ran the loop. Four
rounds of critique.

Findings:

- Opus v1: ClickHouse-centered with S3 tiering. Contrarian-correct
  (mainstream answer would have been ELK).
- Round 1 panel: 3 of 4 agreed with v1; one dissented toward Loki.
- Opus held the position, integrated metrics-derived alerting from
  one panelist's framing, caught a factual error in another panelist's
  compression-ratio claim, and added VictoriaLogs as a co-prototype.
- Round 2 critiques caught a real partitioning bug (PARTITION BY
  (toDate(ts), service) over 50 services = ~50 partitions/day).
  Opus fixed it.
- Round 3 critiques started becoming additive without surfacing new
  signal. Opus explicitly named this: "Four rounds in, the pattern
  is worth naming before I edit: each review round is additive, and
  the document is now closer to the failure mode several of these
  critiques themselves warn against — too much for a small team to
  execute."
- Opus then *consolidated* rather than expanding, adopting two more
  specific fixes (dedup/idempotency for replay, loss model explicit)
  and explicitly rejecting over-engineering proposals (continuous
  classifier sidecar, latency-vs-frustration plotting protocol).

This is the evidence behind: no hard round cap, signal-density stop
condition, the "name the meta-pattern when iteration becomes
counterproductive" instruction in the tool description, the explicit
"defend / integrate / reject" structure in the framing prompt.

---

## 14. What we're explicitly not testing in v0.1

Things that would be good to test but are not blocking ship:

- **Sonnet as orchestrator.** Live tests used Opus. We don't have
  evidence on what happens with Sonnet. Suspect: worse, but workable
  with sharper framing in the tool description. Worth testing in
  v0.2.
- **Adversarial-skeptic panel composition.** Including Mistral
  specifically as an honest-skeptic panelist might produce more
  continue-votes / more pushback when warranted. Worth experimenting
  in v0.2.
- **The critique-mode variant.** Some tasks (creative drafts, written
  proposals) seem to benefit more from "critique this draft" than
  "produce your own version." The current tool does the latter
  exclusively. v0.2 may add `mode: "consult" | "critique"` if the
  difference proves to matter in practice.
- **Per-question-type panel composition.** A factual question might
  want different panelists than a design question. Tom's manual
  workflow already does this informally. Tool doesn't yet.

---

## 15. Things to never do

Putting these in writing because they're easy to violate by accident:

- **Never add a synthesis stage to the tool.** The whole point of
  Roundtable is that Claude does the synthesis in the conversation,
  in its own voice, with the conversation's context. A
  tool-side synthesis throws all that away and produces a generic
  merge.
- **Never add a vote field.** The Senteron corpus shows this becomes
  performative. The orchestrator's judgment is the right stop signal.
- **Never persist prompt or answer content to disk.** Metadata-only
  telemetry is OK if explicitly opt-in. Content is not.
- **Never lower the prompt to fit a model's context window.**
  Truncate, fail loudly, or split into rounds. Silent truncation has
  produced subtle bugs in similar systems.
- **Never let Roundtable's tool description claim it's faster than
  it is.** 60-180s per round is the floor; saying anything that
  implies "quick" misleads the orchestrator into using it for
  inappropriate questions.
- **Never let a "while I'm here" refactor of the framing prompt land
  without a version bump.** The framing prompt is part of the API.

---

## 16. For a fresh agent picking up the work

The fastest path to productive work:

1. Read `README.md` for context (what this is for).
2. Read `CLAUDE.md` for the operational rules (no persistence,
   stateless dispatch, version-bump discipline, framing-prompt-as-API).
3. Read `docs/design.md` for what v0.1 looks like and the
   implementation sequence (§8).
4. Read this file (`docs/decisions.md`) for the *why* behind each
   choice, especially §3 (no persistence), §6 (framing prompt), §7
   (orchestrator quality), and §15 (things never to do).
5. Look at Senteron's `mcpb/build.sh`, `mcpb/manifest.json`,
   `scripts/check_mcpb_freshness.sh`, and
   `.github/workflows/mcpb-up-to-date.yml` for the build patterns to
   mirror.
6. Start with `docs/design.md` §8 Step 1 (schemas, framing,
   FakeProvider, dispatcher). Everything else builds on that.

If something here turns out to be wrong, **update this file in the
same commit as the code that contradicts it.** Don't leave stale
design rationale to mislead future contributors.
