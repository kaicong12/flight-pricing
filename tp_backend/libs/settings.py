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
    # Every prompt resolves its model through this, so swapping it when a model's free tier runs out
    # needs no code change. It lands in extractions.model, which is part of the re-extraction key.
    gemini_model: str = "gemini-3.5-flash-lite"
    city_refresh_days: int = 30
    # searchText's locationRestriction is a rectangle, not a circle, and this is its half-width.
    places_search_radius_m: int = 50000
    # Hours move, and the Places terms only let place_id be kept indefinitely, so this is short.
    place_hours_ttl_days: int = 7
    # computeRoutes allows 25 intermediates, which bounds a day and so bounds a routing request.
    max_stops_per_day: int = 25

    # RedNote needs a cookie AND a signature, and the signature is bound to the URL path — hence
    # one set of these per endpoint. Only the cookie expires, so rotation means editing xhs_cookie.
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

    # Call budgets, one set per throttled domain. RedNote's gap stays conservative because the
    # downside is a real logged-in account being restricted, not a slower run.
    rednote_min_gap_s: float = 45.0
    rednote_jitter_s: float = 15.0
    rednote_max_per_hour: int = 50
    rednote_max_per_day: int = 300
    # The flash-lite free tier's shape. Settings so a paid key can loosen them without a code change.
    gemini_min_gap_s: float = 4.0
    gemini_max_per_minute: int = 15
    gemini_max_per_day: int = 1000

    @property
    def db_max_connections(self) -> int:
        return self.db_pool_size + self.db_max_overflow


@lru_cache
def settings() -> Settings:
    return Settings()
