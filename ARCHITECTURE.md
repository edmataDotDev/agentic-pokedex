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
- **`compare_pokemon`** (or similar second tool) — intentionally left for independent
  design practice, following the same `TOOLS` + `_HANDLERS` + service-function pattern
  as `get_pokemon`.
- **Sequential, not concurrent, tool execution** — `run_llm_turn`'s `"tool_use"` branch runs
  a plain `for` loop over `tool_use_blocks`, calling `execute_tool` one at a time. The SDK
  docs recommend executing parallel tool calls concurrently (they still get returned together
  in one `tool_result` message, which `run_llm_turn` already does correctly — only the
  *execution* is sequential, not the response shape). Not a correctness bug, just slower than
  necessary once a turn ever involves multiple tool calls at once (e.g. a future
  `compare_pokemon` implemented as two parallel `get_pokemon` calls).

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

## 10. Planned tools — battle win-probability & deterministic compare (spec)

Specs two new tools named informally in PRODUCTION_READINESS.md §14. Status: **designed, not
implemented** — no `.py` files exist yet for either. Both follow the existing `TOOLS` +
`_HANDLERS` + service-function pattern (§5); neither requires a new exception class or a change
to `execute_tool`'s `except` tuple (verified below, per tool).

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

### 10.2 `compare_pokemon` — deterministic compare tool

New file `pokemon/comparison.py`. Purely arithmetic — no randomness, no simulation, which is the
point of calling it "deterministic" (as opposed to the battle tool below).

```python
def compare_pokemon(name_or_id_1: str, name_or_id_2: str) -> dict:
```

1. `pokemon_service.get_pokemon(name_or_id_1)` and `(name_or_id_2)` — reuse as-is, two calls.
2. Per-stat diff for all six stats (`hp`, `attack`, `defense`, `special-attack`,
   `special-defense`, `speed`): `{"stat": name, "pokemon_1": v1, "pokemon_2": v2, "diff": v1-v2}`.
3. Base stat total (sum of the six) for each side, plus its diff.
4. Type matchup, using `matchup.best_type_matchup`: best multiplier Pokémon 1's typing achieves
   attacking Pokémon 2, and vice versa (two numbers, not one — matchups aren't symmetric).

Return shape:
```json
{
  "pokemon_1": {"id": .., "name": .., "types": [..]},
  "pokemon_2": {"id": .., "name": .., "types": [..]},
  "stat_comparison": [{"stat": "hp", "pokemon_1": 35, "pokemon_2": 44, "diff": -9}, ...],
  "base_stat_total": {"pokemon_1": 320, "pokemon_2": 314, "diff": 6},
  "type_matchup": {
    "pokemon_1_best_multiplier_vs_pokemon_2": 2.0,
    "pokemon_2_best_multiplier_vs_pokemon_1": 0.5
  }
}
```

**Exceptions:** only `PokemonNotFoundError` (from either `get_pokemon` call) and
`TypeNotFoundError` (from `matchup`, via `get_type`) — both already in `execute_tool`'s `except`
tuple. **No change needed to `agent/tools.py`'s exception handling.**

**Tool schema** (new, first multi-parameter-pair schema in this codebase — same style as
existing single-`name_or_id` schemas, just two of them):
```json
{
  "name": "compare_pokemon",
  "description": "Compares two Pokémon by name or National Pokédex number — per-stat differences, base stat totals, and the best type-effectiveness multiplier each side's typing achieves against the other's. Purely deterministic (no simulation): useful for \"which is stronger on paper\" questions.",
  "input_schema": {
    "type": "object",
    "properties": {
      "name_or_id_1": {"type": "string"},
      "name_or_id_2": {"type": "string"}
    },
    "required": ["name_or_id_1", "name_or_id_2"],
    "additionalProperties": false
  }
}
```

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
