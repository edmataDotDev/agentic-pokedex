# Pokédex — Architecture

A CLI AI agent built with the Anthropic Python SDK (manual agentic loop, no Tool Runner),
using `pypokeclient` as its data source. Built as a learning project in agent engineering
fundamentals — every piece here was deliberately designed, not scaffolded automatically.

## 1. Layers and dependency direction

**Filesystem layout** — `agent/`, `pokemon/`, `rag/`, and `cli/` are siblings, all directly under
`src/pokedex/`. None is nested inside another:

```
src/pokedex/
├── __init__.py        (main)
├── config.py           Settings
├── agent/
│   ├── loop.py          run_llm_turn, run_user_turn
│   ├── message_history.py   Message, MessageHistory
│   ├── system_prompt.py     SYSTEM_PROMPT
│   └── tools.py             TOOLS schema + dispatch (execute_tool)
├── pokemon/
│   └── service.py        PokeAPI via pypokeclient
├── rag/                   legendary-lore retrieval (see §15)
│   ├── chunking.py          Markdown → Chunk
│   ├── embedder.py          text → vector (local model)
│   ├── indexer.py           offline `pokedex-index` command
│   ├── service.py           preload_index, search_lore
│   └── exceptions.py        InvalidIndexError
└── cli/
    └── service.py         terminal I/O
```

**Import graph** — a *separate* thing from the folder layout above. An arrow here means
"imports," not "contains":

```
__init__.py (main)
   └─imports─> agent/loop.py
                  ├─imports─> agent/message_history.py
                  ├─imports─> agent/system_prompt.py
                  ├─imports─> agent/tools.py ─imports─> pokemon/service.py
                  │                          └─imports─> rag/service.py
                  ├─imports─> rag/service.py   (preload_index, called at the start of agent_loop)
                  └─imports─> cli/service.py

config.py (Settings) — imported by whichever module needs it; not part of this chain
```

`agent/tools.py` importing `pokemon/service.py` does **not** mean `pokemon/` lives inside
`agent/` — they're sibling packages; it only means `tools.py`'s code happens to `import` from
`pokemon.service`, the same way it would import any other module regardless of folder position.

Dependencies flow **one direction only**: the agent layer (`loop.py`) imports services
(`pokemon/service.py`, `cli/service.py`); services never import back from the agent layer. This
is deliberate, not incidental — `cli/service.py` importing from `loop.py` while `loop.py` also
imports from `cli/service.py` would be a circular import and simply fail to run.

`cli/` is a package (not a flat `cli.py`), mirroring `pokemon/`, specifically because the CLI is
expected to grow (richer terminal UX later) — this is a deliberate choice for a stated future
need, not speculative structure.

**Known inconsistency:** `cli/` has an explicit `__init__.py`; `agent/` and `pokemon/` currently
don't (they work as implicit namespace packages — Python 3.3+ supports this, and it's been
verified working). Not yet resolved which way to make the project consistent: add `__init__.py`
to `agent/` and `pokemon/`, or drop the one in `cli/`. Practically near-zero difference at this
project's size; the only real argument for explicit `__init__.py` everywhere is avoiding
namespace-package edge cases (silent merging across `sys.path` entries) and some tooling quirks —
neither is currently biting.

## 2. The "service" pattern

A **service** is an adapter to something outside the agent's own logic — `pokemon/service.py`
adapts PokeAPI (HTTP), `cli/service.py` adapts the terminal (stdin/stdout). Both share the
same contract: no knowledge of Claude, tool schemas, or `MessageHistory`. `pokemon/service.py`
raises a typed domain exception (`PokemonNotFoundError`) instead of leaking `httpx2`
exceptions; `cli/service.py` is expected to do the same kind of translation for terminal-specific
concerns if any arise.

Services are **not exclusive to tools** — `pokemon/service.py` happens to be wrapped by a
tool (`get_pokemon` in `agent/tools.py`), but `cli/service.py` is consumed directly by `loop.py`,
with no tool schema involved. "Service" means "environment adapter," not "tool backend."

`rag/service.py` follows the same contract: it adapts a local, on-disk search index (and the local
embedding model behind it), knows nothing about Claude or tool schemas, and raises a typed domain
exception (`InvalidIndexError`). Like `cli/service.py`, `loop.py` also calls it directly
(`preload_index()`), not only through its tool.

## 3. Configuration (`config.py`)

`Settings(BaseSettings)` — typed, validated config loaded from `.env` / environment
variables. Key choices:
- `anthropic_api_key: SecretStr` — required, masked in any accidental `repr`/log.
- `extra="forbid"` — a stray/misspelled key in `.env` fails loudly instead of being
  silently ignored.
- `get_settings()` factory function instead of a module-level `Settings()` singleton —
  construction is explicit and controllable (important for tests), not a side effect of
  importing the module.

**Known inconsistency (not yet cleaned up):** there are currently *two* model-name
fields — `model: str = "claude-sonnet-5"` (unused) and `model_name: str` (required, no
default, actually used by `agent/loop.py`). Worth consolidating into one.

**Note, not a bug:** `.env` and `.env.example` have `MODEL_NAME=claude-sonnet-5-5` — this
looked like a typo for `claude-sonnet-5` and was flagged as one, but was verified directly
against the live API (`response.model` echoed back `"claude-sonnet-5-5"` with no error) — it's
a real, callable model newer than this assistant's cached model knowledge. Intentional choice,
left as-is; swap to `claude-sonnet-5` only if that was never actually the intent.

## 4. Conversation state (`agent/message_history.py`)

- **`Message`** — one conversational turn: `role` (`Literal["user", "assistant", "system"]`)
  + `content` (`Sequence[ContentBlock]`). `content` is **never** a plain string — always a
  list of blocks, even for simple text, by deliberate choice (uniform shape everywhere).
- **`ContentBlock`** — a union of *both* request-side block types we construct ourselves
  (`TextBlockParam`, `ToolUseBlockParam`, `ToolResultBlockParam`) *and* the SDK's own
  response-side union (`anthropic.types.ContentBlock`, aliased as `ResponseContentBlock`).
  Both are needed: a `Message` can hold blocks we built (a `tool_result`) or blocks the API
  handed back verbatim (`response.content`, echoed into history unmodified).
- **Why `Sequence`, not `list`, as the parameter type** — `list` is invariant; a
  `list[SDK's narrower union]` isn't assignable to `list[our broader union]` even though
  every member of the narrower union is also a member of the broader one. `Sequence` is
  covariant (read-only), so it accepts the substitution safely.
- **`MessageHistory`** — owns the growing `list[Message]`. `add()`, `remove()`,
  `to_list()` (the only thing that leaves this module — converts to
  `list[MessageParam]`, exactly what `client.messages.create(messages=...)` expects).

**Hard invariant, enforced by discipline not by the type system:** a `Message` is one
unit. If a model response contains multiple content blocks (text + tool_use, or multiple
tool_use for parallel calls), they all go into **one** `Message`'s `content` list — never
split across several `Message` objects. This was an actual bug caught and fixed during
development (an early draft looped over text blocks adding one `Message` per block).

## 5. Static agent-facing content

- **`agent/system_prompt.py`** — `SYSTEM_PROMPT`: persona and general behavior only
  (who the agent is, how it should treat tool-retrieved vs. memorized data). Deliberately
  does **not** contain per-tool usage instructions — those belong in each tool's own
  `description`, not duplicated in prose here.
- **`agent/tools.py`** — two responsibilities:
  - `TOOLS: list[ToolParam]` — the schema array Claude sees. Currently just
    `get_pokemon(name_or_id: str)`. Reuses the SDK's own `ToolParam` type rather than a
    bare `list[dict]`.
  - `_HANDLERS` + `execute_tool(name, tool_input) -> tuple[str, bool]` — the dispatch
    bridge. Looks up the real function by name, calls it, catches the service's typed
    exception (`PokemonNotFoundError`) and converts it to `(message, is_error=True)`.
    **Never raises** — errors are always returned as data, never as exceptions, so the
    agent loop can keep running and let the model see and react to the failure.

## 6. The turn-based execution model

This is the core design. A **turn** is one meaningful exchange; resolving it may take
several round-trips with the model.

### `run_llm_turn(history: MessageHistory) -> str | None` — done, tested

One round-trip with the model:
1. Calls `client.messages.create(...)` with the model, `system`, `tools`, and
   `history.to_list()` — the **full** history every time (the API is stateless; nothing
   is remembered between calls except what you resend).
2. Appends the **entire, unmodified** `response.content` as one `Message(role="assistant")`
   — unconditionally, before checking `stop_reason`. This single line also fixed an
   earlier bug: it guarantees a `tool_use` block is in history *before* its `tool_result`
   is ever sent, which the API requires.
3. Branches on `stop_reason`:
   - `"end_turn"` → filters `response.content` for text blocks, joins them, **returns**
     that string. This filtering is *only* for the return value — it never touches what
     was already saved to `history` in step 2.
   - `"tool_use"` → runs `execute_tool` for each `tool_use` block, appends **one**
     `Message(role="user")` containing all resulting `tool_result` blocks, and falls
     through to `return None`.

Contract: `None` means "not done, call me again"; a `str` means "final answer." Verified
end-to-end against the live PokeAPI (Pikachu example: round 1 → `None` (tool call), round
2 → grounded final answer with real stats, not memorized/hallucinated data).

### `run_user_turn(history: MessageHistory) -> str | None` — stub, not implemented

Same contract shape as `run_llm_turn`, for symmetry. Intended behavior: read the user's
next input via the `cli` service, add it to `history` as a `Message(role="user", ...)`,
and return `None` if the input was invalid/empty (caller should ask again) or the text
itself once valid. Lives in `loop.py` (not `cli/service.py`) because `cli/service.py` is
meant to stay a pure, dependency-free terminal adapter — `run_user_turn` is the agent-side
consumer of that service, same relationship as `execute_tool` → `pokemon_service`.

### Not yet written

- **A function that resolves one full user turn** by calling `run_llm_turn` in a loop
  until it stops returning `None`:
  ```python
  def resolve_turn(history: MessageHistory) -> str:
      while True:
          result = run_llm_turn(history)
          if result is not None:
              return result
  ```
- **The outer session loop** — repeatedly: `run_user_turn` → `resolve_turn` → show the
  result via the `cli` service → repeat until the user exits.
- **`cli/service.py` itself** — currently empty. Needs at least a function to read user input
  and a function to display a message, with zero imports from the rest of the project.

## 7. Designed but not yet implemented

- **Tool-retry circuit breaker** — discussed and designed conceptually: track consecutive
  failures of the *same* tool call (same name **and** same arguments), keyed per tool, not
  globally. On reaching `max_tool_retry` (already a `Settings` field, default `5`), the
  harness should reject further identical attempts with a synthetic `tool_result`
  (`is_error=True`) telling the model it can't retry that exact call again — *before*
  touching the real service, not after a crash. Not yet wired into `run_llm_turn`'s
  `"tool_use"` branch.
- **Sequential, not concurrent, tool execution** — `run_llm_turn`'s `"tool_use"` branch runs
  a plain `for` loop over `tool_use_blocks`, calling `execute_tool` one at a time. The SDK
  docs recommend executing parallel tool calls concurrently (they still get returned together
  in one `tool_result` message, which `run_llm_turn` already does correctly — only the
  *execution* is sequential, not the response shape). Not a correctness bug, just slower than
  necessary once a turn ever involves multiple tool calls at once (e.g. `compare_pokemon`,
  implemented, internally runs up to 6 sequential `get_pokemon` calls instead of concurrent ones).

## 8. Testing status

- `pokemon/service.py` and `agent/tools.py::execute_tool` were validated with live
  smoke tests against the real PokeAPI (success and not-found cases) — not yet
  automated `pytest` tests, despite `pytest` already being a dev dependency.
- `run_llm_turn` was validated end-to-end with a real multi-round tool-calling
  conversation.
- No automated test suite exists yet.

## 9. Open question: reusing this architecture in future projects

The goal behind this document isn't just documenting *this* project — it's capturing design
decisions precisely enough to re-implement the same pattern in a future agent project without
re-deriving it from scratch. Most of what's above (the service pattern, the `str | None` turn
contract, `Message`/`MessageHistory`, errors-as-data, the dispatch registry) is already
domain-agnostic in how it's described — Pokémon only shows up in the concrete examples, not in
the reasoning. Still undecided: keep everything in this one file (Pokémon examples doubling as
illustration), or extract a second, domain-free `AGENT_PATTERN.md` meant to be dropped into a new
project as a starting point. Raised, not resolved, in conversation.

## 10. Battle win-probability & deterministic compare

Specs two tools named informally in PRODUCTION_READINESS.md §14. Both follow the existing
`TOOLS` + `_HANDLERS` + service-function pattern (§5). Both are now **implemented**, and both
ended up generalized beyond their original fixed-pair spec: `compare_pokemon` (§10.2) compares
N≥2 Pokémon, not exactly two; `battle_win_probability` (§10.3) simulates team battles (1–6
Pokémon per side, singles or doubles), not a fixed 1-vs-1. Neither original claim of "no new
exception class needed" survived contact with the real generalization — `compare_pokemon` needed
`InvalidComparisonInputError`, `battle_win_probability` needed `InvalidBattleInputError` — both
explained in their respective sections below.

### 10.1 Shared helper: `pokemon/matchup.py` (new file)

Both tools need dual-type effectiveness, which nothing in the codebase computes today (`get_type`
only returns one type's relations, not a pair interaction). New sibling helper module, same role
as `pokemon/evolution.py` (free functions, not registered as a tool, consumed only by other
`pokemon/` modules):

```python
def type_effectiveness(attacking_type: str, defending_types: Sequence[str]) -> float:
    """Multiplier of a hit of `attacking_type` against a (possibly dual-typed) defender."""

def best_type_matchup(attacking_types: Sequence[str], defending_types: Sequence[str]) -> float:
    """Best multiplier any of `attacking_types` achieves against `defending_types`."""
```

- `type_effectiveness` calls the existing `pokemon_service.get_type(attacking_type)` **once**
  (its `double_damage_to`/`half_damage_to`/`no_damage_to` lists are already "this type attacking
  others" — no need to call `get_type` per defending type). Multiplies across every name in
  `defending_types` that appears in one of those three buckets (2×, 0.5×, 0× respectively; 1× by
  omission) — this is how real dual-typing stacks.
- `best_type_matchup` is `max(type_effectiveness(t, defending_types) for t in attacking_types)`.
- Raises only `TypeNotFoundError` (propagated from `get_type` — no new exception).

### 10.2 `compare_pokemon` — deterministic compare tool (implemented, generalized to N≥2)

Implemented in `pokemon/comparison.py`. Purely arithmetic — no randomness, no simulation, which is
the point of calling it "deterministic" (as opposed to the battle tool below). **Deviates from the
original spec**, which was fixed at exactly two Pokémon: the real tool accepts a list of 2 to 6,
so an arbitrary roster — not just a pair — can be compared in one call, and the result is a fully
pre-computed structured summary (per-stat leaders, derived threat/weakness lists, directional type
matchups for every pair) so the model never has to reason over the raw numbers itself.

```python
def compare_pokemon(names_or_ids: Sequence[str]) -> dict:
```

1. Validates input: must be a JSON array (guards against a bare string, which is itself
   `len()`-able and would otherwise silently iterate character-by-character), with between
   `MIN_POKEMON = 2` and `MAX_POKEMON = 6` entries. Unlike the battle tool's level clamp, an
   out-of-range count is **rejected**, not silently truncated — dropping a Pokémon the user
   explicitly named would be a worse failure mode than clamping one scalar.
2. `pokemon_service.get_pokemon(n)` for each identifier, then de-duplicates by resolved `id`
   (e.g. `"pikachu"` and `"25"` are the same Pokémon) — re-checks the 2-minimum after dedup, and
   echoes a `note` field when anything was actually removed.
3. Per-stat comparison for all six stats (`hp`, `attack`, `defense`, `special-attack`,
   `special-defense`, `speed`): each Pokémon's value, its `diff_from_highest` (≤0), and a
   `highest` list (handles N-way ties naturally).
4. Base stat total (sum of the six) per Pokémon, same shape, plus a `base_stat_total_rank`
   (ties share a rank) folded into each Pokémon's summary.
5. Type matchup, using `matchup.best_type_matchup`, computed for every **ordered** pair among the
   compared Pokémon (not just one pair — matchups aren't symmetric), plus two derived lists per
   Pokémon (`super_effective_against`, `resisted_or_immune_vs`) so the model doesn't have to scan
   the full ordered-pair list itself to answer "who threatens whom."

Return shape:
```json
{
  "pokemon": [
    {"id": .., "name": .., "types": [..], "base_stat_total": .., "base_stat_total_rank": ..,
     "stats_led": [..], "super_effective_against": [..], "resisted_or_immune_vs": [..]},
    ...
  ],
  "stat_comparison": [
    {"stat": "hp", "entries": [{"name": .., "value": .., "diff_from_highest": ..}, ...], "highest": [..]},
    ...
  ],
  "base_stat_total_comparison": {
    "entries": [{"name": .., "value": .., "diff_from_highest": ..}, ...], "highest": [..]
  },
  "type_matchups": [
    {"attacker": .., "defender": .., "best_multiplier": ..}, ...
  ]
}
```

**Exceptions:** `PokemonNotFoundError` (from `get_pokemon`), `TypeNotFoundError` (from `matchup`,
via `get_type`) — both already in `execute_tool`'s `except` tuple — plus one new exception this
tool actually needed: **`InvalidComparisonInputError`** (in `pokemon/exceptions.py`, same style as
the other five), for the malformed/out-of-range-count cases above. A bare `ValueError` was
considered and rejected: `pydantic.ValidationError` and `json.JSONDecodeError` (raised internally
elsewhere in this codebase, e.g. `get_move`/`get_pokemon_form`'s `response.json()`) are themselves
`ValueError` subclasses, so catching `ValueError` in `execute_tool` would silently swallow those
too. `agent/tools.py`'s exception handling **does** need this one addition.

**Tool schema:**
```json
{
  "name": "compare_pokemon",
  "description": "Compares 2 to 6 Pokémon by name or National Pokédex number, producing a fully pre-computed summary — pure stat and typing arithmetic, with no battle simulation (ignores level, moves, abilities, and IVs/EVs). Interpretation guide: `pokemon` lists each compared Pokémon's identity plus a derived summary — `base_stat_total_rank` (1 = highest total, ties share a rank), `stats_led` (base stats where this Pokémon is tied for highest among those compared), `super_effective_against` (other compared Pokémon this one's typing hits for 2x or more), and `resisted_or_immune_vs` (other compared Pokémon this one's typing only hits for 0.5x or less, including 0x immunity). `stat_comparison` has one entry per base stat (hp, attack, defense, special-attack, special-defense, speed): every compared Pokémon's `value`, `diff_from_highest` (always <= 0; 0 for whoever leads), and a `highest` list naming whoever is tied for that stat. `base_stat_total_comparison` is the same shape, summed across all six stats. `type_matchups` is directional/asymmetric: one entry per ordered (attacker, defender) pair among the compared Pokémon, with `best_multiplier` — the best type-effectiveness multiplier the attacker's typing achieves against the defender's typing (2.0 or 4.0 = advantage, 1.0 = neutral, 0.5 or 0.25 = resisted, 0.0 = immune). If a duplicate identifier was given (e.g. the same Pokémon by name and by number), it's silently de-duplicated and a `note` field explains it.",
  "input_schema": {
    "type": "object",
    "properties": {
      "names_or_ids": {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 2,
        "maxItems": 6
      }
    },
    "required": ["names_or_ids"],
    "additionalProperties": false
  },
  "cache_control": {"type": "ephemeral"}
}
```

**Known limitation, accepted for now (not a regression — the matchup helper below has never had
caching):** at the max roster size (6), this is up to ~30–45 sequential, uncached `get_type` HTTP
calls in the worst case (one ordered pair at a time, no memoization) — same category of accepted
inefficiency as §10.4's note on the battle tool, and PRODUCTION_READINESS.md §10 already documents
"no caching layer" as an open gap project-wide.

### 10.3 `battle_win_probability` — Monte Carlo team-battle tool (implemented, generalized to teams/doubles)

Implemented in `pokemon/battle.py`. **Deviates from the original spec**, which was a fixed
1-vs-1: the real tool accepts two teams of 1–6 Pokémon each and an optional `format`
(`"singles"` — one active Pokémon per side, the default — or `"doubles"` — two active per side,
with spread moves able to hit both active opponents at once). A team of size 1 in `"singles"`
format is exactly the originally-specced 1-vs-1 battle. Module-level constants (not `Settings`
fields — these are simulation parameters, not deployment config): `SIMULATIONS = 2000`,
`MAX_TURNS = 100`, `MIN_TEAM_SIZE = 1`, `MAX_TEAM_SIZE = 6`, `SPREAD_MODIFIER = 0.75`.

```python
def battle_win_probability(
    team_1: Sequence[dict],   # [{"name_or_id": str, "level": int}, ...], 1-6 entries
    team_2: Sequence[dict],
    format: str = "singles",  # "singles" | "doubles"
    seed: int | None = None,
) -> dict:
```

(`seed` is **not** exposed in the tool's `input_schema` — the model never sets it; it exists
purely so the function is unit-testable deterministically later, since zero tests exist today.)

**0. Input validation — raises `InvalidBattleInputError`, not a bare `ValueError`** (same reason
as `InvalidComparisonInputError` in §10.2: `pydantic.ValidationError`/`json.JSONDecodeError` are
themselves `ValueError` subclasses, so catching `ValueError` would silently swallow those too).
This validation is **required**, not optional, because JSON-Schema `minItems`/`maxItems`/`enum`/
nested-object constraints are advisory only (§10.2 already established this for scalar bounds;
it applies identically to array/object shape) — a malformed `team_1` entry (missing `"level"`,
a string where an object was expected, a `bool` passed for `level`, since `bool` is a Python `int`
subclass) would otherwise raise a raw `TypeError`/`KeyError` from inside the handler and crash
the agent loop, since `execute_tool` only catches a fixed exception tuple. Validates: each team is
a list of `MIN_TEAM_SIZE`–`MAX_TEAM_SIZE` dicts, each with a non-empty string `name_or_id` and an
`int` (not `bool`) `level`; `format` is exactly `"singles"` or `"doubles"`.

**1. Roster setup, once per call (not per simulation), per team member:**
- `get_pokemon` + level clamped to `[1,100]` (echoed back per member, same reasoning as the
  original spec: schema bounds are advisory only) + the same stat-conversion formula as before
  (`hp = floor(2*base*L/100)+L+10`, every other stat `floor(2*base*L/100)+5`, IV=0/EV=0/neutral
  nature baseline, unchanged).
- `get_level_up_moves` filtered to `level <= L`, highest-level 6, `get_move` each, drop
  `damage_class=="status"` or `power is None` — same candidate-selection logic as the original
  spec, but **kept as a list, not collapsed to one fixed move** (see next point).
- **Key behavioral change from the 1-vs-1 spec**: no fixed move is pre-selected once per battle.
  Opponents change over a team battle (a new teammate enters when one faints; doubles has two
  simultaneous opponents to pick between), so each active Pokémon re-scores its own candidate
  moves fresh every turn against whichever opponents are currently active (step 3 below).
- **Per-member zero-damaging-moves fallback**: an individual member with zero real damaging moves
  gets its own Struggle-equivalent fallback (`power:50, accuracy:100, type:normal, physical,
  target:"selected-pokemon"`) — same fallback value as before, now applied per member rather than
  per side. Only if **every** member on **both** teams needed this fallback does the tool skip
  simulation entirely for a deterministic draw (`simulations_run:0, draw_rate:1.0,
  average_turns_to_decide:null`), generalizing the original both-sides-zero rule.

**2. Type-effectiveness chart — a real performance fix, not present in the original spec.**
Calling `matchup.py`'s `get_type`-backed functions inside the simulation loop (2000 runs × up to
100 turns × up to 4 active attackers × up to 6 candidate moves × up to 2 targets, every turn)
would be tens of millions of HTTP calls. Instead, `battle.py` builds its own in-memory
`type_chart: dict[str, dict[str, float]]` **once per call** — one `get_type` per canonical type
(18 total; the type list hasn't changed since Generation VI and is a fixed domain constant, not
fetched), then every scoring/damage calculation inside the simulation loop is a pure dict lookup,
never an HTTP call. This chart is local to `battle.py`, independent of (and not a change to)
`matchup.py`, which `compare_pokemon` still uses as-is (its own cost is bounded and
accepted, §10.2).

**3. Per-simulated-battle loop** (`SIMULATIONS=2000` runs, HP reset each run):
- Active slots per side = `min(2 if doubles else 1, count of non-fainted members)`, filled by
  team-list order; this single rule implements both "which Pokémon are out" and "forced-switch
  replacement on faint" with no separate switch-tracking state, because it's recomputed fresh
  from each member's `fainted` flag at the start of every turn.
- Each turn: every active, non-fainted combatant picks one (move, target) pair once, from its
  current candidates, scored as `power * (accuracy/100) * stab * effectiveness` (`stab=1.5` if
  the move's type is one of the attacker's own types). For a single-target move, `effectiveness`
  is computed against the better-scoring of the currently-active opponents, tie-broken by lower
  current HP then lower team-list index (approximates focusing fire to secure a KO, and keeps the
  choice reproducible under a given `seed`). For a spread move (PokeAPI's move `target` of
  `"all-opponents"`/`"all-other-pokemon"`/`"entire-field"`, only when ≥2 opponents are actually
  active) `effectiveness = SPREAD_MODIFIER * sum(effectiveness against each active opponent)` — an
  expected-total-damage proxy, not a plain average (averaging would systematically undervalue
  spread moves whenever both opponents are merely neutral to it).
- All chosen actions across **both** sides (up to 4 in doubles) resolve in one combined order,
  sorted by `(-speed, a fresh random draw taken once per combatant per turn)` — not a single
  coin-flip, since doubles can produce 3- or 4-way speed ties, not just the original spec's 2-way
  tie. An action is skipped if its user fainted earlier the same turn; if its originally-chosen
  single target fainted earlier the same turn, it retargets the other live active opponent if one
  exists, else fizzles; a spread action simply drops any already-fainted original target from its
  hit list. Each target actually hit takes damage via the unchanged original formula (own
  accuracy roll, own `[0.85,1.0]` damage roll, `ATK`/`DEF` pair by `damage_class`), with spread
  hits additionally multiplied by `SPREAD_MODIFIER`. KOs are checked after each resolved action,
  not only at turn end.
- End-of-turn backfill (next non-fainted teammate takes an empty active slot) is **correctly
  modeled** end-of-turn-only behavior matching real doubles rules, not a simplification to
  apologize for.
- Battle ends when one side has zero non-fainted members (other side wins), both reach zero the
  same turn (draw), or `MAX_TURNS` is reached with survivors on both sides (draw) — the latter
  distinct from the all-fallback deterministic draw in step 1.

**4. Aggregation**: unchanged in kind from the original spec — `SIMULATIONS` independent runs,
`random.Random(seed)` if seeded else default `random`, tallying `team_1_win_rate`/
`team_2_win_rate`/`draw_rate` and `average_turns_to_decide` over decided (non-draw) battles only.

**Explicit, stated simplifications** (a best-effort approximation built from the same greedy
type-effectiveness heuristic as the original 1-vs-1 spec, not a competitive-grade engine): no
abilities, held items, weather, terrain, or entry hazards; no PP tracking; no ally damage modeled
(a move that in the real games would also hit an ally is treated here as hitting opposing actives
only); no protect/redirection moves (Follow Me, Rage Powder); no priority-move ordering beyond
base Speed; no voluntary switching.

**Return shape:**
```json
{
  "format": "doubles",
  "team_1": [{"id": .., "name": .., "level": 50, "candidate_moves": [{"name": "flamethrower", "power": 90, "type": "fire"}, ...]}, ...],
  "team_2": [...],
  "simulations_run": 2000,
  "team_1_win_rate": 0.63,
  "team_2_win_rate": 0.35,
  "draw_rate": 0.02,
  "average_turns_to_decide": 4.8
}
```
(`candidate_moves` lists every move a member might use, re-scored live each turn — unlike the
original spec's single fixed `selected_move`, there is no one move to report per member anymore.)

**Exceptions:** `PokemonNotFoundError` (from `get_pokemon`/`get_level_up_moves`), `MoveNotFoundError`
(from `get_move`), `TypeNotFoundError` (from the type-chart build, via `get_type`) — all three
already in `execute_tool`'s `except` tuple — plus the new `InvalidBattleInputError` from step 0,
which **does** require a change to `agent/tools.py`'s exception handling (the original spec's "no
change needed" claim did not survive the team/doubles generalization, same as §10.2).

**Tool schema** (first nested array-of-objects schema in this codebase — validates cleanly
against both the Anthropic `ToolParam`/JSON-Schema shape and mypy):
```json
{
  "name": "battle_win_probability",
  "input_schema": {
    "type": "object",
    "properties": {
      "team_1": {"type": "array", "items": {"type": "object",
          "properties": {"name_or_id": {"type": "string"},
                          "level": {"type": "integer", "minimum": 1, "maximum": 100}},
          "required": ["name_or_id", "level"], "additionalProperties": false},
        "minItems": 1, "maxItems": 6},
      "team_2": "... same shape as team_1 ...",
      "format": {"type": "string", "enum": ["singles", "doubles"]}
    },
    "required": ["team_1", "team_2"],
    "additionalProperties": false
  },
  "cache_control": {"type": "ephemeral"}
}
```
(Full description text lives in `agent/tools.py`, not duplicated here.) `format` is optional in
the schema; the Python default is `"singles"`, and the tool description tells the model to omit
it for a standard 1-vs-1 battle.

### 10.4 Known limitation, not solved by this spec

A 6v6 doubles battle needs up to ~96 PokeAPI calls for roster setup (2 teams × 6 members × up to
8 calls each: `get_pokemon` + `get_level_up_moves` + ≤6 `get_move`) plus 18 one-time type-chart
calls ≈ **~114 calls total**, all done once at setup, not per Monte Carlo run (the 2000 simulated
battles themselves make zero additional HTTP calls, per §10.3 step 2's fix). `get_pokemon` and
`get_level_up_moves` each independently fetch the same underlying Pokémon resource today — a
small, accepted duplicate-fetch inefficiency, not fixed here since doing so would mean touching
already-shipped `service.py` functions. No caching layer exists project-wide
(PRODUCTION_READINESS.md §10, "Caching & PokeAPI etiquette") and no client-side throttle exists
(PRODUCTION_READINESS.md §13, guardrails) — this tool is the clearest case yet for why those gaps
matter; worth prioritizing before it sees real/repeated use.

**A real, separate bug this tool's development surfaced and fixed**: `pokemon_service.get_type`
previously called `pypokeclient`'s typed `_client.get_type(...)`, whose `Type` pydantic model
requires `move_damage_class` to be a resource — but the live PokeAPI returns `null` there for the
Fairy type, so **any** call to `get_type("fairy")` raised an uncaught `pydantic.ValidationError`
(not an `HTTPStatusError`, so `get_type`'s own `try/except` never saw it). This was already a
live bug in shipped code: `compare_pokemon`/`matchup.py` would crash on *any* Fairy-type Pokémon
(e.g. `compare_pokemon(["sylveon", "pikachu"])`), discovered only because `battle.py`'s
type-chart build is the first code path to unconditionally call `get_type` on every canonical
type, Fairy included. Fixed by switching `get_type` to the raw-JSON `_api_request` pattern
`get_move`/`get_pokemon_form` already use for the same class of problem (nullable fields the typed
client doesn't tolerate), instead of `_client.get_type`. Confirmed fixed live:
`compare_pokemon(["sylveon", "pikachu"])` now succeeds.

## 11. Generic JSON-compaction layer between services and tools (spec)

Status: **designed, not implemented** — no `agent/compact.py` file exists yet. Scoped from a
web-research pass (see chat for sources) plus the project's own existing precedent: `get_move`
and `pokemon/evolution.py::map_evolution_detail` already hand-trim "no-op" fields per call
(PRODUCTION_READINESS.md §2), but that trimming is bespoke per function, has to be re-derived for
every new service, and still misses cases *within* those same functions (see §11.4). This spec
generalizes that one existing technique into a single reusable function, rather than inventing a
new one, after researching what else is actually effective.

### 11.1 What the research actually supports (and what it doesn't)

Three families of technique showed up:

1. **Drop null/empty fields.** Consistently described as a safe, "lossless" first-pass
   optimization — a field that is `null`/`""`/`[]`/`{}` carries no information but still costs
   tokens. The one universal caveat across sources: never treat `false` or `0` as empty — those
   are real values (a `pp` of `0`, an `is_hidden` of `false`), not absence. This is the technique
   this spec adopts (§11.3).
2. **Format substitution** (JSON → YAML, or newer schemes like TOON/TRON). Results are mixed and
   format-dependent — one benchmark found YAML can cost *more* tokens than JSON on certain
   shapes (object-heavy, highly nested) despite dropping braces/quotes, while newer formats like
   TOON claim ~40%+ reduction specifically on uniform tabular data. JSON itself remains described
   as the reliable default because models parse it most consistently. **Rejected for this repo**:
   this project's entire data shape is small, irregular, deeply-nested objects (not large uniform
   tables), which is exactly the shape where format-swap gains are weakest and parsing-reliability
   risk is least justified by the payoff. Adopting it would also mean a new dependency and a new
   serialization convention across every tool — a much bigger change than the one-line
   `json.dumps` → `json.dumps(compact(...))` swap this spec proposes for comparable benefit.
3. **Semantic/structural compression** (observation masking, LLM-based summarization, aggressive
   key renaming). Aimed at a different problem — multi-turn agent trajectories where *old* tool
   outputs pile up in history, or very large tool outputs (logs, file dumps). **Not this
   project's problem**: every existing/planned tool response here is one self-contained object a
   few hundred bytes to a few KB large (not a growing trajectory, not a log dump), so the
   heavyweight techniques in this family solve a problem this codebase doesn't have yet. Key
   renaming (e.g. `base_stat` → `bs`) was also considered and rejected on its own merits — the
   token savings on keys this short are marginal, and it directly fights this project's own
   stated preference for explicit, readable names over premature micro-optimization.

### 11.2 Where it lives and what it does and doesn't touch

New file `agent/compact.py`, one function, no imports from `pokemon/`. It lives in `agent/`
specifically because its only consumer is `agent/tools.py` — the dispatch bridge that already
owns the service → model serialization boundary (§5). This is **not** framed as a general
cross-cutting utility that happens to be placed in `agent/`; its location *is* its scope: the
one call site inside `execute_tool`, right before the existing `json.dumps(result)` call,
immediately before a handler's return value is serialized for the model to see:

```python
return json.dumps(compact(result)), False
```

**Scope boundary, stated explicitly because it matters for §10:** `compact()` only runs at this
one call site. Any code that calls a `pokemon_service` function *directly* — `battle.py`,
`comparison.py`, and `matchup.py` from §10 all do this, never going through `execute_tool` —
receives the service's raw, uncompacted return value. §10.3 step 2's `power is None` check
(used to detect and exclude status moves) keeps working exactly as specced, because it never
sees compacted data in the first place. Compaction is a presentation-layer concern for what the
*model* sees, not a transformation on the data services hand to other in-process Python code.

### 11.3 The pruning rule

```python
JSONValue = dict[str, "JSONValue"] | list["JSONValue"] | str | int | float | bool | None

def compact(value: JSONValue) -> JSONValue:
    """Recursively drop None/""/[]/{} — never a meaningful `False` or `0` — from dicts and
    lists. The argument's own container type is always preserved: a dict in, a dict out (even
    an empty one); only values *within* it are ever removed."""
    if isinstance(value, dict):
        return {
            key: compacted
            for key, raw in value.items()
            if (compacted := compact(raw)) not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [
            compacted
            for raw in value
            if (compacted := compact(raw)) not in (None, "", [], {})
        ]
    return value
```

(Recursive type aliases of this shape are supported by mypy well before the version pinned in
`pyproject.toml` — this should type-check as written, not as a hedge.)

Two invariants worth stating outright, since a generic recursive function invites edge cases:

- **The root is never deleted, only shrunk.** `execute_tool` always calls `compact()` with a
  `dict` (every handler returns one); the function always hands back a `dict` in that case, even
  `{}` in a pathological case where every field happened to be empty. `json.dumps({})` is valid,
  so the "tools never raise" contract (§5) holds either way — it would just be an uninformative
  but not broken result. In practice this doesn't occur today: every existing and §10-planned
  service always includes at least one stable, never-empty identifying field (`id`, `name`, or a
  `pokemon_1`/`pokemon_2` wrapper).
- **`False` and `0` always survive**, by construction of the `not in (None, "", [], {})` check —
  equality against that tuple is `False` for both, so neither is ever mistaken for "empty."

**Stance on `None`, stated explicitly (per §11.1's one caveat):** this spec treats "key absent"
and "key present with value `None`" as equivalent to the model — a key that doesn't appear means
"not applicable to this entry," the same convention `get_move`'s existing conditional fields
(`effect_chance`, `meta.ailment`, etc.) already establish by omission. `compact()` simply applies
that same convention uniformly, including to `get_move`'s *unconditional* base fields (`power`,
`accuracy`) that currently leak a literal `"power": null` to the model today. Recommended
follow-up (not required for this spec): tool descriptions in `TOOLS` could state this convention
explicitly for the model's benefit — left as a documentation nit, not a blocker.

### 11.4 Relationship to the existing manual trimming (`get_move`, `pokemon/evolution.py`)

Not redundant, and not touched by this spec. The manual `if`-guards in `get_move` and
`map_evolution_detail` decide **which keys get built into the dict in the first place** (e.g.
"only add a `meta` sub-dict key if the category says something") — a decision that requires
domain knowledge the generic layer deliberately doesn't have (it can't know that
`required_pokemon_form` repeating the base species name is noise — PRODUCTION_READINESS.md §2's
open item — because that requires knowing what an eeveelution is). `compact()` operates one step
later, on **whether an already-built key survives serialization** once it's known to be
None/empty. The two are complementary, not overlapping: this spec's function catches cases the
manual trimming doesn't (`get_move`'s unconditional `power`/`accuracy`, and any *future* service
that is written without hand-trimming at all), while leaving domain-specific decisions where they
already live.

### 11.5 Verification

No live API calls needed — pure function, no I/O, the first realistic candidate in this codebase
for an actual `pytest` unit test (zero exist today, per PRODUCTION_READINESS.md §6). Concrete
before/after check to confirm the feature does what it claims:
`len(json.dumps(result))` vs. `len(json.dumps(compact(result)))` on two known-verbose real
responses — `get_move` for a status move with `power: null` (e.g. `"growl"`), and
`get_evolution_chain` for an eeveelution (many near-empty condition dicts). Character count is a
cheap proxy for token count, not a substitute for it; the Anthropic SDK's token-counting endpoint
can confirm actual token deltas later if a precise before/after number is wanted.

## 12. Games/versions — `pokemon/games.py` (implemented)

One new exception: `VersionNotFoundError` — raised by `get_version`, `get_version_group`, and
`get_generation` (all in `service.py`) on a 404; the latter two use already-valid resource links
from a successfully-resolved version, so they shouldn't 404 in practice, but raise the same
exception defensively rather than assume. All three new `service.py` functions use the raw-JSON
`_api_request` pattern (not the typed `pypokeclient` client methods), consistent with the
Fairy-type lesson from §10.4 — safer by default now that one typed-model crash has already been
found and fixed.

```python
def get_game_info(name_or_id: str) -> dict:
```
Resolves `version -> version_group -> generation -> sibling versions -> region(s)`:
```json
{"version": "omega-ruby", "version_group": "omega-ruby-alpha-sapphire",
 "sibling_versions": ["alpha-sapphire"], "generation": "generation-vi", "regions": ["hoenn"]}
```
**A real correctness fix made during implementation, not in the original spec**: `regions` comes
from `version_group.regions`, not `generation.main_region`. A remake like Omega Ruby is
Generation VI (whose flagship region, per `main_region`, is Kalos) but is itself set in Hoenn —
using `main_region` would have reported "kalos" for a Hoenn game. `version_group.regions` gives
the actual region(s) for that specific game; confirmed live and is always a list (a version group
can, in principle, span more than one region).

**Known gap, stated plainly in the tool description**: this resolves which generation/region a
game belongs to, not concrete cross-generation rule differences. `past_types`/`past_abilities`/
`past_stats` (on `Pokemon`), `past_damage_relations` (on `Type`), `past_values` (on `Move`) are
confirmed present in the live API but deliberately out of scope for this pass, per the user's own
versioning-depth decision (§10 already established this pattern for `compare_pokemon`/
`matchup.py`, which likewise don't apply version-group filtering or `past_*` overrides).

`get_pokemon_locations`/`get_location_encounters` below call `get_game_info` internally to
validate an optional `version` argument early — a clean `VersionNotFoundError` instead of a
silently-empty result for an unknown game name.

## 13. Locations — `pokemon/locations.py` (implemented)

One new exception: `LocationNotFoundError` — raised by `get_location`/`get_location_area` on a
404 (both in `service.py`, raw-JSON). `get_pokemon_location_area` (also in `service.py`, hits
`pokemon/{id}/encounters`) raises the existing `PokemonNotFoundError` instead, since a 404 there
means the Pokémon identifier was bad, not a location one.

**Aggregation — the part that had to be verified, not assumed.** Confirmed live (Poochyena in
Petalburg Woods, Emerald: two `encounter_details` slots of `chance` 20 and 10 for the same
method, summing to exactly the API's own `max_chance: 30`) that summing `chance` within one
`(version, method)` is correct. `_totals_by_group` groups strictly by
`(method, frozenset(condition_values))` — not just `method` — because condition values like
`time-night` (confirmed live via Hoothoot) are mutually exclusive alternatives, not concurrent
probabilities; summing across them, not just across methods, would overstate the real chance.
`_aggregate` then sums within each version and, when no `version` filter is given, averages that
per-version total across every version where the group appears — live-verified on Zubat (many
level-range slots, single method) and Hoothoot (time-of-day condition) that no resulting group
ever exceeds 100%.

```python
def get_pokemon_locations(name_or_id: str, version: str | None = None) -> dict:
def get_location_encounters(name_or_id: str, version: str | None = None) -> dict:
```
Forward (`get_pokemon_locations`) groups by location-area → method → condition-combo; reverse
(`get_location_encounters`) fans out over every area of a `Location` and groups by area → pokemon
→ method → condition-combo — both read the identical underlying `VersionEncounterDetail`/
`Encounter` shape, just entered from opposite directions, confirmed live. Both have a precomputed
single-best shortcut (`most_likely_location` / `most_common_pokemon`) that excludes one-off
methods (`ONE_OFF_METHODS` — `gift`, `gift-egg`, `static`, `npc-trade`, and several event-only
methods, confirmed against the live `encounter-method` list), so a 100%-chance static/gift
encounter never crowds out genuinely repeatable wild encounters in that one ranked pick.

**A real bug found and fixed during implementation, not in the original spec**: the first draft's
single "no encounters" note fired whenever the shortcut couldn't be computed — including when a
Pokémon has exactly one real encounter, just a one-off one. Confirmed live: `get_pokemon_locations
("mew")` returns a real `locations` entry (a static encounter on Faraway Island, Emerald) while
also claiming "no recorded wild encounter locations," which is self-contradictory. Fixed with two
distinct notes: `NO_POKEMON_ENCOUNTERS_NOTE`/`NO_LOCATION_ENCOUNTERS_NOTE` only fire when the
breakdown is truly empty; `ONLY_ONE_OFF_ENCOUNTERS_NOTE` fires when real entries exist but none
are rankable, explicitly pointing at the full breakdown instead of a "most likely" pick that
wouldn't be meaningful there.

Tool descriptions state plainly: `chance_percent` without a `version` filter is a cross-game
average, not one exact game's number; `conditions` are listed, never merged.

## 14. Items — `pokemon/items.py` (implemented)

One new exception: `ItemNotFoundError`, raised by `get_item` (`service.py`, raw-JSON).

```python
def get_item(name_or_id: str, pokemon_name_or_id: str | None = None) -> dict:
```
Structured: `category`, `attributes`, `fling` (`{power, effect}`, included only when
`fling_power is not None`, same conditional-inclusion convention as `get_move`'s `meta`),
`held_by_pokemon` (`[{pokemon, rarity_by_version: [{version, rarity_percent}]}]`), `prices`
(`[{version_group, purchase_price, sell_price}]`), `machines` (`[version_group names]` only — not
resolving the taught move, which would need an unexplored extra call). Free text: `effect` (first
English `effect_entries` match, same convention as `get_move`).

**Confirmed live, worth stating plainly in the tool description rather than assuming**: `prices`
is frequently an empty list even for clearly purchasable items (`potion`, `hyper-potion`,
`repel`, `revive` on the real public PokeAPI all return `prices: []`) — PokeAPI's price data
coverage is genuinely incomplete, well-populated for some categories (confirmed non-empty for
`great-ball`) but not most consumables. An empty list means "not recorded," not "free" or
"unobtainable" — the tool description says so explicitly so the model doesn't over-interpret
silence as a negative fact.

If `pokemon_name_or_id` is given, fetches it via the existing `pokemon_service.get_pokemon`
(reuses `PokemonNotFoundError`) and includes `{id, name, types}` under `"pokemon"`. Per the user's
explicit choice (§ user decisions, recorded in the implementation plan): no hardcoded
item→type-boost table, no evolution-chain cross-reference — the tool description tells the model
plainly that this is the one deliberate exception to this project's "tool pre-computes, model
never reasons" philosophy: when `pokemon` is present, the model judges the held-item/type synergy
itself by reading `effect` against `pokemon.types`.

## 15. RAG — legendary Pokémon lore (`rag/`) (implemented)

Lets the agent answer lore questions (biology, Pokédex entries, origin, name origin) about
**legendary Pokémon only, generations 1–9**, from Bulbapedia Markdown in `legendary-lore/`. That
folder is git-ignored: the content is CC BY-NC-SA 2.5, not covered by the project license, and lives
in its own repo. Everything is hand-built — `numpy` for the vectors, no vector database, no RAG
framework — consistent with the rest of the project. **Indexing is a separate, manual, offline
step**; the agent only reads the finished index and never indexes at run time.

### 15.1 Two phases, one contract

```
OFFLINE   uv run pokedex-index
  legendary-lore/**/*.md ─chunk_markdown─> [Chunk] ─embed_documents─> (N, 384) matrix
        └──────────── data/index/embeddings.npy  +  data/index/chunks.json ────────────┘

AGENT TIME   agent_loop() ─> preload_index()   (background thread, see 15.6)
  user question ─(Claude writes the query in English)─> search_lore(query)
        ─embed_query─> (384,) vector ─ matrix @ vector ─> N scores ─ top 5 ─> chunks.json rows
```

The contract between the phases: **row *i* of `embeddings.npy` is the embedding of `chunks[i]` in
`chunks.json`**. `chunks.json` also records the `model` and `dimension` the index was built with, so
the search can refuse an index that doesn't match the current model.

### 15.2 Configuration

- `documents_location` (`DOCUMENTS_LOCATION`, default `legendary-lore`) and `index_location`
  (`INDEX_LOCATION`, default `data/index`) are `Settings` fields (`Path`). Unlike the other fields
  they have **defaults**: an existing `.env` without them must not stop the agent from starting.
  `data/` is git-ignored — the index is regenerable.
- The embedding model name is a **module constant** (`embedder.MODEL_NAME`), not a setting, on the
  same reasoning as `battle.py`'s constants: it is coupled to the index (vectors from different models
  are not comparable), not deployment config.

### 15.3 `chunking.py` — Markdown → `Chunk`

`chunk_markdown(path) -> list[Chunk]`; `Chunk(pokemon, generation, source, section, text)`, frozen.

1. `_parse_front_matter`: the `---` block (`FRONT_MATTER_RE`) → `key: value` dict (split on the first
   `": "`, since `source` URLs contain colons); falls back to the file stem if `pokemon` is missing.
2. Sections: `HEADING_RE` matches `##`/`###` lines (a single `#` is the Pokémon's name, already in the
   front matter). A section's text runs from its heading to the next one, so there is no duplication
   between a `##` and its `###` children. `section` is `"Biology"` or `"Origin > Name origin"`.
3. Paragraphs: each section is split on blank lines (`PARAGRAPH_RE`); **one chunk per paragraph**.
4. Size budget: a paragraph longer than `MAX_CHUNK_CHARS = 1500` is split by `_split_to_budget`:
   `_split_units` cuts on lines first (a bullet of *Pokédex entries* stays whole), then on sentences
   (`SENTENCE_RE`), gluing back a cut that follows `ABBREVIATIONS = ("Mr.", "Mt.", "St.")`; the units
   are then greedily packed up to the budget. A single unit over budget is emitted alone.
5. `Chunk.text` = `"{pokemon} — {section}\n\n{body}"`. The prefix is part of what gets embedded, so a
   bare sentence like "It is said to live in another world" still names its Pokémon.

Measured on the 71 files: **816 chunks**, longest body 1497 chars, longest chunk **379 tokens** against
the model's 512-token window (0 truncated). The 1500-char budget is a model-agnostic proxy; the real
check is `embedder.truncated_indices` (15.4), run by the indexer.

### 15.4 `embedder.py` — text → vector

- Model: `BAAI/bge-small-en-v1.5` (384 dimensions, 512-token window) via `sentence-transformers`.
  English-only on purpose: the LLM writes the query in English (15.7), so a multilingual embedder
  isn't needed. Chosen as a light baseline for future evals.
- `embed_documents(texts) -> (N, 384)` and `embed_query(query) -> (384,)` call the library's
  `encode_document` / `encode_query`, which apply the model's own configured prompts. For this model
  those prompts are empty, so **no query prefix is applied** (an open experiment, 15.9). The two
  functions are separate so swapping to a model with asymmetric prefixes only changes this file.
- Both pass `normalize_embeddings=True` explicitly, so every vector has length 1 and
  `matrix @ vector` *is* cosine similarity. The model happens to normalize already; the explicit flag
  keeps the invariant independent of the model.
- `truncated_indices(texts)` tokenizes with the model's own tokenizer and returns the positions
  exceeding `max_seq_length` (silent truncation otherwise). `max_seq_length is None` → `[]`.
- `_get_model()` is `lru_cache`d and **imports `sentence_transformers` inside the function**.
  Importing torch took ~9 s and, because `tools.py` imports the RAG service, blocked every CLI startup
  (measured: `import pokedex` 8.8 s vs ~0.7 s). Deferred, it runs in the preload thread. The
  HF/transformers verbosity env vars and the torch-redirects logger are set (via `setdefault`, so a
  user-set value wins) *before* that import, because the libraries read them at load time; this keeps
  the weight-loading bar and hub warnings from printing over the chat prompt. Side effect: only
  *errors* from those libraries are shown, in the agent and in the indexer.

### 15.5 `indexer.py` — the offline command

Registered as `pokedex-index = "pokedex.rag.indexer:main"` in `[project.scripts]` — a command that
runs **before** the agent, never inside it. `main()`: `rglob("*.md")` (sorted, for reproducibility) →
`chunk_markdown` → fail with a clear message if there are no chunks → `embed_documents` →
`truncated_indices` → `_write_index` → print a summary, plus a `WARNING` listing any truncated chunk.

`_write_index` writes `embeddings.npy` (via an open file handle: `np.save` on a path without a `.npy`
suffix would append one) and `chunks.json` (`{"model", "dimension", "chunks": [asdict(chunk), …]}`,
`ensure_ascii=False`) to `.tmp` files, then `os.replace`s both, so a crash mid-write cannot leave a
new matrix beside old metadata. The window between the two renames is tiny but not zero.

Verified: matrix `(816, 384)` float32; re-embedding random chunks reproduces their rows; no leftover
`.tmp` files; re-running overwrites cleanly. ~4.5 s to embed everything on Apple `mps`.

### 15.6 `service.py` — loading and searching

- `preload_index()` — called as the first line of `agent_loop` — submits `_load_index` to a
  single-worker `ThreadPoolExecutor` once (lock-guarded, idempotent) and returns the `Future`. The
  agent prompt appears immediately; loading overlaps with the user typing.
- `_load_index()` returns `None` if the index files don't exist (the agent still works; search
  returns nothing). Otherwise it loads both files and raises `InvalidIndexError` when they are
  unreadable (`OSError`/`ValueError`/`KeyError`), when `model` differs from `MODEL_NAME`, or when the
  matrix shape isn't `(len(chunks), dimension)`. A same-dimension model mismatch would otherwise
  return silent garbage, which is why it is an error and not an empty result. Finally it calls
  `embed_query("warm up")` so the model is loaded in this thread and the first real search isn't slow.
- `search_lore(query) -> dict` waits on the future (`.result()`; a failed load re-raises on every
  call), returns `{"results": []}` for a missing index or a blank/non-string query, then
  `scores = embeddings @ embed_query(query)` and the top `TOP_K = 5` via `np.argsort(scores)[::-1]`.
- `embed_query` runs under `_query_lock`: the agent loop executes tools concurrently and thread-safety
  of the model (notably on `mps`) was not verified, so queries are serialized — milliseconds each.
  The matrix `@`/`argsort` are read-only and need no lock.
- Each result: `pokemon`, `generation`, `section`, `source`, `score` (3 decimals), and `text` **with the
  `"Pokémon — Section\n\n"` prefix removed** (`partition("\n\n")[2]`, which relies on that separator
  from `chunking.py`) — the prefix is redundant with the other fields in what the model reads.
  `source` (the Bulbapedia URL) is returned so answers can be attributed.

### 15.7 The tool — `search_lore(query: str)`

Standard pattern (§5): an entry in `TOOLS`, `"search_lore": search_lore` in `_HANDLERS`, and
`InvalidIndexError` added to `execute_tool`'s `except`, so a bad index reaches the model as
`(message, is_error=True)` telling it to rebuild with `pokedex-index`, instead of raising.
The description is deliberately short: legendary Pokémon only, generations 1–9, what it covers,
returns passages with their source, **write the query in English** — that sentence is what replaces
a multilingual embedder. It also says the tool *always* returns the closest passages even when none
really answers the question (there is no similarity threshold, 15.8), so the model is told to check
relevance itself rather than read an empty result as "no match". `search_lore` is now the **last** entry in `TOOLS`, so it carries the
`cache_control: ephemeral` breakpoint (moved from `get_item`; one breakpoint at the end of the list).

### 15.8 Decisions

- `TOP_K = 5`, fixed and not exposed in the schema (~2,000 chars, ~500 tokens per call).
- **No similarity threshold.** bge-small's scores are compressed (clearly related ≈ 0.72, loosely
  related ≈ 0.69), so any cutoff would be a guess; to be calibrated with evals.
- An empty result is just `{"results": []}`, with no note distinguishing "no index" from "no match".
- The index is loaded **once per process**, eagerly and concurrently, rather than per call.

### 15.9 Known gaps

- **Irrelevant results are still returned.** With no threshold, a non-blank query on a built index
  *always* yields 5 results, however unrelated (e.g. "ghost pokemon that lives in a cave" returned
  Zygarde/Regigigas/Necrozma); an empty result only means a missing index or a blank query. The tool
  description says so and leaves the relevance judgment to the model; a threshold waits for evals.
- **No evals and no automated tests** for the RAG. It was verified by calling `execute_tool` directly
  (no Anthropic API): top results for sample queries, empty/non-string queries, 4 concurrent searches
  matching sequential ones, and missing / wrong-model / corrupt / inconsistent indexes. A full agent
  run confirming that Claude chooses `search_lore` for lore questions is not recorded here.
- The index is not reloaded: regenerating it needs an agent restart, and an index absent at startup
  stays absent for that process. A search issued in the first few seconds waits for the preload.
- Every `pokedex` command imports the agent (`pokedex/__init__.py` → `loop.py`), so `pokedex-index`
  also requires a valid `.env` (API key) even though it never calls the API.
- Chunking limits: the abbreviation list is closed (`Dr.`, `Jr.` would mis-split); packed pieces lose
  their original line breaks; very short chunks remain (shortest body 23 chars); a source artifact —
  a blank line inside a sentence in some files — splits that sentence into two chunks.
- Experiments queued for evals: the bge query-instruction prefix; chunk budget (e.g. 1500 vs ~1800
  chars, or no splitting with a long-window model such as `gte-modernbert-base`, 8192 tokens);
  *sentence-window* retrieval (embed ~3,800 sentences, return the parent paragraph).
