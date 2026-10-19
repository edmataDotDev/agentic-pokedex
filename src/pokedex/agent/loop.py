import anthropic
from pokedex.config import get_settings

settings = get_settings()
client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key.get_secret_value()
)