"""Request-scoped dependencies. All are overridden in tests so no live API is called."""

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from libs.auth import user_for_token
from libs.db import User, UserTrip, session
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


def session_token(authorization: Annotated[str | None, Header()] = None) -> str:
    """tp_client holds the session token in an httpOnly cookie and forwards it as a bearer."""
    return (authorization or "").removeprefix("Bearer ").strip()


def current_user(
    db: Annotated[Session, Depends(db_session)],
    token: Annotated[str, Depends(session_token)],
) -> User:
    user = user_for_token(db, token) if token else None
    if user is None:
        raise HTTPException(401, "sign in required")
    return user


def require_trip_access(
    trip_id: str,
    db: Annotated[Session, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
) -> None:
    """Gate for every /trips/{trip_id} route. Access is the user_trips row, nothing else.

    404 rather than 403, so the gate cannot be used to discover which trip ids exist.
    """
    if db.get(UserTrip, (user.user_id, trip_id)) is None:
        raise HTTPException(404, "no such trip")


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
