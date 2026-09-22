"""The planning screen's endpoints: a ranked shortlist, the user's ordering, and one checked day.

Declaration and validation only — the work is in `service`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from tp_api.deps import (
    HoursLookup,
    VenueLookup,
    VenueSearch,
    db_session,
    hours_lookup,
    require_edit,
    require_trip_access,
    venue_lookup,
    venue_search,
)
from tp_api.route_planning import export, service
from tp_api.route_planning.schemas import (
    DayRouteOut,
    DismissalIn,
    ItineraryIn,
    ItineraryOut,
    PlaceAddIn,
    ShortlistOut,
    ShortlistPlaceOut,
    VenueSuggestionOut,
)

# Every route here is under /trips/{trip_id}, so one router-wide gate covers all of them.
router = APIRouter(dependencies=[Depends(require_trip_access)])

Db = Annotated[Session, Depends(db_session)]
Hours = Annotated[HoursLookup, Depends(hours_lookup)]
Venues = Annotated[VenueSearch, Depends(venue_search)]
Venue = Annotated[VenueLookup, Depends(venue_lookup)]
Edit = [Depends(require_edit)]


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


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# A viewer may export: the file says no more than the plan screen already shows them.
@router.get("/trips/{trip_id}/export.xlsx", response_class=Response)
def get_export(trip_id: str, db: Db, fetch_hours: Hours) -> Response:
    trip = service.get_trip(db, trip_id)
    return Response(
        content=export.workbook_bytes(db, trip, fetch_hours),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{export.filename(trip)}"'},
    )


@router.put("/trips/{trip_id}/itinerary", response_model=ItineraryOut, dependencies=Edit)
def put_itinerary(trip_id: str, body: ItineraryIn, db: Db) -> ItineraryOut:
    return service.replace_days(db, trip_id, body)


# Gated on edit because searching costs a Places call, and a viewer could only be 403'd by the POST.
@router.get("/trips/{trip_id}/places/search", response_model=list[VenueSuggestionOut],
            dependencies=Edit)
def search_places(
    trip_id: str,
    db: Db,
    search: Venues,
    q: Annotated[str, Query(min_length=2, max_length=120)],
) -> list[VenueSuggestionOut]:
    return service.venue_suggestions(db, trip_id, q, search)


@router.post("/trips/{trip_id}/places", response_model=ShortlistPlaceOut, dependencies=Edit)
def add_place(trip_id: str, body: PlaceAddIn, db: Db, lookup: Venue) -> ShortlistPlaceOut:
    return service.add_place(db, trip_id, body.place_id, body.category, lookup)


@router.post("/trips/{trip_id}/dismissals", status_code=204, dependencies=Edit)
def add_dismissal(trip_id: str, body: DismissalIn, db: Db) -> None:
    service.add_dismissal(db, trip_id, body.place_id)


@router.delete("/trips/{trip_id}/dismissals/{place_id}", status_code=204, dependencies=Edit)
def remove_dismissal(trip_id: str, place_id: str, db: Db) -> None:
    service.remove_dismissal(db, trip_id, place_id)


@router.post("/trips/{trip_id}/days/{day_index}/route", response_model=DayRouteOut)
def route_day(trip_id: str, day_index: int, db: Db, fetch_hours: Hours) -> DayRouteOut:
    return service.route_day(db, trip_id, day_index, fetch_hours)
