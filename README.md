# Roundtable

An MCP tool for multi-model deliberation. Claude consults a panel of other
models, then refines its own answer through iterative critique.

**Status:** v0.1.2. Real OpenAI / Google / DeepSeek dispatch when
the corresponding API key is configured; transparent fallback to a
placeholder `FakeProvider` (with a clear stderr warning) for any
provider whose key is missing, so the server boots and runs even
with no keys configured.

## What it does

Roundtable exposes one tool to Claude Desktop (or any MCP client): given a
prompt, dispatch it to a panel of other LLMs in parallel and return their
raw answers. Claude can then optionally call the tool again with a bundle
of everyone's prior answers — including its own — to get a revised round
of responses.

The orchestration loop lives in Claude's conversation, not in Roundtable.
There is no synthesis stage, no judge, no convergence vote, and no
persistence. Roundtable is a stateless dispatcher; Claude is the
participating orchestrator.

## Why it exists

The manual workflow this replaces: ask Claude something, ask GPT or Gemini
the same thing, take the differences back to Claude, let Claude revise its
answer in light of the others, repeat until convergence. Done by hand it
works well. Roundtable lets Claude run the loop itself without you
shuffling text between browser tabs.

## How it differs from Senteron

[Senteron](https://github.com/Senteron/senteron) is a CLI/web tool that
runs a full peer-review pipeline with synthesis. Roundtable is the
MCP-shaped subset: parallel dispatch only, no synthesis, no persistence,
designed for Claude as the orchestrating consumer rather than a human at
a terminal.

## Installation

The current installable `.mcpb` bundle is committed to
[dist/](dist/). To install in Claude Desktop:

1. Download `dist/roundtable-0.1.2.mcpb` from this repo (or grab it
   from the [v0.1.2 release page](https://github.com/Senteron/roundtable/releases/tag/v0.1.2)).
2. Verify the checksum against `dist/roundtable-0.1.2.mcpb.sha256`
   (`shasum -a 256 -c roundtable-0.1.2.mcpb.sha256`).
3. Open Claude Desktop → Settings → Extensions → Install from file →
   select the `.mcpb`.

The bundle launches the MCP server via `uv run`; Claude Desktop's
extension runtime provisions the dependencies from
[mcpb/pyproject.toml](mcpb/pyproject.toml) automatically.

Configure API keys in the Claude Desktop install dialog to enable
real dispatch. Any key field left blank turns that provider into a
FakeProvider stub for the panel — the server logs a warning but
continues to run, which keeps the install dialog optional and lets
you bring up the bundle with whichever subset of providers you have
keys for.

> **Note on `.env` files:** Unlike its sibling [Senteron](https://github.com/Senteron/senteron),
> Roundtable v0.1 does **not** read API keys from a `.env` file in
> your home directory or in a configured directory picker. The
> bundle launches with a sanitized environment supplied by Claude
> Desktop; only values you type into the Roundtable install dialog
> reach the server. Putting your keys in a project `.env` (even a
> Roundtable repo `.env`) will not work — the server never sees
> them. A `.env` file picker like Senteron's is on the v0.2
> roadmap.

If real dispatch fails with an obviously-wrong error message like
`api_error: AuthenticationError` or `OPENAI_API_KEY looks like an
unresolved manifest placeholder`, the most common cause is an empty
or stale field in the Claude Desktop install dialog. v0.1.1 detects
unresolved `${user_config.*}` literals at provider-construction
time and falls back to FakeProvider with a clear warning rather
than silently passing the placeholder through to the SDK.

## What it costs

Per round, Roundtable bills you separately for two things:

1. **Panel dispatch** — calling OpenAI, Google, and DeepSeek.
   Reported in the tool's response as `total_cost_usd`. **Measured**
   from token counts each provider's SDK returns; reflected in your
   provider invoices.
2. **Orchestrator conversation** — the Claude conversation that
   invoked Roundtable. Billed directly to your Anthropic account;
   **not reported** in Roundtable's response. Roundtable is an MCP
   tool; it has no visibility into Claude's token usage on the other
   side of the protocol.

Approximate magnitudes from real runs (May 2026, current public
pricing; verify against your invoice):

| Round shape | Panel (measured) | Orchestrator (est.) |
| --- | --- | --- |
| Trivial round 0 ("Reply OK") | ~$0.0001 | ~$0.05–0.10 |
| Substantive round 0 (see note) | ~$0.03 | ~$0.30–1.00 |
| 3-round deliberation, same scale | ~$0.10–0.30 | ~$1–3 |

*Substantive round 0 = ~3 KB prompt, ~4 KB total panel output.*

**The orchestrator dominates total cost, typically by 10–30×.**
This is a property of how MCP and conversational LLMs work: Claude
re-reads the panel's responses every time it produces output, so
bundle size compounds against orchestrator-side tokens far more
than against panel-side tokens.

To keep costs down:

- **Stop on signal density, not round count.** 1–2 rounds is fine
  for simple questions; the corpus data suggests 3–4 rounds only
  earns its keep on genuinely complex deliberations.
- **Keep prompts and answers concise.** Verbose panelists (Gemini
  is ~2.4× more verbose than GPT at the median; see
  [empirical-evidence.md §6.3](docs/empirical-evidence.md)) inflate
  orchestrator cost more than panel cost.
- **The model you use as orchestrator dominates.** Opus produces
  the highest-quality deliberation but at Opus pricing. Sonnet is
  cheaper but is untested as a Roundtable orchestrator; see the
  caveat in [docs/decisions.md §7](docs/decisions.md).

Roundtable does **not** include a dry-run cost estimator (a
"how much would this round cost?" preflight call). We considered it
and chose not to ship one; the reasoning is in
[docs/decisions.md §17](docs/decisions.md).

## What models does the panel use?

The v0.1 default lineup:

| Provider | Default model | Snapshot |
| --- | --- | --- |
| OpenAI | `gpt-4o` | May 2024 (pinned) |
| Google | `gemini-2.5-pro` | March 2025 (pinned) |
| DeepSeek | `deepseek-chat` | Provider-maintained alias |

The OpenAI and Google entries are specific model snapshots; newer
versions (`gpt-5`/`gpt-5.1`, `gemini-3-pro`) exist but aren't the
default. DeepSeek's `deepseek-chat` is a provider-maintained alias
that routes to their current production chat model.

**Why not the latest?** The defaults are pinned to the lineup that
the project's empirical evidence is calibrated against — the corpus
analysis, framing-prompt tuning, per-model behavioral observations,
and cost magnitudes in this README all measure *these specific
models*. Bumping defaults without re-running that validation would
invalidate parts of the audit trail. The full reasoning is in
[docs/decisions.md §17.4](docs/decisions.md). Updating defaults is a
v0.2 task scheduled to land with side-by-side re-validation.

**To use newer models now:** override per-call via the `models`
parameter:

```python
roundtable_round(
    prompt="...",
    models=["gpt-5", "gemini-3-pro", "deepseek-chat"],
)
```

The override mechanism is fully wired and tested; only the
defaults are pinned.

## License

Apache 2.0. See [LICENSE](LICENSE).
