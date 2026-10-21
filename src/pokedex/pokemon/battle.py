import math
import random
from collections.abc import Sequence

from pokedex.pokemon import service as pokemon_service
from pokedex.pokemon.exceptions import InvalidBattleInputError

SIMULATIONS = 2000
MAX_TURNS = 100
MIN_TEAM_SIZE = 1
MAX_TEAM_SIZE = 6
MAX_ACTIVE = {"singles": 1, "doubles": 2}
SPREAD_MODIFIER = 0.75

STRUGGLE_FALLBACK = {
    "name": "struggle", "power": 50, "accuracy": 100,
    "type": "normal", "damage_class": "physical", "target": "selected-pokemon",
}

# Hasn't changed since Generation VI; treated as a fixed domain fact, not fetched from the API.
ALL_TYPES = (
    "normal", "fire", "water", "electric", "grass", "ice", "fighting", "poison",
    "ground", "flying", "psychic", "bug", "rock", "ghost", "dragon", "dark",
    "steel", "fairy",
)

SPREAD_MOVE_TARGETS = {"all-opponents", "all-other-pokemon", "entire-field"}


def _build_type_chart() -> dict[str, dict[str, float]]:
    """attacker type -> defender type -> multiplier, fetched once per battle (18 calls total)."""
    chart: dict[str, dict[str, float]] = {}
    for attacking_type in ALL_TYPES:
        relations = pokemon_service.get_type(attacking_type)
        chart[attacking_type] = {}
        for defending_type in ALL_TYPES:
            if defending_type in relations["no_damage_to"]:
                chart[attacking_type][defending_type] = 0.0
            elif defending_type in relations["double_damage_to"]:
                chart[attacking_type][defending_type] = 2.0
            elif defending_type in relations["half_damage_to"]:
                chart[attacking_type][defending_type] = 0.5
            else:
                chart[attacking_type][defending_type] = 1.0
    return chart

def _type_effectiveness(chart: dict[str, dict[str, float]], attacking_type: str, defending_types: Sequence[str]) -> float:
    multiplier = 1.0
    for defending_type in defending_types:
        multiplier *= chart[attacking_type][defending_type]
    return multiplier

def _best_type_matchup(chart: dict[str, dict[str, float]], attacking_types: Sequence[str], defending_types: Sequence[str]) -> float:
    return max(_type_effectiveness(chart, t, defending_types) for t in attacking_types)

def _validate_team(team: object, label: str) -> list[dict]:
    if not isinstance(team, list):
        raise InvalidBattleInputError(f"{label} must be a JSON array of team members.")
    if not (MIN_TEAM_SIZE <= len(team) <= MAX_TEAM_SIZE):
        raise InvalidBattleInputError(
            f"{label} must have between {MIN_TEAM_SIZE} and {MAX_TEAM_SIZE} Pokémon, got {len(team)}."
        )

    validated = []
    for i, member in enumerate(team):
        if not isinstance(member, dict):
            raise InvalidBattleInputError(f"{label}[{i}] must be an object with name_or_id and level.")
        name_or_id = member.get("name_or_id")
        level = member.get("level")
        if not isinstance(name_or_id, str) or not name_or_id:
            raise InvalidBattleInputError(f"{label}[{i}].name_or_id must be a non-empty string.")
        if not isinstance(level, int) or isinstance(level, bool):
            raise InvalidBattleInputError(f"{label}[{i}].level must be an integer.")
        validated.append({"name_or_id": name_or_id, "level": level})
    return validated

def _convert_stats(base_stats: dict[str, int], level: int) -> dict[str, int]:
    stats = {}
    for name, base in base_stats.items():
        if name == "hp":
            stats[name] = math.floor(2 * base * level / 100) + level + 10
        else:
            stats[name] = math.floor(2 * base * level / 100) + 5
    return stats

def _candidate_moves(name_or_id: str, level: int) -> tuple[list[dict], bool]:
    """Returns (moves, used_fallback). Highest-level 6 damaging level-up moves known by `level`."""
    moveset = pokemon_service.get_level_up_moves(name_or_id)
    learnable = sorted(
        (m for m in moveset["level_up_moves"] if m["level"] <= level),
        key=lambda m: m["level"],
        reverse=True,
    )[:6]

    moves = []
    for candidate in learnable:
        move = pokemon_service.get_move(candidate["name"])
        if move["damage_class"] == "status" or move["power"] is None:
            continue
        moves.append(move)

    if not moves:
        return [dict(STRUGGLE_FALLBACK)], True
    return moves, False

def _build_member(name_or_id: str, level: int) -> tuple[dict, bool]:
    pokemon = pokemon_service.get_pokemon(name_or_id)
    clamped_level = max(1, min(100, level))
    base_stats = {s["name"]: s["base_stat"] for s in pokemon["stats"]}
    stats = _convert_stats(base_stats, clamped_level)
    moves, used_fallback = _candidate_moves(name_or_id, clamped_level)

    member = {
        "id": pokemon["id"],
        "name": pokemon["name"],
        "types": pokemon["types"],
        "level": clamped_level,
        "stats": stats,
        "moves": moves,
    }
    return member, used_fallback

def _choose_action(chart: dict[str, dict[str, float]], attacker: dict, live_opponents: list[dict]) -> dict:
    best = None
    for move in attacker["moves"]:
        stab = 1.5 if move["type"] in attacker["types"] else 1.0
        # A null `accuracy` means the move never misses (e.g. Swift, Aerial Ace) — not a missing value.
        accuracy = move["accuracy"] if move["accuracy"] is not None else 100
        is_spread = move["target"] in SPREAD_MOVE_TARGETS and len(live_opponents) >= 2

        if is_spread:
            targets = live_opponents
            effectiveness = sum(_best_type_matchup(chart, [move["type"]], t["types"]) for t in targets)
            score = move["power"] * (accuracy / 100) * stab * SPREAD_MODIFIER * effectiveness
        else:
            target = min(
                live_opponents,
                key=lambda opp: (
                    -_best_type_matchup(chart, [move["type"]], opp["types"]),
                    opp["current_hp"],
                    opp["slot_index"],
                ),
            )
            targets = [target]
            effectiveness = _best_type_matchup(chart, [move["type"]], target["types"])
            score = move["power"] * (accuracy / 100) * stab * effectiveness

        if best is None or score > best["score"]:
            best = {"move": move, "targets": targets, "is_spread": is_spread, "score": score}

    assert best is not None  # attacker["moves"] is never empty (Struggle fallback guarantees it)
    return best

def _resolve_damage(chart: dict[str, dict[str, float]], attacker: dict, move: dict, target: dict, rng: random.Random, spread: bool) -> None:
    accuracy = move["accuracy"] if move["accuracy"] is not None else 100
    if rng.random() > accuracy / 100:
        return

    atk_stat, def_stat = (
        ("attack", "defense") if move["damage_class"] == "physical" else ("special-attack", "special-defense")
    )
    stab = 1.5 if move["type"] in attacker["types"] else 1.0
    effectiveness = _best_type_matchup(chart, [move["type"]], target["types"])
    roll = rng.uniform(0.85, 1.0)
    spread_mult = SPREAD_MODIFIER if spread else 1.0

    damage = math.floor(
        (2 * attacker["level"] / 5 + 2) * move["power"] * attacker["stats"][atk_stat] / target["stats"][def_stat] / 50 + 2
    ) * stab * effectiveness * roll * spread_mult

    target["current_hp"] = max(0.0, target["current_hp"] - damage)
    if target["current_hp"] <= 0:
        target["fainted"] = True

def _run_single_battle(
    team_1_static: list[dict],
    team_2_static: list[dict],
    format_: str,
    chart: dict[str, dict[str, float]],
    rng: random.Random,
) -> tuple[str, int]:
    max_active = MAX_ACTIVE[format_]
    state_1 = [
        {**m, "current_hp": float(m["stats"]["hp"]), "fainted": False, "slot_index": i}
        for i, m in enumerate(team_1_static)
    ]
    state_2 = [
        {**m, "current_hp": float(m["stats"]["hp"]), "fainted": False, "slot_index": i}
        for i, m in enumerate(team_2_static)
    ]

    turn_count = 0
    while True:
        non_fainted_1 = [m for m in state_1 if not m["fainted"]]
        non_fainted_2 = [m for m in state_2 if not m["fainted"]]

        if not non_fainted_1 and not non_fainted_2:
            return "draw", turn_count
        if not non_fainted_1:
            return "team_2", turn_count
        if not non_fainted_2:
            return "team_1", turn_count
        if turn_count >= MAX_TURNS:
            return "draw", turn_count

        active_1 = non_fainted_1[:max_active]
        active_2 = non_fainted_2[:max_active]

        actions = []
        for attacker in active_1:
            action = _choose_action(chart, attacker, active_2)
            actions.append({"side": "team_1", "attacker": attacker, **action})
        for attacker in active_2:
            action = _choose_action(chart, attacker, active_1)
            actions.append({"side": "team_2", "attacker": attacker, **action})

        actions.sort(key=lambda a: (-a["attacker"]["stats"]["speed"], rng.random()))

        for action in actions:
            attacker = action["attacker"]
            if attacker["fainted"]:
                continue

            opponents = state_2 if action["side"] == "team_1" else state_1
            live_targets = [t for t in action["targets"] if not t["fainted"]]

            if not live_targets:
                if action["is_spread"]:
                    continue
                remaining = [o for o in opponents if not o["fainted"]]
                live_targets = remaining[:1]
                if not live_targets:
                    continue

            spread = action["is_spread"] and len(live_targets) >= 2
            for target in live_targets:
                _resolve_damage(chart, attacker, action["move"], target, rng, spread)

        turn_count += 1

def _roster_summary(team_static: list[dict]) -> list[dict]:
    return [
        {
            "id": m["id"],
            "name": m["name"],
            "level": m["level"],
            "candidate_moves": [
                {"name": mv["name"], "power": mv["power"], "type": mv["type"]}
                for mv in m["moves"]
            ],
        }
        for m in team_static
    ]

def battle_win_probability(
    team_1: Sequence[dict],
    team_2: Sequence[dict],
    format: str = "singles",
    seed: int | None = None,
) -> dict:
    if format not in MAX_ACTIVE:
        raise InvalidBattleInputError(f"format must be 'singles' or 'doubles', got {format!r}.")

    validated_1 = _validate_team(team_1, "team_1")
    validated_2 = _validate_team(team_2, "team_2")

    built_1 = [_build_member(m["name_or_id"], m["level"]) for m in validated_1]
    built_2 = [_build_member(m["name_or_id"], m["level"]) for m in validated_2]

    team_1_static = [member for member, _ in built_1]
    team_2_static = [member for member, _ in built_2]
    all_fallback = all(used_fallback for _, used_fallback in built_1 + built_2)

    if all_fallback:
        return {
            "format": format,
            "team_1": _roster_summary(team_1_static),
            "team_2": _roster_summary(team_2_static),
            "simulations_run": 0,
            "team_1_win_rate": 0.0,
            "team_2_win_rate": 0.0,
            "draw_rate": 1.0,
            "average_turns_to_decide": None,
        }

    chart = _build_type_chart()
    rng = random.Random(seed)

    team_1_wins = 0
    team_2_wins = 0
    draws = 0
    decided_turns = []

    for _ in range(SIMULATIONS):
        outcome, turns = _run_single_battle(team_1_static, team_2_static, format, chart, rng)
        if outcome == "team_1":
            team_1_wins += 1
            decided_turns.append(turns)
        elif outcome == "team_2":
            team_2_wins += 1
            decided_turns.append(turns)
        else:
            draws += 1

    return {
        "format": format,
        "team_1": _roster_summary(team_1_static),
        "team_2": _roster_summary(team_2_static),
        "simulations_run": SIMULATIONS,
        "team_1_win_rate": team_1_wins / SIMULATIONS,
        "team_2_win_rate": team_2_wins / SIMULATIONS,
        "draw_rate": draws / SIMULATIONS,
        "average_turns_to_decide": sum(decided_turns) / len(decided_turns) if decided_turns else None,
    }
