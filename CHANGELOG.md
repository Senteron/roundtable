# Changelog

All notable changes to Roundtable will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project scaffolding: repo structure, license, README, manifest,
  package metadata, contributor guidance.

## [0.1.0] — TBD

Initial release. Will include:
- One MCP tool, `roundtable_round`, for parallel dispatch to a panel of
  external models.
- Standardized round-1+ framing prompt embedding the cognitive task
  (revise your own answer informed by peers, do not synthesize).
- N-1 panel tolerance; failed models return error stubs and the round
  continues.
- Per-call, per-round, and per-run wall-clock timeouts.
- Provider clients for OpenAI, Google, DeepSeek (and optionally Anthropic).
- `.mcpb` bundle for Claude Desktop install.
- No persistence: nothing is written to disk by the tool.
