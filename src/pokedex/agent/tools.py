import json
from collections.abc import Callable

from anthropic.types import ToolParam

from pokedex.pokemon import service as pokemon_service
from pokedex.pokemon.battle import battle_win_probability
from pokedex.pokemon.comparison import compare_pokemon
from pokedex.pokemon.exceptions import (
    InvalidBattleInputError,
    InvalidComparisonInputError,
    ItemNotFoundError,
    LocationNotFoundError,
    VersionNotFoundError
)
from pokedex.pokemon.games import get_game_info
from pokedex.pokemon.items import get_item
from pokedex.pokemon.locations import get_location_encounters, get_pokemon_locations
from pokedex.pokemon.service import (
    EvolutionTriggerNotFoundError,
    MoveNotFoundError,
    PokemonFormNotFoundError,
    PokemonNotFoundError,
    TypeNotFoundError
)

TOOLS: list[ToolParam] = [
    {
        "name": "get_pokemon",
        "description": "Retrieves data about a specific Pokémon by name or National Pokédex number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {
                    "type": "string"
                }
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_move",
        "description": "Retrieves data about a specific Pokémon move by id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {
                    "type": "string"
                }
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_level_up_moves",
        "description": (
            "Retrieves the level-up moveset for a specific Pokémon by name or "
            "National Pokédex number — which moves it learns by leveling up, and "
            "at what level. Does not include moves learned only by TM, tutor, or "
            "egg (those have no level to report)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {
                    "type": "string"
                }
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_evolution_chain",
        "description": (
            "Retrieves the evolution chain for a specific Pokémon by name or "
            "National Pokédex number — what it evolves into (or from), and under "
            "what conditions (level, item, trade, happiness, etc)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {
                    "type": "string"
                }
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_evolution_trigger",
        "description": (
            "Retrieves data about a specific evolution trigger by name or id "
            "(e.g. level-up, trade, use-item, shed) — what kind of event it is "
            "and which Pokémon species use it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {
                    "type": "string"
                }
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_type",
        "description": (
            "Retrieves data about a specific Pokémon type by name or id — its "
            "damage relations (what it's super effective against, weak to, or "
            "immune to and from)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {
                    "type": "string"
                }
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_pokemon_form",
        "description": (
            "Retrieves data about a specific Pokémon form by name (e.g. 'arceus-fire', "
            "'rotom-heat', 'deoxys-attack', 'charizard-mega-x') — its type(s) and what "
            "triggers it (held item, etc). Use this for alternate/regional/mega forms; "
            "get_pokemon only covers a Pokémon's base/default form."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {
                    "type": "string"
                }
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "compare_pokemon",
        "description": (
            "Compares 2 to 6 Pokémon by name or National Pokédex number, producing a fully "
            "pre-computed summary — pure stat and typing arithmetic, with no battle simulation "
            "(ignores level, moves, abilities, and IVs/EVs). Interpretation guide: `pokemon` lists "
            "each compared Pokémon's identity plus a derived summary — `base_stat_total_rank` "
            "(1 = highest total, ties share a rank), `stats_led` (base stats where this Pokémon is "
            "tied for highest among those compared), `super_effective_against` (other compared "
            "Pokémon this one's typing hits for 2x or more), and `resisted_or_immune_vs` (other "
            "compared Pokémon this one's typing only hits for 0.5x or less, including 0x immunity). "
            "`stat_comparison` has one entry per base stat (hp, attack, defense, special-attack, "
            "special-defense, speed): every compared Pokémon's `value`, `diff_from_highest` (always "
            "<= 0; 0 for whoever leads), and a `highest` list naming whoever is tied for that stat. "
            "`base_stat_total_comparison` is the same shape, summed across all six stats. "
            "`type_matchups` is directional/asymmetric: one entry per ordered (attacker, defender) "
            "pair among the compared Pokémon, with `best_multiplier` — the best type-effectiveness "
            "multiplier the attacker's typing achieves against the defender's typing (2.0 or 4.0 = "
            "advantage, 1.0 = neutral, 0.5 or 0.25 = resisted, 0.0 = immune). If a duplicate "
            "identifier was given (e.g. the same Pokémon by name and by number), it's silently "
            "de-duplicated and a `note` field explains it."
        ),
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
            "additionalProperties": False
        }
    },
    {
        "name": "battle_win_probability",
        "description": (
            "Estimates the win probability between two teams of Pokémon via Monte Carlo "
            "simulation (2000 simulated battles), in either 'singles' (one Pokémon active per "
            "side, the default — omit `format` for a standard 1-vs-1 battle) or 'doubles' (two "
            "Pokémon active per side at once, with spread moves able to hit both active "
            "opponents). Each team is 1-6 Pokémon with independent levels; a fainted Pokémon is "
            "automatically replaced by the next one in its team's list (no voluntary switching). "
            "Uses each Pokémon's own best level-appropriate damaging moves, chosen and re-scored "
            "every turn by type effectiveness — not a fixed moveset. Reports win rate per team, "
            "draw rate, and average turns to decide — a measured rate from simulation, not a "
            "formula-based guess. Simplifications, stated plainly: no abilities, held items, "
            "weather, terrain, or entry hazards; no PP tracking; spread moves never damage an "
            "ally in this simulation even where the real games would; no protect/redirection "
            "moves; no voluntary switching. A best-effort approximation, not a competitive-grade "
            "battle engine."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "team_1": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name_or_id": {"type": "string"},
                            "level": {"type": "integer", "minimum": 1, "maximum": 100}
                        },
                        "required": ["name_or_id", "level"],
                        "additionalProperties": False
                    },
                    "minItems": 1,
                    "maxItems": 6
                },
                "team_2": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name_or_id": {"type": "string"},
                            "level": {"type": "integer", "minimum": 1, "maximum": 100}
                        },
                        "required": ["name_or_id", "level"],
                        "additionalProperties": False
                    },
                    "minItems": 1,
                    "maxItems": 6
                },
                "format": {"type": "string", "enum": ["singles", "doubles"]}
            },
            "required": ["team_1", "team_2"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_game_info",
        "description": (
            "Resolves a game (e.g. 'omega-ruby', 'emerald', 'scarlet') to its version group, "
            "sibling version (the paired game, if any, e.g. 'alpha-sapphire' for 'omega-ruby'), "
            "generation, and region(s) — use this to identify which generation a named game "
            "belongs to, or to get the exact `version` string to pass to get_pokemon_locations / "
            "get_location_encounters. Known gap, stated plainly: this does not yet compute "
            "concrete cross-generation rule differences (e.g. the Fairy type not existing before "
            "Generation VI, or ability/stat changes across generations) — only which generation/"
            "region a game belongs to."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {
                    "type": "string"
                }
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_pokemon_locations",
        "description": (
            "Retrieves where a Pokémon can be found in the wild by name or National Pokédex "
            "number, with a pre-computed encounter-rate %, ranked by frequency. `version` is "
            "optional: pass an exact game (e.g. 'emerald', from get_game_info) for that game's "
            "exact numbers, or omit it to average across every game it's known in (an "
            "approximate frequency signal, not one exact game's number). `most_likely_location` "
            "is the single best repeatable wild-encounter pick; `locations` is the full "
            "breakdown, each with one entry per encounter method (walk/surf/fishing rod/etc, "
            "since different methods are separate, non-comparable encounter tables) giving "
            "`chance_percent`, level range, which games it applies in, and any `conditions` "
            "(e.g. time of day, swarm) — conditions are listed separately, never merged, because "
            "they are mutually exclusive alternatives, not combined probabilities. If this "
            "Pokémon has no repeatable wild encounters at all (only a one-off static/gift "
            "encounter, or none recorded — common for starters, trade-only, or evolution-only "
            "species), `most_likely_location` is omitted and a `note` explains why."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {"type": "string"},
                "version": {"type": "string"}
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_location_encounters",
        "description": (
            "Reverse of get_pokemon_locations: given a location by name (e.g. 'petalburg-woods'), "
            "lists which wild Pokémon appear there and at what pre-computed encounter-rate %, "
            "across every area within that location. Same `version`/`chance_percent`/`conditions` "
            "semantics as get_pokemon_locations — optional `version` for one exact game's "
            "numbers, omit to average across every game; `most_common_pokemon` is the single best "
            "repeatable wild-encounter pick for this location, `areas` is the full breakdown per "
            "area and Pokémon. If nothing repeatable is recorded, `most_common_pokemon` is "
            "omitted and a `note` explains why."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {"type": "string"},
                "version": {"type": "string"}
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_item",
        "description": (
            "Retrieves a Pokémon item's specs by name or id: category, attributes (e.g. "
            "holdable, consumable), fling power/effect, free-text `effect` explaining what it "
            "does, `held_by_pokemon` (which wild Pokémon carry it naturally, with rarity % per "
            "game — a structured 'how to find it via wild encounters' signal), `prices` (shop "
            "buy/sell price per game — often an empty list, since PokeAPI's price data is only "
            "well-populated for some item categories like Poké Balls, not most consumables; an "
            "empty list means 'not recorded', not 'free' or 'unobtainable'), and `machines` "
            "(which games teach a move via this item as a TM/TR, without resolving which move). "
            "PokeAPI has no shop/route-location data at all — 'how to find it' can only be "
            "answered from `held_by_pokemon` and `prices`, never a specific route or town name. "
            "Optionally pass `pokemon_name_or_id` to also get that Pokémon's `types` alongside — "
            "PokeAPI has no structured item-to-type-boost or item-to-evolution-species link, so "
            "when `pokemon` is included, judge the held-item/type synergy yourself by reading "
            "`effect` against `pokemon.types`: the one tool in this Pokédex where you do that "
            "reasoning instead of the tool doing it for you."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_id": {"type": "string"},
                "pokemon_name_or_id": {"type": "string"}
            },
            "required": ["name_or_id"],
            "additionalProperties": False
        },
        "cache_control": {"type": "ephemeral"}
    },
]

_HANDLERS: dict[str, Callable[..., dict]] = {
    "get_pokemon": pokemon_service.get_pokemon,
    "get_move": pokemon_service.get_move,
    "get_level_up_moves": pokemon_service.get_level_up_moves,
    "get_evolution_chain": pokemon_service.get_evolution_chain,
    "get_evolution_trigger": pokemon_service.get_evolution_trigger,
    "get_type": pokemon_service.get_type,
    "get_pokemon_form": pokemon_service.get_pokemon_form,
    "compare_pokemon": compare_pokemon,
    "battle_win_probability": battle_win_probability,
    "get_game_info": get_game_info,
    "get_pokemon_locations": get_pokemon_locations,
    "get_location_encounters": get_location_encounters,
    "get_item": get_item
}


def execute_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}", True

    try:
        result = handler(**tool_input)
    except (
        PokemonNotFoundError,
        MoveNotFoundError,
        EvolutionTriggerNotFoundError,
        TypeNotFoundError,
        PokemonFormNotFoundError,
        InvalidComparisonInputError,
        InvalidBattleInputError,
        VersionNotFoundError,
        LocationNotFoundError,
        ItemNotFoundError
    ) as exc:
        return str(exc), True

    return json.dumps(result), False
