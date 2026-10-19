from httpx2 import HTTPStatusError
from pypokeclient import Client


class PokemonNotFoundError(Exception):
    """Raised when a Pokémon cannot be found by name or National Pokédex number."""


_client = Client()


def get_pokemon(name_or_id: str) -> dict:
    try:
        pokemon = _client.get_pokemon(name_or_id)
    except HTTPStatusError as exc:
        raise PokemonNotFoundError(
            f"No Pokémon found with identifier '{name_or_id}'."
        ) from exc

    return {
        "id": pokemon.id,
        "name": pokemon.name,
        "height": pokemon.height,
        "weight": pokemon.weight,
        "base_experience": pokemon.base_experience,
        "types": [t.type.name for t in pokemon.types],
        "abilities": [
            {"name": a.ability.name, "is_hidden": a.is_hidden}
            for a in pokemon.abilities
            if a.ability is not None
        ],
        "stats": [
            {"name": s.stat.name, "base_stat": s.base_stat}
            for s in pokemon.stats
        ],
    }
