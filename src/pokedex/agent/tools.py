import json
from collections.abc import Callable

from anthropic.types import ToolParam

from pokedex.pokemon import service as pokemon_service
from pokedex.pokemon.battle import battle_win_probability
from pokedex.pokemon.comparison import compare_pokemon
from pokedex.pokemon.exceptions import InvalidBattleInputError, InvalidComparisonInputError
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
    "battle_win_probability": battle_win_probability
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
        InvalidBattleInputError
    ) as exc:
        return str(exc), True

    return json.dumps(result), False
