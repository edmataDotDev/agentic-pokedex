# Pokédex — Architecture

A CLI AI agent built with the Anthropic Python SDK (manual agentic loop, no Tool Runner),
using `pypokeclient` as its data source. Built as a learning project in agent engineering
fundamentals — every piece here was deliberately designed, not scaffolded automatically.

## 1. Layers and dependency direction

**Filesystem layout** — `agent/`, `pokemon/`, and `cli/` are siblings, all directly under
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

## 10. Planned tools — battle win-probability & deterministic compare

Specs two tools named informally in PRODUCTION_READINESS.md §14. Both follow the existing
`TOOLS` + `_HANDLERS` + service-function pattern (§5). Status: `compare_pokemon` is **implemented**
(§10.2, generalized to N≥2 Pokémon rather than the originally-specced fixed pair — see below);
`battle_win_probability` (§10.3) remains **designed, not implemented**. Only the battle tool's
claim of "no new exception class or change to `execute_tool`'s `except` tuple" still holds —
`compare_pokemon` needed one (`InvalidComparisonInputError`), explained in §10.2.

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

### 10.3 `battle_win_probability` — Monte Carlo battle tool

New file `pokemon/battle.py`. Module-level constants (not `Settings` fields — adding a required
`Settings` field with no default would break any existing `.env`; these are simulation
parameters, not deployment config): `SIMULATIONS = 2000`, `MAX_TURNS = 100`.

```python
def battle_win_probability(
    name_or_id_1: str, level_1: int,
    name_or_id_2: str, level_2: int,
    seed: int | None = None,
) -> dict:
```

(`seed` is **not** exposed in the tool's `input_schema` — Claude never sets it; it exists purely
so the function is unit-testable deterministically later, since zero tests exist today.)

**1. Level → stat conversion (resolves PRODUCTION_READINESS.md's unstated "baseline stats only"
note — without this step, `level` would barely affect anything):**
With IV=0, EV=0, neutral nature (the stated baseline simplification):
- `hp = floor(2 * base_hp * L / 100) + L + 10`
- every other stat = `floor(2 * base_stat * L / 100) + 5`

Level is clamped to `[1, 100]` **inside the service function**, not rejected — nothing in this
codebase enforces JSON Schema bounds server-side, so the schema's `minimum`/`maximum` are
advisory only; the service must defend itself regardless. The clamped value actually used is
echoed back in the result (`"level"` in the output, see return shape) so the model/user can see
if clamping happened. This keeps the "tools never raise" contract intact without adding a new
exception for "invalid level."

**2. Candidate move selection (resolves the §14 claim that filtering to known-by-level moves
avoids fetching "dozens" of moves — it doesn't, by itself: `get_level_up_moves` returns names
only, and a level-50 Pokémon can easily know 20–40 level-up moves):**
- Call `pokemon_service.get_level_up_moves(name_or_id)`, filter to `level <= L`.
- Take the **highest-level N=6** of those (moves learned closer to the current level skew
  stronger; 6 approximates a real moveset with some margin for status-move filtering). If fewer
  than 6 qualify, use all of them.
- Call `pokemon_service.get_move(name)` for each of the ≤6 survivors (≤12 total `get_move` calls
  per battle, plus 2 `get_pokemon` + 2 `get_level_up_moves` — ~16 PokeAPI round-trips worst case;
  see "Known limitation" below).
- Drop any move where `damage_class == "status"` or `power is None` (can't be scored by the
  power/accuracy/effectiveness heuristic; `get_move` already returns `None` correctly for these
  per its documented nullable-field fix).
- **If a side ends up with zero damaging moves** (e.g. very low level, or a movepool that's
  genuinely all status moves within the filtered window), that side's "selected move" becomes a
  fixed fallback: `{power: 50, accuracy: 100, type: "normal", damage_class: "physical"}` — a
  Struggle-equivalent, chosen for determinism rather than crashing or returning an error.
  **If both sides end up with zero real damaging moves**, skip simulation entirely and return a
  deterministic draw (`simulations_run: 0`, `draw_rate: 1.0`, `average_turns_to_decide: null`) —
  this is a detectable deterministic case, not something that needs 2000 Monte Carlo runs to
  discover, and must be reported distinctly from "hit the turn cap."

**3. Move scoring (per PRODUCTION_READINESS.md's existing design, confirmed, unchanged):**
`score = power * (accuracy / 100) * matchup.best_type_matchup([move_type], opponent_types)`.
Highest-scoring candidate becomes that side's single fixed move for every simulated battle (the
opponent's types don't change mid-battle, so re-scoring per turn would be wasted work).

**4. Damage formula (standard simplified formula, no IV/EV/nature — same simplification level as
the stat conversion above):**
```
damage = floor( ( (2*L/5 + 2) * power * (ATK/DEF) / 50 ) + 2 ) * STAB * effectiveness * roll
```
- `ATK/DEF` = `Attack`/`Defense` if `damage_class == "physical"`, else `Special Attack`/
  `Special Defense` if `"special"` (PokeAPI only has these two damaging categories).
- `STAB = 1.5` if the move's type is one of the attacker's own types, else `1.0`.
- `effectiveness` = the same `best_type_matchup` value used for scoring (recomputed or cached;
  same inputs, same result).
- `roll` = uniform random in `[0.85, 1.0]`, resampled every hit.
- Before computing damage, roll uniform `[0, 1)` against `accuracy/100`; on miss, `damage = 0`
  for that attack this turn (no retry).

**5. Turn order & loop:** higher `Speed` acts first each turn; exact ties resolved by a fresh
coin-flip **every turn** (not fixed once per battle — matches real game behavior, per the
existing design note). Each turn: faster side attacks, loser checked for KO; if still alive,
other side attacks, checked for KO; turn count increments. Loop ends on a KO or at `MAX_TURNS`
(100) — reaching the cap with both sides alive counts as a draw **for that one simulated
battle**, distinct from the "no damaging moves at all" deterministic draw in step 2.

**6. Aggregation:** run `SIMULATIONS` (2000) independent battles (HP reset each run), using
`random.Random(seed)` if a seed was passed, else the module's default `random`. Tally win counts
per side, draw count, and the turn count of every *decided* (non-draw) battle for an average.

**Return shape** (no per-turn log — same token-cost discipline as `get_move`'s trimming):
```json
{
  "pokemon_1": {"id": .., "name": .., "level": 50, "selected_move": {"name": "flamethrower", "power": 90, "accuracy": 100, "type": "fire"}},
  "pokemon_2": {"id": .., "name": .., "level": 50, "selected_move": {...}},
  "simulations_run": 2000,
  "pokemon_1_win_rate": 0.63,
  "pokemon_2_win_rate": 0.35,
  "draw_rate": 0.02,
  "average_turns_to_decide": 4.8
}
```

**Exceptions:** `PokemonNotFoundError` (from `get_pokemon`/`get_level_up_moves`), `MoveNotFoundError`
(from `get_move`), `TypeNotFoundError` (from `matchup`, via `get_type`) — **all three already in
`execute_tool`'s `except` tuple today. No change needed to `agent/tools.py`'s exception
handling** for this tool either.

**Tool schema:**
```json
{
  "name": "battle_win_probability",
  "description": "Estimates the win probability between two Pokémon at independently given levels, via Monte Carlo simulation (2000 simulated battles) using each side's best level-appropriate damaging move. Reports win rate per side, draw rate, and average turns to decide — a measured rate, not a formula-based guess.",
  "input_schema": {
    "type": "object",
    "properties": {
      "name_or_id_1": {"type": "string"},
      "level_1": {"type": "integer", "minimum": 1, "maximum": 100},
      "name_or_id_2": {"type": "string"},
      "level_2": {"type": "integer", "minimum": 1, "maximum": 100}
    },
    "required": ["name_or_id_1", "level_1", "name_or_id_2", "level_2"],
    "additionalProperties": false
  }
}
```

### 10.4 Known limitation, not solved by this spec

`battle_win_probability` costs up to ~16 PokeAPI round-trips per call (vs. 1 for every existing
tool) with no caching (PRODUCTION_READINESS.md §10, "Caching & PokeAPI etiquette") and no
client-side throttle (PRODUCTION_READINESS.md §13, guardrails). Those gaps already exist today
but this tool is the first one that makes them actually hurt latency/etiquette noticeably. Worth
prioritizing the caching item before this tool sees real/repeated use; not blocking for the spec
itself.

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
