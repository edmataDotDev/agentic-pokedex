import json

from anthropic.types import ToolParam

from pokedex.pokemon import service as pokemon_service
from pokedex.pokemon.service import MoveNotFoundError, PokemonNotFoundError

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
]

_HANDLERS = {
    "get_pokemon": pokemon_service.get_pokemon,
    "get_move": pokemon_service.get_move,
    "get_level_up_moves": pokemon_service.get_level_up_moves
}


def execute_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}", True

    try:
        result = handler(**tool_input)
    except (PokemonNotFoundError, MoveNotFoundError) as exc:
        return str(exc), True

    return json.dumps(result), False
