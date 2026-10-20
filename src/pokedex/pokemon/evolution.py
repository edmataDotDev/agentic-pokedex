def map_evolution_detail(detail) -> dict:
    condition = {"trigger": detail.trigger.name}

    if detail.item is not None:
        condition["item"] = detail.item.name
    if detail.gender is not None:
        condition["gender"] = detail.gender
    if detail.held_item is not None:
        condition["held_item"] = detail.held_item.name
    if detail.known_move is not None:
        condition["known_move"] = detail.known_move.name
    if detail.known_move_type is not None:
        condition["known_move_type"] = detail.known_move_type.name
    if detail.location is not None:
        condition["location"] = detail.location.name
    if detail.min_level is not None:
        condition["min_level"] = detail.min_level
    if detail.min_happiness is not None:
        condition["min_happiness"] = detail.min_happiness
    if detail.min_beauty is not None:
        condition["min_beauty"] = detail.min_beauty
    if detail.min_affection is not None:
        condition["min_affection"] = detail.min_affection
    if detail.near_special_rock:
        condition["near_special_rock"] = True
    if detail.needs_multiplayer:
        condition["needs_multiplayer"] = True
    if detail.needs_overworld_rain:
        condition["needs_overworld_rain"] = True
    if detail.party_species is not None:
        condition["party_species"] = detail.party_species.name
    if detail.party_type is not None:
        condition["party_type"] = detail.party_type.name
    if detail.relative_physical_stats is not None:
        condition["relative_physical_stats"] = detail.relative_physical_stats
    if detail.time_of_day:
        condition["time_of_day"] = detail.time_of_day
    if detail.trade_species is not None:
        condition["trade_species"] = detail.trade_species.name
    if detail.turn_upside_down:
        condition["turn_upside_down"] = True
    if detail.region is not None:
        condition["region"] = detail.region.name
    if detail.required_pokemon_form is not None:
        condition["required_pokemon_form"] = detail.required_pokemon_form.name
    if detail.evolved_pokemon_form is not None:
        condition["evolved_pokemon_form"] = detail.evolved_pokemon_form.name
    if detail.used_move is not None:
        condition["used_move"] = detail.used_move.name
    if detail.min_move_count is not None:
        condition["min_move_count"] = detail.min_move_count
    if detail.min_steps is not None:
        condition["min_steps"] = detail.min_steps
    if detail.min_damage_taken is not None:
        condition["min_damage_taken"] = detail.min_damage_taken
    if detail.allowed_natures is not None:
        condition["allowed_natures"] = detail.allowed_natures.name
    if detail.condition_expression is not None:
        condition["condition_expression"] = detail.condition_expression.expression

    return condition

def map_chain_link(link) -> dict:
    defaults = [d for d in link.evolution_details if d.is_default]
    conditions = defaults if defaults else link.evolution_details

    return {
        "species": link.species.name,
        "conditions": [map_evolution_detail(d) for d in conditions],
        "evolves_to": [map_chain_link(child) for child in link.evolves_to],
    }
