"""Request-scoped dependencies. All are overridden in tests so no live API is called."""

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from libs.auth import user_for_token
from libs.db import User, UserTrip, session
from libs.db.enums import TripRole
from libs.places import (
    CityDetails,
    CitySuggestion,
    VenueHit,
    VenueSuggestion,
    city_details,
    search_cities,
    search_venues,
    venue_details,
)
from libs.routing import HoursHit, RouteResult, compute_walk, fetch_hours

CityLookup = Callable[[str], CityDetails]
CitySearch = Callable[[str, int], list[CitySuggestion]]
VenueSearch = Callable[[str, float, float, int], list[VenueSuggestion]]
VenueLookup = Callable[[str], VenueHit | None]
HoursLookup = Callable[[list[str]], dict[str, HoursHit]]
RouteCompute = Callable[[list[str]], RouteResult]


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
) -> str:
    """The caller's role on this trip. Access is the user_trips row, nothing else.

    404 rather than 403, so the gate cannot be used to discover which trip ids exist.
    """
    row = db.get(UserTrip, (user.user_id, trip_id))
    if row is None:
        raise HTTPException(404, "no such trip")
    return row.role


# 403 not 404 here: a member already knows the trip exists.
def require_edit(role: Annotated[str, Depends(require_trip_access)]) -> None:
    if role == TripRole.VIEWER:
        raise HTTPException(403, "you can view this trip but not change it")


def require_admin(role: Annotated[str, Depends(require_trip_access)]) -> None:
    if role != TripRole.OWNER:
        raise HTTPException(403, "only the trip's owner can do that")


def city_lookup() -> CityLookup:
    return city_details


def city_search() -> CitySearch:
    return search_cities


def venue_search() -> VenueSearch:
    return search_venues


def venue_lookup() -> VenueLookup:
    return venue_details


def hours_lookup() -> HoursLookup:
    return fetch_hours


def route_compute() -> RouteCompute:
    return compute_walk
