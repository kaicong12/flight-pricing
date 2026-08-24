"""Google Routes. We never let it choose the order — optimizeWaypointOrder stays false.

WALK is one call for a whole day. TRANSIT forbids intermediate waypoints (a hard 400), so it is one
call per consecutive pair, and it has a ~100-day horizon beyond which there is simply no answer.
"""

import re
from dataclasses import dataclass
from itertools import pairwise

import httpx

from libs.http import client
from libs.settings import settings

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Field masks set the billing tier, so both are the minimum the UI actually renders. Transit step
# details cost more, which is why they are only on the transit mask.
WALK_FIELDS = ("routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,"
               "routes.legs.duration,routes.legs.distanceMeters")
TRANSIT_FIELDS = ("routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,"
                  "routes.legs.steps.travelMode,"
                  "routes.legs.steps.transitDetails.transitLine.nameShort,"
                  "routes.legs.steps.transitDetails.transitLine.name,"
                  "routes.legs.steps.transitDetails.stopDetails.departureStop.name,"
                  "routes.legs.steps.transitDetails.stopDetails.arrivalStop.name")


class RoutesError(RuntimeError):
    """Routes was unreachable or returned an error body."""


@dataclass(frozen=True)
class Leg:
    seconds: int
    meters: int
    transit_steps: list[str]
    # Set on transit legs only: per-pair encoded polylines cannot be concatenated into one string,
    # so a transit day is drawn leg by leg while a walking day gets RouteResult.polyline.
    polyline: str | None = None


@dataclass(frozen=True)
class RouteResult:
    """legs is empty when no route exists — beyond the transit horizon, or genuinely unreachable."""

    legs: list[Leg]
    polyline: str | None
    total_seconds: int
    total_meters: int


def _seconds(v: str | None) -> int:
    """Routes returns durations as "1281s"."""
    return int(re.sub(r"\D", "", v or "") or 0)


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


def _transit_steps(route: dict) -> list[str]:
    out = []
    for leg in route.get("legs") or []:
        for s in leg.get("steps") or []:
            td = s.get("transitDetails")
            if not td:
                continue
            line = td.get("transitLine") or {}
            stops = td.get("stopDetails") or {}
            dep = (stops.get("departureStop") or {}).get("name") or "?"
            arr = (stops.get("arrivalStop") or {}).get("name") or "?"
            out.append(f"{line.get('nameShort') or line.get('name') or '?'}: {dep} → {arr}")
    return out


def compute_walk(place_ids: list[str], *, timeout: float = 30.0) -> RouteResult:
    """One call for the whole ordered day.

    Walking silently routes through scheduled ferries — the Suomenlinna crossing comes back at
    19 km/h tagged as a toll, with no wait and no timetable — so a leg that crosses water is
    optimistic by however long the boat takes.
    """
    if len(place_ids) < 2:
        return RouteResult(legs=[], polyline=None, total_seconds=0, total_meters=0)

    body = {
        "origin": {"placeId": place_ids[0]},
        "destination": {"placeId": place_ids[-1]},
        "intermediates": [{"placeId": p} for p in place_ids[1:-1]],
        "travelMode": "WALK",
        "optimizeWaypointOrder": False,
    }
    routes = _post(body, WALK_FIELDS, timeout).get("routes") or []
    if not routes:
        return RouteResult(legs=[], polyline=None, total_seconds=0, total_meters=0)

    route = routes[0]
    legs = [Leg(seconds=_seconds(leg.get("duration")),
                meters=leg.get("distanceMeters") or 0,
                transit_steps=[])
            for leg in route.get("legs") or []]
    return RouteResult(
        legs=legs,
        polyline=(route.get("polyline") or {}).get("encodedPolyline") or None,
        total_seconds=_seconds(route.get("duration")),
        total_meters=route.get("distanceMeters") or 0,
    )


def compute_transit(place_ids: list[str], depart_iso: str, *, timeout: float = 30.0) -> RouteResult:
    """One call per consecutive pair, because TRANSIT rejects intermediates with a 400.

    Beyond the ~100-day horizon Routes answers 200 with an empty body rather than an error, so a
    missing route means "no answer available", never "the request was wrong". Unroutable pairs come
    back as zero-second legs and the caller warns about them.
    """
    if len(place_ids) < 2:
        return RouteResult(legs=[], polyline=None, total_seconds=0, total_meters=0)

    legs: list[Leg] = []
    for a, b in pairwise(place_ids):
        body = {"origin": {"placeId": a}, "destination": {"placeId": b},
                "travelMode": "TRANSIT", "departureTime": depart_iso}
        routes = _post(body, TRANSIT_FIELDS, timeout).get("routes") or []
        if not routes:
            legs.append(Leg(seconds=0, meters=0, transit_steps=[]))
            continue
        route = routes[0]
        legs.append(Leg(seconds=_seconds(route.get("duration")),
                        meters=route.get("distanceMeters") or 0,
                        transit_steps=_transit_steps(route),
                        polyline=(route.get("polyline") or {}).get("encodedPolyline") or None))

    return RouteResult(legs=legs, polyline=None,
                       total_seconds=sum(x.seconds for x in legs),
                       total_meters=sum(x.meters for x in legs))
