"""Request-scoped dependencies. All are overridden in tests so no live API is called."""

from collections.abc import Callable, Iterator

from sqlalchemy.orm import Session

from libs.db import session
from libs.places import CityDetails, CitySuggestion, city_details, search_cities
from libs.routing import HoursHit, RouteResult, compute_transit, compute_walk, fetch_hours

CityLookup = Callable[[str], CityDetails]
CitySearch = Callable[[str, int], list[CitySuggestion]]
HoursLookup = Callable[[list[str]], dict[str, HoursHit]]
# (place_ids, mode, depart_iso) -> route. One callable for both modes so a test overrides once.
RouteCompute = Callable[[list[str], str, str], RouteResult]


def db_session() -> Iterator[Session]:
    with session() as s:
        yield s


def city_lookup() -> CityLookup:
    return city_details


def city_search() -> CitySearch:
    return search_cities


def hours_lookup() -> HoursLookup:
    return fetch_hours


def compute_route(place_ids: list[str], mode: str, depart_iso: str) -> RouteResult:
    if mode == "transit":
        return compute_transit(place_ids, depart_iso)
    return compute_walk(place_ids)


def route_compute() -> RouteCompute:
    return compute_route
