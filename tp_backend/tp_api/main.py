"""The planning API. Creates a trip, then makes sure its city has been ingested."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from anyio import to_thread
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs.db import IngestRun, IngestTask, Place, Trip
from libs.db.enums import RunKind, TaskStatus
from libs.ingest import ensure_city, ensure_city_ingest
from libs.places import NotACity, PlacesError
from libs.settings import settings
from tp_api import plan_routes
from tp_api.deps import CityLookup, CitySearch, city_lookup, city_search, db_session
from tp_api.schemas import (
    CityOut,
    CitySuggestionOut,
    IngestOut,
    InitiatePlanRequest,
    TaskProgress,
    TripOut,
    TripStatusOut,
    TripSummaryOut,
    notes_for,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Endpoints are sync, so they run in anyio's threadpool. Leaving it wider than the connection
    # pool just moves the queue: requests would wait on pool_timeout and fail at 30s instead.
    to_thread.current_default_thread_limiter().total_tokens = settings().db_max_connections
    yield


app = FastAPI(title="Trip planner API", lifespan=lifespan)
app.include_router(plan_routes.router)

Db = Annotated[Session, Depends(db_session)]
Lookup = Annotated[CityLookup, Depends(city_lookup)]
Search = Annotated[CitySearch, Depends(city_search)]


@app.get("/health")
def health() -> dict[str, str]:
    """What the container healthcheck probes. Liveness only — it must not touch the database."""
    return {"status": "ok"}


@app.get("/cities/search", response_model=list[CitySuggestionOut])
def search_cities_endpoint(
    search: Search,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> list[CitySuggestionOut]:
    try:
        found = search(q, limit)
    except PlacesError as e:
        raise HTTPException(502, f"city search failed: {e}") from e
    return [CitySuggestionOut.model_validate(s, from_attributes=True) for s in found]


@app.post("/initiate-plan", response_model=TripOut)
def initiate_plan(body: InitiatePlanRequest, db: Db, lookup: Lookup) -> TripOut:
    try:
        details = lookup(body.city_place_id)
    except NotACity as e:
        raise HTTPException(422, f"not a city: {e}") from e
    except PlacesError as e:
        raise HTTPException(502, f"places lookup failed: {e}") from e

    city = ensure_city(db, details)
    trip = Trip(
        trip_id=str(uuid4()),
        city_id=city.city_id,
        arrive_date=body.arrive_date,
        arrive_time=body.arrive_time,
        depart_date=body.depart_date,
        depart_time=body.depart_time,
        extra_details=body.extra_details,
    )
    db.add(trip)
    db.commit()

    run = ensure_city_ingest(db, city)
    return TripOut(
        trip_id=trip.trip_id,
        city=CityOut.model_validate(city, from_attributes=True),
        arrive_date=trip.arrive_date,
        arrive_time=trip.arrive_time,
        depart_date=trip.depart_date,
        depart_time=trip.depart_time,
        extra_details=trip.extra_details,
        ingest=IngestOut(run_id=run.run_id, status=run.status) if run else None,
        notes=notes_for(trip.arrive_date),
    )


DONE_TASK_STATUSES = (TaskStatus.DONE, TaskStatus.SKIPPED)


@app.get("/trips", response_model=list[TripSummaryOut])
def list_trips(db: Db) -> list[TripSummaryOut]:
    trips = db.scalars(
        select(Trip).where(Trip.deleted.is_(False)).order_by(Trip.created_at.desc())
    ).all()
    if not trips:
        return []

    city_ids = {t.city_id for t in trips}

    # One query each rather than per trip: the list is the landing screen and N trips share cities.
    latest_run: dict[str, IngestRun] = {}
    for run in db.scalars(
        select(IngestRun)
        .where(IngestRun.city_id.in_(city_ids), IngestRun.kind == RunKind.CITY_INGEST)
        .order_by(IngestRun.requested_at.desc())
    ):
        if run.city_id is not None:
            latest_run.setdefault(run.city_id, run)

    counts: dict[str, tuple[int, int]] = {}
    if latest_run:
        rows = db.execute(
            select(IngestTask.run_id, IngestTask.status, func.count().label("n"))
            .where(IngestTask.run_id.in_([r.run_id for r in latest_run.values()]))
            .group_by(IngestTask.run_id, IngestTask.status)
        ).all()
        for row in rows:
            done, total = counts.get(row.run_id, (0, 0))
            counts[row.run_id] = (done + (row.n if row.status in DONE_TASK_STATUSES else 0),
                                  total + row.n)

    places = dict(
        db.execute(
            select(Place.city_id, func.count())
            .where(Place.city_id.in_(city_ids))
            .group_by(Place.city_id)
        ).all()
    )

    out = []
    for trip in trips:
        run = latest_run.get(trip.city_id)
        done, total = counts.get(run.run_id, (0, 0)) if run else (0, 0)
        out.append(
            TripSummaryOut(
                trip_id=trip.trip_id,
                city=CityOut.model_validate(trip.city, from_attributes=True),
                arrive_date=trip.arrive_date,
                depart_date=trip.depart_date,
                ingest=IngestOut(run_id=run.run_id, status=run.status) if run else None,
                tasks_done=done,
                tasks_total=total,
                place_count=places.get(trip.city_id, 0),
                notes=notes_for(trip.arrive_date),
            )
        )
    return out


@app.get("/trips/{trip_id}", response_model=TripStatusOut)
def get_trip(trip_id: str, db: Db) -> TripStatusOut:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "no such trip")

    run = db.scalars(
        select(IngestRun)
        .where(IngestRun.city_id == trip.city_id, IngestRun.kind == RunKind.CITY_INGEST)
        .order_by(IngestRun.requested_at.desc())
    ).first()

    # Counted, not stored: the checklist is a group-by so a restarted worker can't skew it.
    progress = []
    if run is not None:
        rows = db.execute(
            select(IngestTask.kind, IngestTask.status, func.count().label("n"))
            .where(IngestTask.run_id == run.run_id)
            .group_by(IngestTask.kind, IngestTask.status)
            .order_by(IngestTask.kind, IngestTask.status)
        ).all()
        progress = [TaskProgress(kind=r.kind, status=r.status, count=r.n) for r in rows]

    return TripStatusOut(
        trip_id=trip.trip_id,
        city=CityOut.model_validate(trip.city, from_attributes=True),
        arrive_date=trip.arrive_date,
        arrive_time=trip.arrive_time,
        depart_date=trip.depart_date,
        depart_time=trip.depart_time,
        extra_details=trip.extra_details,
        ingest=IngestOut(run_id=run.run_id, status=run.status) if run else None,
        notes=notes_for(trip.arrive_date),
        deleted=trip.deleted,
        progress=progress,
    )


@app.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: str, db: Db) -> None:
    """Hide a trip from the list. Soft, so its days and dismissals survive; idempotent."""
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "no such trip")
    trip.deleted = True
    db.commit()
