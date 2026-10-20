import json

from anthropic.types import ToolParam

from pokedex.pokemon import service as pokemon_service
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
        },
        "cache_control": {"type": "ephemeral"}
    },
]

_HANDLERS = {
    "get_pokemon": pokemon_service.get_pokemon,
    "get_move": pokemon_service.get_move,
    "get_level_up_moves": pokemon_service.get_level_up_moves,
    "get_evolution_chain": pokemon_service.get_evolution_chain,
    "get_evolution_trigger": pokemon_service.get_evolution_trigger,
    "get_type": pokemon_service.get_type,
    "get_pokemon_form": pokemon_service.get_pokemon_form
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
        PokemonFormNotFoundError
    ) as exc:
        return str(exc), True

    return json.dumps(result), False
