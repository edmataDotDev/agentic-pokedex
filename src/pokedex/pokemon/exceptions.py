class PokemonNotFoundError(Exception):
    """Raised when a Pokémon cannot be found by name or National Pokédex number."""

class MoveNotFoundError(Exception):
    """Raised when a Move cannot be found by name or id number."""