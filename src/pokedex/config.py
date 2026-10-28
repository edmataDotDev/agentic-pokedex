from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    anthropic_api_key: SecretStr
    model: str = "claude-sonnet-5"
    max_tool_retry: int
    model_name: str
    max_tokens: int
    max_concurrent_tools: int
    documents_location: Path = Path("legendary-lore")
    index_location: Path = Path("data/index")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="forbid",
    )

def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values are loaded from .env