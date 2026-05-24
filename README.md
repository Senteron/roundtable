# Roundtable

An MCP tool for multi-model deliberation. Claude consults a panel of other
models, then refines its own answer through iterative critique.

> **⚠️ Status: v0.1 development preview — uses placeholder providers.**
> The server is functional and the MCP contract is stable, but the
> default panel returns `FakeProvider` echo responses, not real
> OpenAI / Google / DeepSeek answers. **Real provider dispatch lands
> in v0.2 (per [docs/review-concerns-plan.md](docs/review-concerns-plan.md)
> P4).** Do not install the `.mcpb` bundle expecting working
> multi-model dispatch yet. API key fields in the manifest are marked
> optional and are not yet read by the code.

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

The first installable `.mcpb` bundle is committed to
[dist/](dist/) as of v0.1.0. To install in Claude Desktop:

1. Download `dist/roundtable-0.1.0.mcpb` from this repo.
2. Verify the checksum against `dist/roundtable-0.1.0.mcpb.sha256`
   (`shasum -a 256 -c roundtable-0.1.0.mcpb.sha256`).
3. Open Claude Desktop → Settings → Extensions → Install from file →
   select the `.mcpb`.

The bundle launches the MCP server via `uv run`; Claude Desktop's
extension runtime provisions the dependencies from
[mcpb/pyproject.toml](mcpb/pyproject.toml) automatically.

**This v0.1 bundle still uses placeholder providers per the banner
above.** Configuring API keys in the Claude Desktop install dialog
is supported (the fields are present and optional) but the keys are
not yet read by the code; the panel returns echo responses. Real
multi-model dispatch lands in v0.2 (P4).

## License

Apache 2.0. See [LICENSE](LICENSE).
