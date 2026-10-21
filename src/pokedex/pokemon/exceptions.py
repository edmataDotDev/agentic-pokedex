class PokemonNotFoundError(Exception):
    """Raised when a Pokémon cannot be found by name or National Pokédex number."""

class MoveNotFoundError(Exception):
    """Raised when a Move cannot be found by name or id number."""

class EvolutionTriggerNotFoundError(Exception):
    """Raised when an Evolution Trigger cannot be found by name or id number."""

class TypeNotFoundError(Exception):
    """Raised when a Type cannot be found by name or id number."""

class PokemonFormNotFoundError(Exception):
    """Raised when a Pokémon Form cannot be found by name or id number."""

class InvalidComparisonInputError(Exception):
    """Raised when compare_pokemon receives a malformed or out-of-range list of identifiers."""

class InvalidBattleInputError(Exception):
    """Raised when battle_win_probability receives a malformed team or format argument."""

class VersionNotFoundError(Exception):
    """Raised when a Version, Version Group, or Generation cannot be found by name or id."""

class LocationNotFoundError(Exception):
    """Raised when a Location or Location Area cannot be found by name or id."""

class ItemNotFoundError(Exception):
    """Raised when an Item cannot be found by name or id."""