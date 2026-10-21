from collections.abc import Sequence

from pokedex.pokemon import service as pokemon_service


def type_effectiveness(attacking_type: str, defending_types: Sequence[str]) -> float:
    """Multiplier of a hit of `attacking_type` against a (possibly dual-typed) defender."""
    type_ = pokemon_service.get_type(attacking_type)

    multiplier = 1.0
    for defending_type in defending_types:
        if defending_type in type_["no_damage_to"]:
            multiplier *= 0.0
        elif defending_type in type_["double_damage_to"]:
            multiplier *= 2.0
        elif defending_type in type_["half_damage_to"]:
            multiplier *= 0.5

    return multiplier

def best_type_matchup(attacking_types: Sequence[str], defending_types: Sequence[str]) -> float:
    """Best multiplier any of `attacking_types` achieves against `defending_types`."""
    return max(type_effectiveness(t, defending_types) for t in attacking_types)
