"""Configuration, read from the repo-root .env like the spike scripts do."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env() -> Path | None:
    """Nearest .env walking up from this file."""
    for d in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        candidate = d / ".env"
        if candidate.is_file():
            return candidate
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_find_env(), extra="ignore")

    database_url: str = "postgresql+psycopg://localhost/trip_planner"


@lru_cache
def settings() -> Settings:
    return Settings()
