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
    gemini_api_key: str | None = None
    # Part of the re-extraction key via extractions.model.
    gemini_model: str = "gemini-3.5-flash-lite"
    # Must match the Cloud Console registration byte-for-byte; no default on purpose.
    google_auth_client_id: str | None = None
    google_auth_client_secret: str | None = None
    google_auth_redirect_uri: str | None = None
    session_ttl_days: int = 30

    city_refresh_days: int = 30
    # Half-width of searchText's rectangular locationRestriction.
    places_search_radius_m: int = 50000
    # Places terms only allow keeping place_id indefinitely.
    place_hours_ttl_days: int = 7
    max_stops_per_day: int = 25

    # The RedNote signature is bound to the URL path; only the cookie expires.
    xhs_cookie: str | None = None
    xhs_search_xs: str | None = None
    xhs_search_xt: str | None = None
    xhs_search_xs_common: str | None = None
    xhs_search_xrap: str | None = None
    xhs_feed_xs: str | None = None
    xhs_feed_xt: str | None = None
    xhs_feed_xs_common: str | None = None
    xhs_feed_xrap: str | None = None

    # One search burns most of an hour's budget if every result is fetched.
    rednote_max_fetch_per_search: int = 8
    rednote_ocr_max_images: int = 4

    # RedNote's gap is conservative: a real logged-in account is at risk.
    rednote_min_gap_s: float = 45.0
    rednote_jitter_s: float = 15.0
    rednote_max_per_hour: int = 50
    rednote_max_per_day: int = 300
    # Gemini flash-lite free tier limits.
    gemini_min_gap_s: float = 4.0
    gemini_max_per_minute: int = 15
    gemini_max_per_day: int = 1000

    @property
    def db_max_connections(self) -> int:
        return self.db_pool_size + self.db_max_overflow


@lru_cache
def settings() -> Settings:
    return Settings()
