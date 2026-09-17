"""Google Routes. We never let it choose the order — optimizeWaypointOrder stays false.

One WALK call draws a whole day: the polyline and how far apart the places are. Travel time is
deliberately not asked for — the plan does not schedule around it.
"""

from dataclasses import dataclass

import httpx

from libs.http import client
from libs.settings import settings

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# The field mask sets the billing tier, so it is the minimum the UI actually renders.
WALK_FIELDS = ("routes.distanceMeters,routes.polyline.encodedPolyline,"
               "routes.legs.distanceMeters")


class RoutesError(RuntimeError):
    """Routes was unreachable or returned an error body."""


@dataclass(frozen=True)
class Leg:
    meters: int


@dataclass(frozen=True)
class RouteResult:
    """legs is empty when no route exists — genuinely unreachable, or Routes had no answer."""

    legs: list[Leg]
    polyline: str | None
    total_meters: int


def _post(body: dict, mask: str, timeout: float) -> dict:
    key = settings().google_api_key
    if not key:
        raise RoutesError("GOOGLE_API_KEY is not set")
    try:
        r = client().post(ROUTES_URL, timeout=timeout, json=body,
                          headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": mask})
    except httpx.HTTPError as e:
        raise RoutesError(f"computeRoutes failed: {e}") from e
    if r.status_code != 200:
        raise RoutesError(f"computeRoutes returned {r.status_code}: {r.text[:200]}")
    return r.json()


def compute_walk(place_ids: list[str], *, timeout: float = 30.0) -> RouteResult:
    """One call for the whole ordered day."""
    if len(place_ids) < 2:
        return RouteResult(legs=[], polyline=None, total_meters=0)

    body = {
        "origin": {"placeId": place_ids[0]},
        "destination": {"placeId": place_ids[-1]},
        "intermediates": [{"placeId": p} for p in place_ids[1:-1]],
        "travelMode": "WALK",
        "optimizeWaypointOrder": False,
    }
    routes = _post(body, WALK_FIELDS, timeout).get("routes") or []
    if not routes:
        return RouteResult(legs=[], polyline=None, total_meters=0)

    route = routes[0]
    return RouteResult(
        legs=[Leg(meters=leg.get("distanceMeters") or 0) for leg in route.get("legs") or []],
        polyline=(route.get("polyline") or {}).get("encodedPolyline") or None,
        total_meters=route.get("distanceMeters") or 0,
    )
