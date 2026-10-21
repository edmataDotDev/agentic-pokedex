from pokedex.pokemon import service as pokemon_service


def get_item(name_or_id: str, pokemon_name_or_id: str | None = None) -> dict:
    item = pokemon_service.get_item(name_or_id)

    if pokemon_name_or_id is not None:
        pokemon = pokemon_service.get_pokemon(pokemon_name_or_id)
        item["pokemon"] = {
            "id": pokemon["id"],
            "name": pokemon["name"],
            "types": pokemon["types"],
        }

    return item
