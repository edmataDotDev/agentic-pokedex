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