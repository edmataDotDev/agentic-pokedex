from pokedex.pokemon import service as pokemon_service


def get_game_info(name_or_id: str) -> dict:
    """version -> version_group -> generation -> sibling versions -> region(s)."""
    version = pokemon_service.get_version(name_or_id)
    version_group = pokemon_service.get_version_group(version["version_group"])
    generation = pokemon_service.get_generation(version_group["generation"])

    return {
        "version": version["name"],
        "version_group": version_group["name"],
        "sibling_versions": [v for v in version_group["versions"] if v != version["name"]],
        "generation": generation["name"],
        # The game's own version-group regions, not the generation's flagship region — a remake
        # like Omega Ruby is Generation VI (flagship region Kalos) but is itself set in Hoenn.
        "regions": version_group["regions"],
    }
