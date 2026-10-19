# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A CLI AI agent built with the Anthropic Python SDK (manual agentic loop, no Tool Runner), using
`pypokeclient` as its data source for PokeAPI. This is a learning project in agent engineering
fundamentals — every piece is deliberately hand-built rather than scaffolded, so prefer extending
existing patterns over introducing new abstractions (e.g. don't reach for the SDK's Tool Runner).

Package manager is `uv`; dependencies are declared in `pyproject.toml` and locked in `uv.lock`.

For the full system design — layers, the service pattern, conversation-state invariants, the
turn-based execution model, known gaps — see [ARCHITECTURE.md](ARCHITECTURE.md). This file does
not duplicate it; keep architecture changes there, not here.

## Commands

- Run the CLI: `uv run pokedex`
- Install/sync dependencies: `uv sync`
- Run tests: `uv run pytest` (run a single test: `uv run pytest path/to/test_file.py::test_name`)
- Lint: `uv run ruff check .`
- Type-check: `uv run mypy .`

There is currently no automated test suite — `pytest` is a declared dev dependency but no test
files exist yet.

## Working in this repo

- **Never invoke the real Anthropic API** (anything that ends up calling
  `client.messages.create(...)` — directly, via a one-off script, or by running `agent/loop.py`
  end-to-end) **without the user's explicit, specific consent for that exact run.** This costs
  real money and hits a live external service. Ask first, every time — approval for one run does
  not carry over to the next. This is also enforced by a hook (see `.claude/settings.json`); if
  the hook blocks something you believe the user already approved, ask again rather than
  bypassing it.
