from collections.abc import Sequence

from pokedex.pokemon import service as pokemon_service
from pokedex.pokemon.exceptions import InvalidComparisonInputError
from pokedex.pokemon.matchup import best_type_matchup

STATS = ("hp", "attack", "defense", "special-attack", "special-defense", "speed")
MIN_POKEMON = 2
MAX_POKEMON = 6


def compare_pokemon(names_or_ids: Sequence[str]) -> dict:
    if not isinstance(names_or_ids, list):
        raise InvalidComparisonInputError(
            "names_or_ids must be a JSON array of Pokémon names or National Pokédex numbers."
        )
    if len(names_or_ids) < MIN_POKEMON:
        raise InvalidComparisonInputError(
            f"At least {MIN_POKEMON} Pokémon are required to compare, got {len(names_or_ids)}."
        )
    if len(names_or_ids) > MAX_POKEMON:
        raise InvalidComparisonInputError(
            f"At most {MAX_POKEMON} Pokémon can be compared at once, got {len(names_or_ids)}."
        )

    fetched = [pokemon_service.get_pokemon(n) for n in names_or_ids]

    # De-dupe by resolved id — e.g. "pikachu" and "25" are the same Pokémon.
    seen_ids: set[int] = set()
    pokemon_list = []
    for p in fetched:
        if p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            pokemon_list.append(p)

    if len(pokemon_list) < MIN_POKEMON:
        raise InvalidComparisonInputError(
            f"At least {MIN_POKEMON} distinct Pokémon are required after removing duplicates."
        )

    names = [p["name"] for p in pokemon_list]
    stats_by_name = {p["name"]: {s["name"]: s["base_stat"] for s in p["stats"]} for p in pokemon_list}
    types_by_name = {p["name"]: p["types"] for p in pokemon_list}

    stat_comparison = []
    stats_led: dict[str, list[str]] = {name: [] for name in names}
    for stat in STATS:
        entries = [{"name": n, "value": stats_by_name[n][stat]} for n in names]
        top = max(e["value"] for e in entries)
        for e in entries:
            e["diff_from_highest"] = e["value"] - top
        highest = [e["name"] for e in entries if e["value"] == top]
        for n in highest:
            stats_led[n].append(stat)
        stat_comparison.append({"stat": stat, "entries": entries, "highest": highest})

    totals = {n: sum(stats_by_name[n].values()) for n in names}
    bst_entries = [{"name": n, "value": totals[n]} for n in names]
    top_total = max(e["value"] for e in bst_entries)
    for e in bst_entries:
        e["diff_from_highest"] = e["value"] - top_total
    base_stat_total_comparison = {
        "entries": bst_entries,
        "highest": [e["name"] for e in bst_entries if e["value"] == top_total],
    }
    ranks = {v: i + 1 for i, v in enumerate(sorted(set(totals.values()), reverse=True))}

    type_matchups = []
    super_effective_against: dict[str, list[str]] = {n: [] for n in names}
    resisted_or_immune_vs: dict[str, list[str]] = {n: [] for n in names}
    for attacker in names:
        for defender in names:
            if attacker == defender:
                continue
            multiplier = best_type_matchup(types_by_name[attacker], types_by_name[defender])
            type_matchups.append(
                {"attacker": attacker, "defender": defender, "best_multiplier": multiplier}
            )
            if multiplier >= 2.0:
                super_effective_against[attacker].append(defender)
            elif multiplier <= 0.5:
                resisted_or_immune_vs[attacker].append(defender)

    pokemon_summaries = [
        {
            "id": p["id"],
            "name": p["name"],
            "types": types_by_name[p["name"]],
            "base_stat_total": totals[p["name"]],
            "base_stat_total_rank": ranks[totals[p["name"]]],
            "stats_led": stats_led[p["name"]],
            "super_effective_against": super_effective_against[p["name"]],
            "resisted_or_immune_vs": resisted_or_immune_vs[p["name"]],
        }
        for p in pokemon_list
    ]

    result = {
        "pokemon": pokemon_summaries,
        "stat_comparison": stat_comparison,
        "base_stat_total_comparison": base_stat_total_comparison,
        "type_matchups": type_matchups,
    }
    if len(pokemon_list) != len(fetched):
        result["note"] = (
            f"{len(fetched) - len(pokemon_list)} duplicate identifier(s) referring to a Pokémon "
            "already in the list were removed before comparing."
        )
    return result
