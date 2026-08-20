"""The planning API. Creates a trip, then makes sure its city has been ingested."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from anyio import to_thread
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs.db import IngestRun, IngestTask, Trip
from libs.db.enums import RunKind
from libs.ingest import ensure_city, ensure_city_ingest
from libs.places import NotACity, PlacesError
from libs.settings import settings
from tp_api.deps import CityLookup, city_lookup, db_session
from tp_api.schemas import (
    CityOut,
    IngestOut,
    InitiatePlanRequest,
    TaskProgress,
    TripOut,
    TripStatusOut,
    notes_for,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Endpoints are sync, so they run in anyio's threadpool. Leaving it wider than the connection
    # pool just moves the queue: requests would wait on pool_timeout and fail at 30s instead.
    to_thread.current_default_thread_limiter().total_tokens = settings().db_max_connections
    yield


app = FastAPI(title="Trip planner API", lifespan=lifespan)

Db = Annotated[Session, Depends(db_session)]
Lookup = Annotated[CityLookup, Depends(city_lookup)]


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
        progress=progress,
    )
