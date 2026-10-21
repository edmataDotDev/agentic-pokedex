from httpx2 import HTTPStatusError
from pypokeclient import Client
from pokedex.pokemon.evolution import map_chain_link
from pokedex.pokemon.exceptions import (
    PokemonNotFoundError,
    MoveNotFoundError,
    EvolutionTriggerNotFoundError,
    TypeNotFoundError,
    PokemonFormNotFoundError,
    VersionNotFoundError,
    LocationNotFoundError,
    ItemNotFoundError
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
    # Uses the raw endpoint, not the typed `_client.get_type`, because pypokeclient's `Type`
    # model requires `move_damage_class` to be a resource, but the live API returns `null`
    # there for the Fairy type — same workaround already used by get_move/get_pokemon_form.
    try:
        response = _client._api_request(f"type/{name_or_id}")
    except HTTPStatusError as exc:
        raise TypeNotFoundError(
            f"No Type found with identifier '{name_or_id}'."
        ) from exc

    type_ = response.json()
    relations = type_["damage_relations"]

    return {
        "id": type_["id"],
        "name": type_["name"],
        "double_damage_to": [t["name"] for t in relations["double_damage_to"]],
        "double_damage_from": [t["name"] for t in relations["double_damage_from"]],
        "half_damage_to": [t["name"] for t in relations["half_damage_to"]],
        "half_damage_from": [t["name"] for t in relations["half_damage_from"]],
        "no_damage_to": [t["name"] for t in relations["no_damage_to"]],
        "no_damage_from": [t["name"] for t in relations["no_damage_from"]],
    }

def get_pokemon_form(name_or_id: str) -> dict:
    try:
        response = _client._api_request(f"pokemon-form/{name_or_id}")
    except HTTPStatusError as exc:
        raise PokemonFormNotFoundError(
            f"No Pokémon Form found with identifier '{name_or_id}'."
        ) from exc

    form = response.json()

    return {
        "name": form["name"],
        "pokemon": form["pokemon"]["name"],
        "form_name": form["form_name"],
        "is_default": form["is_default"],
        "is_battle_only": form["is_battle_only"],
        "is_mega": form["is_mega"],
        "types": [t["type"]["name"] for t in form["types"]],
        "trigger_conditions": [
            {"trigger": tc["trigger"], "name": tc["name"]}
            for tc in form.get("trigger_conditions", [])
        ],
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

def get_version(name_or_id: str) -> dict:
    try:
        response = _client._api_request(f"version/{name_or_id}")
    except HTTPStatusError as exc:
        raise VersionNotFoundError(
            f"No Version found with identifier '{name_or_id}'."
        ) from exc

    version = response.json()

    return {
        "id": version["id"],
        "name": version["name"],
        "version_group": version["version_group"]["name"],
    }

def get_version_group(name_or_id: str) -> dict:
    try:
        response = _client._api_request(f"version-group/{name_or_id}")
    except HTTPStatusError as exc:
        raise VersionNotFoundError(
            f"No Version Group found with identifier '{name_or_id}'."
        ) from exc

    version_group = response.json()

    return {
        "id": version_group["id"],
        "name": version_group["name"],
        "generation": version_group["generation"]["name"],
        "versions": [v["name"] for v in version_group["versions"]],
        "regions": [r["name"] for r in version_group["regions"]],
    }

def get_generation(name_or_id: str) -> dict:
    try:
        response = _client._api_request(f"generation/{name_or_id}")
    except HTTPStatusError as exc:
        raise VersionNotFoundError(
            f"No Generation found with identifier '{name_or_id}'."
        ) from exc

    generation = response.json()

    return {
        "id": generation["id"],
        "name": generation["name"],
        "main_region": generation["main_region"]["name"],
    }

def get_location(name_or_id: str) -> dict:
    try:
        response = _client._api_request(f"location/{name_or_id}")
    except HTTPStatusError as exc:
        raise LocationNotFoundError(
            f"No Location found with identifier '{name_or_id}'."
        ) from exc

    location = response.json()

    return {
        "id": location["id"],
        "name": location["name"],
        "region": location["region"]["name"] if location["region"] else None,
        "areas": [a["name"] for a in location["areas"]],
    }

def _map_encounter(encounter: dict) -> dict:
    return {
        "min_level": encounter["min_level"],
        "max_level": encounter["max_level"],
        "chance": encounter["chance"],
        "method": encounter["method"]["name"],
        "condition_values": [c["name"] for c in encounter["condition_values"]],
    }

def _map_version_details(version_details: list[dict]) -> list[dict]:
    return [
        {
            "version": detail["version"]["name"],
            "encounters": [_map_encounter(e) for e in detail["encounter_details"]],
        }
        for detail in version_details
    ]

def get_location_area(name_or_id: str) -> dict:
    try:
        response = _client._api_request(f"location-area/{name_or_id}")
    except HTTPStatusError as exc:
        raise LocationNotFoundError(
            f"No Location Area found with identifier '{name_or_id}'."
        ) from exc

    location_area = response.json()

    return {
        "id": location_area["id"],
        "name": location_area["name"],
        "location": location_area["location"]["name"],
        "pokemon_encounters": [
            {
                "pokemon": pe["pokemon"]["name"],
                "versions": _map_version_details(pe["version_details"]),
            }
            for pe in location_area["pokemon_encounters"]
        ],
    }

def get_pokemon_location_area(name_or_id: str) -> list[dict]:
    try:
        response = _client._api_request(f"pokemon/{name_or_id}/encounters")
    except HTTPStatusError as exc:
        raise PokemonNotFoundError(
            f"No Pokémon found with identifier '{name_or_id}'."
        ) from exc

    encounters = response.json()

    return [
        {
            "location_area": entry["location_area"]["name"],
            "versions": _map_version_details(entry["version_details"]),
        }
        for entry in encounters
    ]

def get_item(name_or_id: str) -> dict:
    try:
        response = _client._api_request(f"item/{name_or_id}")
    except HTTPStatusError as exc:
        raise ItemNotFoundError(
            f"No Item found with identifier '{name_or_id}'."
        ) from exc

    item = response.json()

    result = {
        "id": item["id"],
        "name": item["name"],
        "category": item["category"]["name"],
        "attributes": [a["name"] for a in item["attributes"]],
        "effect": next(
            (e["short_effect"] for e in item["effect_entries"] if e["language"]["name"] == "en"),
            None,
        ),
        "held_by_pokemon": [
            {
                "pokemon": h["pokemon"]["name"],
                "rarity_by_version": [
                    {"version": vd["version"]["name"], "rarity_percent": vd["rarity"]}
                    for vd in h["version_details"]
                ],
            }
            for h in item["held_by_pokemon"]
        ],
        "prices": [
            {
                "version_group": p["version_group"]["name"],
                "purchase_price": p["purchase_price"],
                "sell_price": p["sell_price"],
            }
            for p in item["prices"]
        ],
        "machines": [m["version_group"]["name"] for m in item["machines"]],
    }

    if item["fling_power"] is not None:
        result["fling"] = {
            "power": item["fling_power"],
            "effect": item["fling_effect"]["name"] if item["fling_effect"] else None,
        }

    return result
