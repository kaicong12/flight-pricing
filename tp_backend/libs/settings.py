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
    db_pool_size: int = 10
    db_max_overflow: int = 10
    google_api_key: str | None = None
    city_refresh_days: int = 30

    # RedNote needs a cookie AND a signature, and the signature is bound to the URL path — hence
    # one set of these per endpoint. Only the cookie expires, so rotation means editing xhs_cookie.
    xhs_cookie: str | None = None
    xhs_search_xs: str | None = None
    xhs_search_xt: str | None = None
    xhs_search_xs_common: str | None = None
    xhs_search_xrap: str | None = None

    @property
    def db_max_connections(self) -> int:
        return self.db_pool_size + self.db_max_overflow


@lru_cache
def settings() -> Settings:
    return Settings()
