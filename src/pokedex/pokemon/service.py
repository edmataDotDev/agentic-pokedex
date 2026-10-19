from httpx2 import HTTPStatusError
from pypokeclient import Client
from pokedex.pokemon.exceptions import (
    PokemonNotFoundError,
    MoveNotFoundError
)


_client = Client()

def get_move(name_or_id: str) -> dict:
    try:
        response = _client._api_request(f"move/{name_or_id}")
    except HTTPStatusError as exc:
        raise MoveNotFoundError(
            f"No Move found with identifier '{name_or_id}'."
        ) from exc

    move = response.json()
    meta = move["meta"]

    result = {
        "id": move["id"],
        "name": move["name"],
        "type": move["type"]["name"],
        "damage_class": move["damage_class"]["name"],
        "power": move["power"],
        "accuracy": move["accuracy"],
        "pp": move["pp"],
        "priority": move["priority"],
        "target": move["target"]["name"],
        "generation": move["generation"]["name"],
        "effect": next(
            (e["short_effect"] for e in move["effect_entries"] if e["language"]["name"] == "en"),
            None,
        ),
    }

    if move["effect_chance"] is not None:
        result["effect_chance"] = move["effect_chance"]

    # Most moves have no secondary effect, so most of these sub-fields are 0/"none"
    # for most moves — including them unconditionally for every move would mean
    # paying tokens, on every single lookup, to say "this doesn't apply." Only
    # report a sub-field when it actually says something.
    if meta is not None:
        move_meta = {"category": meta["category"]["name"]}
        if meta["ailment"]["name"] != "none":
            move_meta["ailment"] = meta["ailment"]["name"]
        if meta["ailment_chance"]:
            move_meta["ailment_chance"] = meta["ailment_chance"]
        if meta["drain"]:
            move_meta["drain"] = meta["drain"]
        if meta["healing"]:
            move_meta["healing"] = meta["healing"]
        if meta["crit_rate"]:
            move_meta["crit_rate"] = meta["crit_rate"]
        if meta["flinch_chance"]:
            move_meta["flinch_chance"] = meta["flinch_chance"]
        if meta["stat_chance"]:
            move_meta["stat_chance"] = meta["stat_chance"]
        result["meta"] = move_meta

    return result

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
