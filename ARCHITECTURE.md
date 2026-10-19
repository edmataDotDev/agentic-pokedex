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

**Known live bug:** both `.env` and `.env.example` currently have
`MODEL_NAME=claude-sonnet-5-5` — the extra `-5` is a typo. The correct model ID is
`claude-sonnet-5`. This will make the next real `run_llm_turn` call fail with a
model-not-found error until fixed.

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

## 8. Testing status

- `pokemon/service.py` and `agent/tools.py::execute_tool` were validated with live
  smoke tests against the real PokeAPI (success and not-found cases) — not yet
  automated `pytest` tests, despite `pytest` already being a dev dependency.
- `run_llm_turn` was validated end-to-end with a real multi-round tool-calling
  conversation.
- No automated test suite exists yet.
