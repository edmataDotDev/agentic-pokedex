# Production readiness — pending work

Tracking doc for what's left before this agent is production-ready. Not prioritized/ordered —
pick off items as they make sense. Update as items are resolved or new gaps are found.

## 1. Behavior & prompting

- [ ] **Response formatting guidance.** `display_message` already renders Markdown via Rich
  (cli/service.py), but the *content* format (when to use tables vs. prose, how verbose to be)
  isn't steered anywhere — it's whatever the model defaults to. Worth adding explicit guidance to
  `SYSTEM_PROMPT` if a consistent shape matters.
- [ ] **"Skills"-style modular behavior.** Open design question (see chat) — nothing like this
  exists yet. Would mean designing how additional instruction blocks get composed into/alongside
  `SYSTEM_PROMPT`, not a PokeAPI concern. Needs its own design pass before implementing.
- [ ] **Tool-use guidance in the prompt.** E.g. Lucario triggered `get_pokemon` +
  `get_evolution_chain` + `get_level_up_moves` + `get_type` ×2 in one turn — fine, but worth
  deciding if that's the behavior we want for simple questions (cost/latency vs. thoroughness).

## 2. Token / JSON optimization

- [x] `get_move` — trimmed (meta sub-fields, `effect_chance`) to drop zero/no-op values.
- [x] `get_evolution_chain` — conditions reduced to `is_default` only, ~25 possible fields
  collapsed to only the ones that apply.
- [ ] **Generic compaction layer** (`agent/compact.py`, not created) — a single `compact()`
  function applied at the `execute_tool` serialization boundary that generalizes the
  null/empty-field-dropping technique above to every tool, instead of re-deriving it by hand per
  service. Full spec, including why format swaps (YAML/TOON) and key-shortening were researched
  and rejected: see **ARCHITECTURE.md §11**.
- [ ] **Audit remaining services** (`get_pokemon`, `get_level_up_moves`, `get_type`,
  `get_evolution_trigger`) for the same treatment — haven't been reviewed with the same
  token-cost lens as `get_move`/evolution. Partly superseded by the generic layer above once
  built (it only needs manual trimming for domain-specific noise it can't infer, e.g.
  `required_pokemon_form` below).
- [ ] **Large list guarding.** `get_evolution_trigger`/`get_type` return full species/type lists
  from PokeAPI — fine for now (max ~30 items observed), but no cap exists if a future
  endpoint returns something much larger (e.g. a `machine` or `use-item` trigger's species list).
- [ ] **`required_pokemon_form` noise.** Shows up on every eeveelution condition (always
  `"eevee"`) — mildly redundant; decide if it's worth suppressing when it just repeats the base
  species name.

## 3. Known architecture gaps (already called out in ARCHITECTURE.md)

- [ ] `config.py`: duplicate model fields — `model` (unused, default `"claude-sonnet-5"`) vs.
  `model_name` (required, actually used). Consolidate into one.
- [ ] `max_tool_retry` setting exists in `Settings` but is **never read anywhere in the code**.
  Design already specified (ARCHITECTURE.md §7): track consecutive failures of the same tool call
  (same name + args), keyed per tool; once `max_tool_retry` is hit, reject further identical
  attempts with a synthetic error `tool_result`, before touching the real service.
- [ ] `cli/` has an explicit `__init__.py`; `agent/`/`pokemon/` don't (implicit namespace
  packages). Pick one convention.
- [ ] Style nits never applied: `isUserTurn` (camelCase, rest of codebase is snake_case),
  `answer == None` / `answer != None` (should be `is None` / `is not None`) in
  `agent_loop`.

## 4. Robustness / error handling

- [ ] **No handling for Anthropic API failures.** `client.messages.create(...)` in
  `run_llm_turn` has zero error handling — `RateLimitError`, `APIConnectionError`,
  `APIStatusError` (5xx), `APITimeoutError` will all crash the whole CLI with a raw traceback.
  The SDK's own docs show a typed-exception chain to catch; none of it exists here yet.
- [ ] **No handling for PokeAPI network failures.** `pokemon/service.py` only catches
  `HTTPStatusError` (4xx/5xx *with a response*) — a connection drop, DNS failure, or timeout
  from `httpx2` would raise uncaught and propagate past `execute_tool`'s `try/except`, breaking
  the documented "tools never raise" contract (ARCHITECTURE.md §5).
- [ ] **Audit other `pypokeclient` typed models for the same bug class as `get_move`.**
  Confirmed: `Move`/`PastMoveStatValues` has non-nullable `int` fields that PokeAPI sends as
  `null` for some entries (see `PYPOKECLIENT_BUG.md`), fixed by bypassing the typed model.
  Only spot-tested happy paths for `Pokemon`, `PokemonSpecies`, `EvolutionChain`, `Type`,
  `EvolutionTrigger` — haven't systematically checked for the same class of bug on edge-case
  data (e.g. very old Pokémon/moves/forms with sparse historical data).
- [ ] **`refusal` stop_reason gets generic handling.** Currently falls into the same `case _:`
  as `max_tokens`/etc., showing `stop_reason: refusal` — might want this to surface
  `response.stop_details.category`/`.explanation` specifically, since it's a meaningfully
  different situation (the model declined, not that it ran out of room).

## 5. UX

- [ ] **No way to exit the chat loop** except `Ctrl+C`. `agent_loop`'s `while True` has no
  `exit`/`salir` command and no `return` path, despite `agent_loop() -> MessageHistory`
  claiming to return one (ARCHITECTURE.md gap, noted earlier in chat, never implemented).
- [ ] **No conversation persistence.** `MessageHistory` is in-memory only — closing the CLI
  loses everything. Decide if that's acceptable for v1 or needs saving to disk.

## 6. Testing & CI

- [ ] **Zero automated tests exist.** `pytest` is a declared dev dependency with no test files
  (confirmed). Everything so far has been validated via live smoke tests against the real APIs,
  not captured as regression tests.
- [ ] No CI pipeline (lint/type-check/test on push) — depends on whether/how this gets shared
  or deployed.

## 7. Docs

- [ ] `README.md` is empty (0 lines) — no install/run instructions for anyone other than us.
- [x] `PYPOKECLIENT_BUG.md` — documents the `get_move` library bug; consider filing it
  upstream (repo: github.com/RistoAle97/pokeapi-python-wrapper/issues).

## 8. Evals

Different from unit tests: measures *model behavior quality*, not code correctness — does the
agent call the right tool, stay grounded in tool data instead of hallucinating, give a reasonable
answer, across a set of real prompts run against the live model.

- [ ] No eval set exists. Needs: a set of representative questions (simple lookup, comparison,
  evolution/type reasoning, edge cases like unknown Pokémon) with expected tool call(s) and/or
  expected answer content, run automatically against the real model, graded (exact match, rubric,
  or LLM-judge) — costs real money per run, same consent rule as any other live call.
- [ ] No regression safety net — e.g. nothing would catch if a future system-prompt or tool
  change makes the agent start hallucinating stats instead of calling `get_pokemon`.

## 9. Observability & cost control

- [ ] **No logging.** Nothing is written to a file/log — if this runs unattended or something
  goes wrong after the fact, there's no record (tool calls made, errors, latencies).
- [ ] **No hard spend limit.** `display_usage` shows a running cost total but nothing stops the
  session if it crosses a threshold — purely informational, not a guardrail.
- [ ] **No awareness of model deprecation.** We already found Anthropic publishes a
  model-deprecation/migration schedule; nothing here tracks whether `MODEL_NAME` is approaching
  retirement or whether a breaking API change (like the `temperature` removal we hit) needs
  action.

## 10. Caching & PokeAPI etiquette

- [ ] **No caching layer.** `pypokeclient.Client()` supports a `hishel` caching HTTP client as a
  constructor arg (seen in `_api_request`'s docstring) but `pokemon/service.py` doesn't configure
  one — every lookup re-fetches from PokeAPI even for data that never changes (a Pokémon's base
  stats, a move's effect). PokeAPI's own docs ask for "fair use" even though they don't rate-limit.
- [ ] No in-process de-dupe either — asking about the same Pokémon twice in one session refetches
  it in full both times.

## 11. Security / safety

- [ ] **Tool results are trusted verbatim.** PokeAPI is read-only and low-risk, but `tool_result`
  content is fed back to the model unfiltered — worth a conscious note that this assumes PokeAPI
  stays a trusted source, not a general "fetch arbitrary external content" pattern.
- [ ] No input validation/length limits on what the user types before it's sent as a message — low
  risk today (no destructive actions exist), but worth revisiting if tools ever gain side effects.

## 12. Deployment & distribution

- [ ] **Undefined target.** "Production" hasn't been scoped — is this: (a) a polished personal
  CLI tool, (b) something installable by others (PyPI package), or (c) something packaged
  further (Docker, binary)? Affects most of the other sections' priority.
- [ ] No LICENSE file — matters if (b)/(c) above.
- [ ] `Prompt.ask`/Rich assume an interactive TTY — untested behavior if ever run
  non-interactively (piped input, CI, etc.).

## 13. Guardrails (abuse / misuse prevention)

- [ ] Tool-retry circuit breaker (§3) — prevents the agent from looping on a failing call
  indefinitely; also a cost guardrail.
- [ ] **On-topic scope enforcement.** Nothing in `SYSTEM_PROMPT` currently tells the model to
  decline requests outside the Pokédex domain (e.g. unrelated tasks, attempts to extract the
  system prompt, roleplay/jailbreak attempts). Needs a definition of what counts as "indebido"
  for this agent before writing the instruction.
- [ ] **Hard spend/usage cap per session.** Ties to §9's "no hard spend limit" — decide on a
  concrete cap (dollars, tokens, or turns) and what happens when it's hit (warn vs. stop).
- [ ] **Prompt-injection defense-in-depth.** Tool results come from PokeAPI (trusted, read-only),
  so risk is low today, but no explicit instruction tells the model to treat tool_result content
  as data, not instructions — worth adding even as a cheap safeguard.
- [ ] **Input length limit on user messages.** Nothing caps how long a single user turn can be
  before it's sent — a very long paste could balloon cost in one shot.
- [ ] **Turn limit per session.** No cap on how many user↔model exchanges a session allows,
  independent of dollar cost — protects against very long conversations, not just tool loops.
- [ ] **Tool-call round limit per turn.** The retry circuit breaker (§3) only guards against the
  *same* call repeated — nothing stops the model from chaining many *different* tool calls in one
  turn (Lucario already triggered 5). A cap on rounds per turn would be a distinct guardrail.
- [ ] **Input validation before calling a tool.** E.g. reject an empty or absurdly long
  `name_or_id` before it ever reaches PokeAPI — cheap to check, saves a wasted network round-trip.
- [ ] **Client-side rate limiting toward PokeAPI.** PokeAPI doesn't enforce one, but a self-imposed
  throttle (e.g. max N requests/second) is good citizenship and protects against it changing policy
  later.
- [ ] **Logging/audit trail of what's asked.** Doesn't block anything by itself, but without a
  record there's no way to notice abuse patterns after the fact (ties to §9).
- [ ] **Generic user-facing errors for internal failures.** Avoid surfacing raw
  tracebacks/implementation details to the user if something breaks — matters less for a personal
  CLI than for anything multi-user, but worth deciding the stance.

## 14. Battle win-probability & deterministic compare — both implemented

Full spec (level→stat conversion, move-sampling bound, damage formula, return shapes, exact tool
schemas, and the shared `pokemon/matchup.py` type-effectiveness helper): see **ARCHITECTURE.md
§10**. Both tools ended up generalized beyond their original fixed-pair/fixed-1v1 scope.

- [x] **Battle win-probability tool** (`pokemon/battle.py`) — Monte Carlo simulation (2000
  battles) of **team** battles, 1–6 Pokémon per side, `singles` or `doubles` format (generalized
  beyond the original fixed 1-vs-1 spec), using each active Pokémon's best level-appropriate
  damaging move, re-scored live every turn. Spec: ARCHITECTURE.md §10.3.
- [x] **Deterministic compare tool** (`pokemon/comparison.py`) — per-stat diff + totals between
  2–6 Pokémon (generalized beyond the original two-Pokémon spec), plus directional type
  effectiveness for every pair. Spec: ARCHITECTURE.md §10.2.
- [x] Both have `TOOLS`/`_HANDLERS` entries in `agent/tools.py`. Both **did** need an addition to
  `execute_tool`'s exception tuple, contrary to each one's original spec: `compare_pokemon` added
  `InvalidComparisonInputError`, `battle_win_probability` added `InvalidBattleInputError`.
- [x] Building the battle tool's type-effectiveness chart surfaced and fixed a live, pre-existing
  bug in `pokemon_service.get_type`: the typed `pypokeclient` client crashes on the Fairy type
  (`move_damage_class` is `null` in the real API response, which its model doesn't allow),
  silently breaking `compare_pokemon`/`matchup.py` for any Fairy-type Pokémon. Fixed by switching
  to the same raw-JSON `_api_request` pattern `get_move`/`get_pokemon_form` already use. See
  ARCHITECTURE.md §10.4.
- [x] A second move-scoring bug surfaced only once a battle involved a guaranteed-hit move (e.g.
  Swift, Aerial Ace): `move["accuracy"]` can be `null` in the real API (meaning "never misses"),
  but the code divided it by 100 unconditionally — crashed the whole CLI the first time a real
  battle used one. Fixed by treating `None` accuracy as 100 everywhere it's read.

## 15. Games, Locations, Items — all implemented

Spec: ARCHITECTURE.md §12 (games), §13 (locations), §14 (items).

- [x] **Games/versions** (`pokemon/games.py`) — `get_game_info` resolves a game name to its
  version group, sibling version, generation, and region(s). Known gap, stated in the tool
  description: does not yet surface cross-generation rule differences (`past_types`/
  `past_abilities`/`past_stats`/`past_damage_relations`/`past_values`), per the user's explicit
  decision not to retrofit existing tools with version-group filtering in this pass.
- [x] **Locations** (`pokemon/locations.py`) — `get_pokemon_locations` (forward) and
  `get_location_encounters` (reverse), both with an optional `version` (aggregates/averages
  across every game when omitted, per the user's explicit choice). Aggregation groups by
  `(method, condition-combo)`, live-verified on Zubat and Hoothoot to never exceed 100% in any
  group, and never collapses mutually-exclusive conditions (time-of-day, swarm) into one number.
- [x] **Items** (`pokemon/items.py`) — `get_item`, optionally joined with a Pokémon's types. Per
  the user's explicit choice, no hardcoded item→type-boost table: the model reads `effect`
  against `pokemon.types` itself when both are present — the one deliberate exception to this
  project's "tool pre-computes" philosophy. `prices` confirmed frequently empty even for
  purchasable items (PokeAPI data gap, not a bug) — tool description says so explicitly.
- [x] All four new `service.py` functions (`get_version`/`get_version_group`/`get_generation`,
  `get_location`/`get_location_area`/`get_pokemon_location_area`, `get_item`) use the raw-JSON
  `_api_request` pattern, not the typed `pypokeclient` client methods — a deliberate choice given
  the Fairy-type bug already found in `get_type` (§10.4), to avoid hitting more typed-model
  validation crashes on fields the real API can return as `null`.
- [x] All four needed one new typed exception each (`VersionNotFoundError`,
  `LocationNotFoundError`, `ItemNotFoundError`, reusing `PokemonNotFoundError` where a 404
  genuinely means a bad Pokémon identifier rather than a bad location one) — all added to
  `execute_tool`'s exception tuple alongside the `TOOLS`/`_HANDLERS` entries.
- [x] A real logic bug surfaced and fixed during implementation: the first draft's "no
  encounters" note fired even when a Pokémon had one real (but one-off, e.g. static/gift)
  encounter recorded — self-contradictory alongside a non-empty result. Fixed with two distinct
  notes (truly-empty vs. only-one-off-methods-recorded). See ARCHITECTURE.md §13.
