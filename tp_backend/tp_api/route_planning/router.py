"""The planning screen's endpoints: a ranked shortlist, the user's ordering, and one routed day.

Declaration and validation only — the work is in `service`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from tp_api.deps import (
    HoursLookup,
    RouteCompute,
    db_session,
    hours_lookup,
    route_compute,
)
from tp_api.route_planning import service
from tp_api.route_planning.schemas import (
    DayRouteOut,
    DismissalIn,
    ItineraryIn,
    ItineraryOut,
    RouteDayRequest,
    ShortlistOut,
)

router = APIRouter()

Db = Annotated[Session, Depends(db_session)]
Hours = Annotated[HoursLookup, Depends(hours_lookup)]
Route = Annotated[RouteCompute, Depends(route_compute)]


@router.get("/trips/{trip_id}/shortlist", response_model=ShortlistOut)
def get_shortlist(
    trip_id: str,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 40,
    offset: Annotated[int, Query(ge=0)] = 0,
    category: Annotated[str | None, Query(max_length=16)] = None,
) -> ShortlistOut:
    return service.shortlist(db, trip_id, limit, offset, category)


@router.get("/trips/{trip_id}/itinerary", response_model=ItineraryOut)
def get_itinerary(trip_id: str, db: Db) -> ItineraryOut:
    return service.read_days(db, service.get_trip(db, trip_id))


@router.put("/trips/{trip_id}/itinerary", response_model=ItineraryOut)
def put_itinerary(trip_id: str, body: ItineraryIn, db: Db) -> ItineraryOut:
    return service.replace_days(db, trip_id, body)


@router.post("/trips/{trip_id}/dismissals", status_code=204)
def add_dismissal(trip_id: str, body: DismissalIn, db: Db) -> None:
    service.add_dismissal(db, trip_id, body.place_id)


@router.delete("/trips/{trip_id}/dismissals/{place_id}", status_code=204)
def remove_dismissal(trip_id: str, place_id: str, db: Db) -> None:
    service.remove_dismissal(db, trip_id, place_id)


@router.post("/trips/{trip_id}/days/{day_index}/route", response_model=DayRouteOut)
def route_day(
    trip_id: str,
    day_index: int,
    body: RouteDayRequest,
    db: Db,
    fetch_hours: Hours,
    compute: Route,
) -> DayRouteOut:
    return service.route_day(db, trip_id, day_index, body, fetch_hours, compute)
