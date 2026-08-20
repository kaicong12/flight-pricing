"""Google Places lookups. Only what the API layer needs: turning a place_id into a city."""

from dataclasses import dataclass

import httpx

from libs.http import client
from libs.settings import settings

DETAILS_URL = "https://places.googleapis.com/v1/places"
FIELDS = "id,displayName,location,addressComponents,types,timeZone"

# Autocomplete restricted to (cities) can still return a region or a district, but never a venue.
CITY_TYPES = {"locality", "administrative_area_level_1", "administrative_area_level_2",
              "administrative_area_level_3", "postal_town", "sublocality"}


class PlacesError(RuntimeError):
    """Places was unreachable or returned something unusable."""


class NotACity(ValueError):
    """The place_id resolves to something that is not a city."""


@dataclass(frozen=True)
class CityDetails:
    place_id: str
    name: str
    country: str | None
    timezone: str | None
    lat: float | None
    lon: float | None


def _country(components: list[dict]) -> str | None:
    for c in components:
        if "country" in c.get("types", []):
            return c.get("shortText")
    return None


def city_details(place_id: str, *, timeout: float = 10.0) -> CityDetails:
    """Fetch and validate a city by place_id. Raises NotACity for venues, PlacesError on transport."""
    key = settings().google_api_key
    if not key:
        raise PlacesError("GOOGLE_API_KEY is not set")

    try:
        r = client().get(f"{DETAILS_URL}/{place_id}", timeout=timeout,
                         headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS})
    except httpx.HTTPError as e:
        raise PlacesError(f"places details failed: {e}") from e
    if r.status_code == 404:
        raise NotACity(f"unknown place_id {place_id!r}")
    if r.status_code != 200:
        raise PlacesError(f"places details returned {r.status_code}: {r.text[:200]}")

    body = r.json()
    if not CITY_TYPES.intersection(body.get("types", [])):
        raise NotACity(f"{body.get('types')} is not a city")

    loc = body.get("location") or {}
    return CityDetails(
        # The response id is canonical; the one the client sent may be a merged alias.
        place_id=body.get("id") or place_id,
        name=(body.get("displayName") or {}).get("text") or place_id,
        country=_country(body.get("addressComponents") or []),
        timezone=(body.get("timeZone") or {}).get("id"),
        lat=loc.get("latitude"),
        lon=loc.get("longitude"),
    )
