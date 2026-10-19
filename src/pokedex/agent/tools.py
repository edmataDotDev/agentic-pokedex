import json

from pokedex.pokemon import service as pokemon_service
from pokedex.pokemon.service import PokemonNotFoundError

TOOLS = [
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
    }
]

_HANDLERS = {
    "get_pokemon": lambda _: None
}


def execute_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}", True

    try:
        result = handler(**tool_input)
    except PokemonNotFoundError as exc:
        return str(exc), True

    return json.dumps(result), False
