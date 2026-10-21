from collections import defaultdict

from pokedex.pokemon import service as pokemon_service
from pokedex.pokemon.games import get_game_info

NO_POKEMON_ENCOUNTERS_NOTE = (
    "No recorded encounter locations at all — this Pokémon may only be obtainable by evolution, "
    "trade, or a special event in the games checked."
)
NO_LOCATION_ENCOUNTERS_NOTE = (
    "No recorded wild Pokémon encounters at all for this location (or this version, if filtered) "
    "— it may be a town, building, or other area with no wild encounter table."
)
ONLY_ONE_OFF_ENCOUNTERS_NOTE = (
    "Every recorded encounter is a one-off method (e.g. a single static/gift encounter), not a "
    "repeatable wild encounter — see the full breakdown for the exact spot(s)/Pokémon rather "
    "than a single 'most likely'/'most common' pick, which isn't meaningful here."
)

# One-off/static/event methods, confirmed against the live encounter-method list — excluded only
# from the single "most likely"/"most common" shortcut field, never from the full breakdown,
# since a 100%-chance gift encounter would otherwise dominate any ranking by chance alone.
ONE_OFF_METHODS = {
    "gift", "gift-egg", "static", "npc-trade",
    "colosseum-bonus-disc-us", "colosseum-bonus-disc-jpn",
    "pokemon-channel-pal", "pokemon-ranger", "pokemon-battle-revolution",
    "new-york-pokecenter-wish-eggs",
}

def _totals_by_group(encounters: list[dict]) -> dict[tuple[str, frozenset], dict]:
    """One version's raw encounter slots, grouped by (method, condition-combo) and summed.

    Condition values (time-of-day, swarm, etc.) are mutually exclusive alternatives, not
    concurrent probabilities — grouping by their exact combination, not just by method, avoids
    summing across alternatives in a way that could exceed 100%.
    """
    groups: dict[tuple[str, frozenset], dict] = defaultdict(
        lambda: {"chance": 0, "min_level": None, "max_level": None}
    )
    for encounter in encounters:
        key = (encounter["method"], frozenset(encounter["condition_values"]))
        group = groups[key]
        group["chance"] += encounter["chance"]
        group["min_level"] = (
            encounter["min_level"] if group["min_level"] is None
            else min(group["min_level"], encounter["min_level"])
        )
        group["max_level"] = (
            encounter["max_level"] if group["max_level"] is None
            else max(group["max_level"], encounter["max_level"])
        )
    return groups

def _aggregate(versions: list[dict], version_filter: str | None) -> list[dict]:
    """[{"version": .., "encounters": [..]}] -> per-(method, conditions) chance%, averaged across
    versions when no `version_filter` is given."""
    if version_filter is not None:
        versions = [v for v in versions if v["version"] == version_filter]

    aggregated: dict[tuple[str, frozenset], dict] = defaultdict(
        lambda: {"totals": [], "versions": set(), "min_level": None, "max_level": None}
    )

    for entry in versions:
        if not entry["encounters"]:
            continue
        for key, group in _totals_by_group(entry["encounters"]).items():
            target = aggregated[key]
            target["totals"].append(group["chance"])
            target["versions"].add(entry["version"])
            target["min_level"] = (
                group["min_level"] if target["min_level"] is None
                else min(target["min_level"], group["min_level"])
            )
            target["max_level"] = (
                group["max_level"] if target["max_level"] is None
                else max(target["max_level"], group["max_level"])
            )

    results = [
        {
            "method": method,
            "chance_percent": sum(data["totals"]) / len(data["totals"]),
            "min_level": data["min_level"],
            "max_level": data["max_level"],
            "versions": sorted(data["versions"]),
            "conditions": sorted(conditions),
        }
        for (method, conditions), data in aggregated.items()
    ]
    results.sort(key=lambda r: r["chance_percent"], reverse=True)
    return results

def get_pokemon_locations(name_or_id: str, version: str | None = None) -> dict:
    if version is not None:
        get_game_info(version)  # validates early: raises VersionNotFoundError for an unknown game

    pokemon = pokemon_service.get_pokemon(name_or_id)
    encounters = pokemon_service.get_pokemon_location_area(name_or_id)

    locations = []
    for entry in encounters:
        methods = _aggregate(entry["versions"], version)
        if methods:
            locations.append({"location_area": entry["location_area"], "methods": methods})
    locations.sort(key=lambda loc: loc["methods"][0]["chance_percent"], reverse=True)

    result = {
        "pokemon": {"id": pokemon["id"], "name": pokemon["name"]},
        "version_filter": version,
        "locations": locations,
    }

    rankable = [
        (loc["location_area"], method)
        for loc in locations
        for method in loc["methods"]
        if method["method"] not in ONE_OFF_METHODS
    ]
    if rankable:
        best_area, best_method = max(rankable, key=lambda pair: pair[1]["chance_percent"])
        result["most_likely_location"] = {
            "location_area": best_area,
            "method": best_method["method"],
            "chance_percent": best_method["chance_percent"],
            "min_level": best_method["min_level"],
            "max_level": best_method["max_level"],
        }
    elif not locations:
        result["note"] = NO_POKEMON_ENCOUNTERS_NOTE
    else:
        result["note"] = ONLY_ONE_OFF_ENCOUNTERS_NOTE

    return result

def get_location_encounters(name_or_id: str, version: str | None = None) -> dict:
    if version is not None:
        get_game_info(version)

    location = pokemon_service.get_location(name_or_id)

    areas = []
    rankable = []
    for area_name in location["areas"]:
        area = pokemon_service.get_location_area(area_name)
        pokemon_list = []
        for encounter in area["pokemon_encounters"]:
            methods = _aggregate(encounter["versions"], version)
            if not methods:
                continue
            pokemon_list.append({"name": encounter["pokemon"], "methods": methods})
            for method in methods:
                if method["method"] not in ONE_OFF_METHODS:
                    rankable.append((area["name"], encounter["pokemon"], method))
        pokemon_list.sort(key=lambda p: p["methods"][0]["chance_percent"], reverse=True)
        if pokemon_list:
            areas.append({"location_area": area["name"], "pokemon": pokemon_list})

    result = {
        "location": {"name": location["name"], "region": location["region"]},
        "version_filter": version,
        "areas": areas,
    }

    if rankable:
        area_name, pokemon_name, best_method = max(rankable, key=lambda t: t[2]["chance_percent"])
        result["most_common_pokemon"] = {
            "name": pokemon_name,
            "location_area": area_name,
            "method": best_method["method"],
            "chance_percent": best_method["chance_percent"],
        }
    elif not areas:
        result["note"] = NO_LOCATION_ENCOUNTERS_NOTE
    else:
        result["note"] = ONLY_ONE_OFF_ENCOUNTERS_NOTE

    return result
