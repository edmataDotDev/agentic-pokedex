from httpx2 import HTTPStatusError
from pypokeclient import Client
from pokedex.pokemon.evolution import map_chain_link
from pokedex.pokemon.exceptions import (
    PokemonNotFoundError,
    MoveNotFoundError,
    EvolutionTriggerNotFoundError,
    TypeNotFoundError
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

def get_level_up_moves(name_or_id: str) -> dict:
    try:
        pokemon = _client.get_pokemon(name_or_id)
    except HTTPStatusError as exc:
        raise PokemonNotFoundError(
            f"No Pokémon found with identifier '{name_or_id}'."
        ) from exc

    level_up_moves = []
    for move in pokemon.moves:
        levels = [
            detail.level_learned_at
            for detail in move.version_group_details
            if detail.move_learn_method.name == "level-up"
        ]
        if levels:
            level_up_moves.append({"name": move.move.name, "level": min(levels)})

    level_up_moves.sort(key=lambda m: m["level"])

    return {
        "id": pokemon.id,
        "name": pokemon.name,
        "level_up_moves": level_up_moves,
    }

def get_evolution_chain(name_or_id: str) -> dict:
    try:
        species = _client.get_pokemon_species(name_or_id)
    except HTTPStatusError as exc:
        raise PokemonNotFoundError(
            f"No Pokémon found with identifier '{name_or_id}'."
        ) from exc

    chain_id = int(species.evolution_chain.url.rstrip("/").rsplit("/", 1)[-1])
    chain = _client.get_evolution_chain(chain_id)

    return map_chain_link(chain.chain)

def get_evolution_trigger(name_or_id: str) -> dict:
    try:
        trigger = _client.get_evolution_trigger(name_or_id)
    except HTTPStatusError as exc:
        raise EvolutionTriggerNotFoundError(
            f"No Evolution Trigger found with identifier '{name_or_id}'."
        ) from exc

    return {
        "id": trigger.id,
        "name": trigger.name,
        "pokemon_species": [s.name for s in trigger.pokemon_species],
    }

def get_type(name_or_id: str) -> dict:
    try:
        type_ = _client.get_type(name_or_id)
    except HTTPStatusError as exc:
        raise TypeNotFoundError(
            f"No Type found with identifier '{name_or_id}'."
        ) from exc

    relations = type_.damage_relations

    return {
        "id": type_.id,
        "name": type_.name,
        "double_damage_to": [t.name for t in relations.double_damage_to],
        "double_damage_from": [t.name for t in relations.double_damage_from],
        "half_damage_to": [t.name for t in relations.half_damage_to],
        "half_damage_from": [t.name for t in relations.half_damage_from],
        "no_damage_to": [t.name for t in relations.no_damage_to],
        "no_damage_from": [t.name for t in relations.no_damage_from],
    }

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
