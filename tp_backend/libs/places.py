"""Google Places lookups: turning a place_id into a city, and a venue name into a place_id."""

import math
from dataclasses import dataclass

import httpx

from libs.http import client
from libs.settings import settings

DETAILS_URL = "https://places.googleapis.com/v1/places"
AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "id,displayName,location,addressComponents,types,timeZone"

# A venue needs userRatingCount, which the city mask omits — it is the only trustworthy confidence
# signal. Keep the mask minimal otherwise; it sets the billing tier.
VENUE_FIELDS = ("places.id,places.displayName,places.formattedAddress,places.location,"
                "places.types,places.primaryTypeDisplayName,places.rating,places.userRatingCount")

# Details takes the mask unprefixed; a `places.`-prefixed one is a 400.
VENUE_DETAIL_FIELDS = ("id,displayName,formattedAddress,location,types,primaryTypeDisplayName,"
                       "rating,userRatingCount")

# 1 degree of latitude is ~111 km everywhere; longitude shrinks with the cosine of the latitude,
# which matters at Tromsø's 69°N.
_KM_PER_DEG_LAT = 111.0

# Autocomplete restricted to (cities) can still return a region or a district, but never a venue.
CITY_TYPES = {"locality", "administrative_area_level_1", "administrative_area_level_2",
              "administrative_area_level_3", "postal_town", "sublocality"}


class PlacesError(RuntimeError):
    """Places was unreachable or returned something unusable."""


class NotACity(ValueError):
    """The place_id resolves to something that is not a city."""


@dataclass(frozen=True)
class CitySuggestion:
    place_id: str
    description: str
    main_text: str | None


@dataclass(frozen=True)
class VenueSuggestion:
    place_id: str
    name: str
    context: str | None


@dataclass(frozen=True)
class VenueHit:
    place_id: str
    name: str
    address: str | None
    lat: float | None
    lon: float | None
    rating: float | None
    rating_count: int | None
    primary_type: str | None
    types: list[str]


@dataclass(frozen=True)
class CityDetails:
    place_id: str
    name: str
    country: str | None
    timezone: str | None
    lat: float | None
    lon: float | None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular, which is accurate enough over a city and cheap."""
    mean = math.radians((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * _KM_PER_DEG_LAT * math.cos(mean)
    dy = (lat2 - lat1) * _KM_PER_DEG_LAT
    return math.hypot(dx, dy)


def _country(components: list[dict]) -> str | None:
    for c in components:
        if "country" in c.get("types", []):
            return c.get("shortText")
    return None


def _autocomplete(body: dict, limit: int, timeout: float) -> list[dict]:
    key = settings().google_api_key
    if not key:
        raise PlacesError("GOOGLE_API_KEY is not set")

    try:
        r = client().post(AUTOCOMPLETE_URL, timeout=timeout, headers={"X-Goog-Api-Key": key},
                          json=body)
    except httpx.HTTPError as e:
        raise PlacesError(f"places autocomplete failed: {e}") from e
    if r.status_code != 200:
        raise PlacesError(f"places autocomplete returned {r.status_code}: {r.text[:200]}")

    # A suggestion is either a placePrediction or a queryPrediction; only the former has an id.
    out = [s["placePrediction"] for s in r.json().get("suggestions") or []
           if (s.get("placePrediction") or {}).get("placeId")]
    return out[:limit]


def search_cities(q: str, limit: int = 5, *, timeout: float = 10.0) -> list[CitySuggestion]:
    """Typeahead over city names. No matches is an empty list, not an error."""
    body = {"input": q, "includedPrimaryTypes": ["(cities)"]}
    return [
        CitySuggestion(
            place_id=p["placeId"],
            description=(p.get("text") or {}).get("text") or "",
            main_text=((p.get("structuredFormat") or {}).get("mainText") or {}).get("text"),
        )
        for p in _autocomplete(body, limit, timeout)
    ]


def search_venues(q: str, lat: float, lon: float, radius_m: int, limit: int = 6,
                  *, timeout: float = 10.0) -> list[VenueSuggestion]:
    """Typeahead over venues near a city. Autocomplete takes a circle where searchText needs a
    rectangle, and no `includedPrimaryTypes` means anything from a museum to a bakery comes back.

    A bias, not a restriction, because a trip may hold a place in another city.
    """
    body = {
        "input": q,
        "locationBias": {"circle": {
            "center": {"latitude": lat, "longitude": lon},
            "radius": float(radius_m),
        }},
    }
    out = []
    for p in _autocomplete(body, limit, timeout):
        fmt = p.get("structuredFormat") or {}
        main = (fmt.get("mainText") or {}).get("text")
        out.append(VenueSuggestion(
            place_id=p["placeId"],
            name=main or (p.get("text") or {}).get("text") or "",
            context=(fmt.get("secondaryText") or {}).get("text"),
        ))
    return out


def search_venue(query: str, lat: float, lon: float, radius_m: int,
                 *, timeout: float = 20.0) -> VenueHit | None:
    """Resolve one venue name near a city. No match is None, not an error.

    The caller must pass the name with its city appended: a bare "Tromso Cathedral" resolves to the
    Arctic Cathedral a kilometre away, while "Tromso Cathedral, Tromsø" resolves correctly. The box
    constrains geography; the suffix gives the matcher a lexical anchor. Both are needed.
    """
    key = settings().google_api_key
    if not key:
        raise PlacesError("GOOGLE_API_KEY is not set")

    # searchText's locationRestriction takes a rectangle only — a circle is a 400, and a 400 is
    # terminal, so it kills the task rather than retrying.
    d_lat = radius_m / 1000 / _KM_PER_DEG_LAT
    d_lon = d_lat / max(math.cos(math.radians(lat)), 0.01)
    body = {
        "textQuery": query,
        "maxResultCount": 1,
        "languageCode": "en",
        "locationRestriction": {"rectangle": {
            "low": {"latitude": lat - d_lat, "longitude": lon - d_lon},
            "high": {"latitude": lat + d_lat, "longitude": lon + d_lon},
        }},
    }

    try:
        r = client().post(SEARCH_URL, timeout=timeout, json=body,
                          headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": VENUE_FIELDS})
    except httpx.HTTPError as e:
        raise PlacesError(f"places searchText failed: {e}") from e
    if r.status_code != 200:
        raise PlacesError(f"places searchText returned {r.status_code}: {r.text[:200]}")

    hits = r.json().get("places") or []
    if not hits or not hits[0].get("id"):
        return None

    hit = hits[0]
    loc = hit.get("location") or {}
    return VenueHit(
        place_id=hit["id"],
        name=(hit.get("displayName") or {}).get("text") or query,
        address=hit.get("formattedAddress"),
        lat=loc.get("latitude"),
        lon=loc.get("longitude"),
        rating=hit.get("rating"),
        rating_count=hit.get("userRatingCount"),
        primary_type=(hit.get("primaryTypeDisplayName") or {}).get("text"),
        types=hit.get("types") or [],
    )


def venue_details(place_id: str, *, timeout: float = 10.0) -> VenueHit | None:
    """Fetch one venue by place_id. Unlike `city_details` it does not check the type — Places labels
    plenty of real venues with types no allowlist would hold."""
    key = settings().google_api_key
    if not key:
        raise PlacesError("GOOGLE_API_KEY is not set")

    try:
        r = client().get(f"{DETAILS_URL}/{place_id}", timeout=timeout,
                         headers={"X-Goog-Api-Key": key,
                                  "X-Goog-FieldMask": VENUE_DETAIL_FIELDS})
    except httpx.HTTPError as e:
        raise PlacesError(f"places details failed: {e}") from e
    # An unknown id is a 404, a malformed one a 400. Both mean no such place.
    if r.status_code in (400, 404):
        return None
    if r.status_code != 200:
        raise PlacesError(f"places details returned {r.status_code}: {r.text[:200]}")

    body = r.json()
    loc = body.get("location") or {}
    return VenueHit(
        # The response id is canonical; the one the client sent may be a merged alias.
        place_id=body.get("id") or place_id,
        name=(body.get("displayName") or {}).get("text") or place_id,
        address=body.get("formattedAddress"),
        lat=loc.get("latitude"),
        lon=loc.get("longitude"),
        rating=body.get("rating"),
        rating_count=body.get("userRatingCount"),
        primary_type=(body.get("primaryTypeDisplayName") or {}).get("text"),
        types=body.get("types") or [],
    )


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
