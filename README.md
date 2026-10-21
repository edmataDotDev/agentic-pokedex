# Pokédex

A CLI AI agent that answers Pokémon questions by calling [PokeAPI](https://pokeapi.co/) through
[`pypokeclient`](https://pypi.org/project/pypokeclient/). Ask it about a Pokémon, its moves, its
evolution chain, or its type, and it looks the data up live instead of guessing from memory. It
can also compare Pokémon side by side, estimate battle (even team/doubles battle) outcomes, find
where a Pokémon is caught in the wild (or what's found at a given location), and explain items —
all computed by the tools themselves, not guessed by the model.

This is a **learning project in agent engineering fundamentals**: the agentic loop is hand-built
directly on the [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) (no
Tool Runner, no agent framework), so every piece — the conversation loop, tool dispatch, message
history — is implemented and understood from scratch rather than scaffolded. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the full system design and
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for known gaps and work in progress.

## Features

The agent has tools to query:

- **Pokémon** — stats, types, abilities (`get_pokemon`)
- **Forms** — alternate forms of a Pokémon (`get_pokemon_form`)
- **Moves** — move details (`get_move`)
- **Level-up movesets** — what a Pokémon learns and at what level (`get_level_up_moves`)
- **Evolution chains** — full evolution line for a species (`get_evolution_chain`)
- **Evolution triggers** — what causes a given evolution (`get_evolution_trigger`)
- **Types** — type matchups and the Pokémon/moves of a given type (`get_type`)
- **Comparisons** — stat-by-stat and type-matchup comparison across 2–6 Pokémon at once, fully
  pre-computed so the model just reads the conclusions (`compare_pokemon`)
- **Battle simulation** — Monte Carlo win-probability between two teams (1–6 Pokémon each),
  singles or real doubles, re-scoring moves live every turn (`battle_win_probability`)
- **Games** — resolves a game to its generation, region, and sibling version, e.g. identifying
  that Omega Ruby is a Generation VI remake set in Hoenn (`get_game_info`)
- **Locations** — where a Pokémon is found in the wild and at what encounter rate, and the
  reverse (which Pokémon appear at a given location), both aggregating across games or filtered
  to one (`get_pokemon_locations`, `get_location_encounters`)
- **Items** — an item's specs (category, fling, held-by-wild-Pokémon rarity, shop prices) and,
  optionally, a Pokémon's types alongside it so the model can judge held-item fit
  (`get_item`)

## Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) as the package/dependency manager
- An [Anthropic API key](https://console.anthropic.com/)

## Installation

```bash
git clone <this-repo-url>
cd pokédex
uv sync
```

## Configuration

Copy the example env file and fill in your own values:

```bash
cp .env.example .env
```

| Variable | Description |
| --- | --- |
| `ANTHROPIC_API_KEY` | Your Anthropic API key. **Never commit this file** — `.env` is gitignored. |
| `MODEL_NAME` | Claude model to use for the agent loop. |
| `MAX_TOKENS` | Max tokens per model response. |
| `MAX_TOOL_RETRY` | Max retries for a failing tool call. |
| `MAX_CONCURRENT_TOOLS` | Max tool calls executed concurrently in one turn. |

`.env` is never read into this repo's history — only `.env.example` (with placeholder values) is
tracked in git.

## Usage

```bash
uv run pokedex
```

This starts an interactive CLI session. Ask natural-language questions about Pokémon and the
agent will call the relevant tools to fetch live data before answering.

> **Note:** running the CLI calls the real Anthropic API and will incur usage costs.

## Development

```bash
uv run pytest           # run tests
uv run pytest path/to/test_file.py::test_name   # run a single test
uv run ruff check .      # lint
uv run mypy .             # type-check
```

## Project status

This project is under active development and not production-ready — see
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for the running list of known gaps (error
handling, token optimization, etc.). Contributions, issues, and suggestions are welcome.

## License

[MIT](LICENSE)
