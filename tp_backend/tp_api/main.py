"""The planning API. Creates a trip, then makes sure its city has been ingested."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from anyio import to_thread
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs import logs
from libs.db import (
    City,
    IngestTask,
    Place,
    Trip,
    TripCity,
    TripDismissal,
    User,
    UserTrip,
    cities_by_trip,
    claim_city_places,
    trip_cities,
)
from libs.db.enums import TaskKind, TaskStatus, TripRole
from libs.ingest import (
    ensure_city,
    ensure_city_ingest,
    ensure_trip_plan,
    latest_runs,
    trip_ingest,
)
from libs.places import NotACity, PlacesError
from libs.settings import settings
from tp_api import metrics
from tp_api.auth_routes import router as auth_router
from tp_api.deps import (
    CityLookup,
    CitySearch,
    city_lookup,
    city_search,
    current_user,
    db_session,
    require_admin,
    require_edit,
    require_trip_access,
)
from tp_api.route_planning import router as planning_router
from tp_api.route_planning.service import in_shortlist
from tp_api.schemas import (
    CityOut,
    CitySuggestionOut,
    IngestOut,
    InitiatePlanRequest,
    TaskFailure,
    TaskProgress,
    TripOut,
    TripPatch,
    TripStatusOut,
    TripSummaryOut,
)
from tp_api.sharing import router as sharing_router
from tp_api.sharing import users_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Endpoints are sync, so they run in anyio's threadpool. Leaving it wider than the connection
    # pool just moves the queue: requests would wait on pool_timeout and fail at 30s instead.
    to_thread.current_default_thread_limiter().total_tokens = settings().db_max_connections
    yield


app = FastAPI(title="Trip planner API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(planning_router)
app.include_router(sharing_router)
app.include_router(users_router)
metrics.install(app)
logs.install()

# uvicorn already logs a line per request, so nothing here repeats method, path or status. These are
# the decisions behind a response that an access log cannot show.
log = logging.getLogger("tp_api")

Db = Annotated[Session, Depends(db_session)]
Lookup = Annotated[CityLookup, Depends(city_lookup)]
Search = Annotated[CitySearch, Depends(city_search)]
Me = Annotated[User, Depends(current_user)]
TripAccess = [Depends(require_trip_access)]
TripEdit = [Depends(require_edit)]
TripAdmin = [Depends(require_admin)]


@app.get("/health")
def health() -> dict[str, str]:
    """What the container healthcheck probes. Liveness only — it must not touch the database."""
    return {"status": "ok"}


@app.get("/cities/search", response_model=list[CitySuggestionOut])
def search_cities_endpoint(
    user: Me,
    search: Search,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> list[CitySuggestionOut]:
    try:
        found = search(q, limit)
    except PlacesError as e:
        log.warning("city search failed q=%r: %s", q, e)
        raise HTTPException(502, f"city search failed: {e}") from e
    return [CitySuggestionOut.model_validate(s, from_attributes=True) for s in found]


@app.post("/initiate-plan", response_model=TripOut)
def initiate_plan(body: InitiatePlanRequest, db: Db, lookup: Lookup, user: Me) -> TripOut:
    resolved: dict[str, City] = {}
    for place_id in body.city_place_ids:
        try:
            details = lookup(place_id)
        except NotACity as e:
            log.warning("initiate-plan rejected place_id=%s: not a city: %s", place_id, e)
            raise HTTPException(422, f"not a city: {e}") from e
        except PlacesError as e:
            log.warning("initiate-plan places lookup failed place_id=%s: %s", place_id, e)
            raise HTTPException(502, f"places lookup failed: {e}") from e
        city = ensure_city(db, details)
        # Keyed on the resolved id, not the input: Places answers an alias with the canonical one.
        resolved.setdefault(city.city_id, city)
    cities = list(resolved.values())

    trip = Trip(
        trip_id=str(uuid4()),
        city_id=cities[0].city_id,
        name=(body.name or "").strip() or None,
        arrive_date=body.arrive_date,
        arrive_time=body.arrive_time,
        depart_date=body.depart_date,
        depart_time=body.depart_time,
        extra_details=body.extra_details,
    )
    db.add(trip)
    db.add(UserTrip(user_id=user.user_id, trip_id=trip.trip_id, role=TripRole.OWNER))
    db.flush()
    for city in cities:
        db.add(TripCity(trip_id=trip.trip_id, city_id=city.city_id))
        claim_city_places(db, trip.trip_id, city.city_id)
    db.commit()

    runs = [r for r in (ensure_city_ingest(db, c) for c in cities) if r is not None]
    if not runs:
        ensure_trip_plan(db, trip)
    # Which of the two paths a trip took is invisible from the response alone, and it decides whether
    # anything is coming: a warm city's plan screen fills from a draft, a cold one's from a run.
    log.info("initiate-plan trip=%s cities=%s ingest=%s", trip.trip_id[:8],
             " ".join(f"{c.name}:{c.city_id}" for c in cities),
             f"run:{runs[0].run_id} {runs[0].status}"
             + (f" +{len(runs) - 1} more" if len(runs) > 1 else "") if runs
             else "warm, draft queued")
    return TripOut(
        trip_id=trip.trip_id,
        name=trip.name,
        city=CityOut.model_validate(cities[0], from_attributes=True),
        cities=[CityOut.model_validate(c, from_attributes=True) for c in cities],
        arrive_date=trip.arrive_date,
        arrive_time=trip.arrive_time,
        depart_date=trip.depart_date,
        depart_time=trip.depart_time,
        extra_details=trip.extra_details,
        ingest=IngestOut(run_id=runs[0].run_id, status=runs[0].status) if runs else None,
    )


DONE_TASK_STATUSES = (TaskStatus.DONE, TaskStatus.SKIPPED)
MAX_FAILURES_SHOWN = 25


def draft_task(db: Session, trip_id: str) -> IngestTask | None:
    """The trip's most recent route.plan task. Keyed on the payload because a planning run is per
    city, so the run alone cannot say which trip it drafted."""
    return db.scalars(
        select(IngestTask)
        .where(IngestTask.kind == TaskKind.ROUTE_PLAN,
               IngestTask.payload["trip_id"].astext == trip_id)
        .order_by(IngestTask.task_id.desc())
    ).first()


@app.get("/trips", response_model=list[TripSummaryOut])
def list_trips(db: Db, user: Me) -> list[TripSummaryOut]:
    rows = db.execute(
        select(Trip, UserTrip.role)
        .join(UserTrip, UserTrip.trip_id == Trip.trip_id)
        .where(UserTrip.user_id == user.user_id, Trip.deleted.is_(False))
        .order_by(Trip.created_at.desc())
    ).all()
    trips = [t for t, _ in rows]
    roles = {t.trip_id: role for t, role in rows}
    if not trips:
        return []

    # One query each rather than per trip: the list is the landing screen and N trips share cities.
    covered = cities_by_trip(db, [t.trip_id for t in trips])
    for t in trips:
        covered.setdefault(t.trip_id, [t.city_id])
    city_ids = {t.city_id for t in trips} | {cid for ids in covered.values() for cid in ids}
    cities = {c.city_id: c for c in db.scalars(select(City).where(City.city_id.in_(city_ids)))}
    latest_run = latest_runs(db, list(city_ids))

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

    # The shortlist's own predicates, correlated on Trip rather than one trip_id, so this stays one
    # query for every trip.
    dismissed = (select(TripDismissal.place_id)
                 .where(TripDismissal.trip_id == Trip.trip_id,
                        TripDismissal.place_id == Place.place_id)
                 .exists())
    places = dict(
        db.execute(
            select(Trip.trip_id, func.count())
            .join(Place, in_shortlist(Trip))
            .where(Trip.trip_id.in_([t.trip_id for t in trips]), ~dismissed)
            .group_by(Trip.trip_id)
        ).all()
    )

    out = []
    for trip in trips:
        mine = covered.get(trip.trip_id, [trip.city_id])
        run = trip_ingest(latest_run, mine)
        done, total = (0, 0)
        for cid in mine:
            if cid in latest_run:
                d, t = counts.get(latest_run[cid].run_id, (0, 0))
                done, total = done + d, total + t
        out.append(
            TripSummaryOut(
                trip_id=trip.trip_id,
                name=trip.name,
                city=CityOut.model_validate(cities[trip.city_id], from_attributes=True),
                cities=[CityOut.model_validate(cities[c], from_attributes=True)
                        for c in mine if c in cities],
                arrive_date=trip.arrive_date,
                depart_date=trip.depart_date,
                ingest=IngestOut(run_id=run.run_id, status=run.status) if run else None,
                your_role=roles[trip.trip_id],
                tasks_done=done,
                tasks_total=total,
                place_count=places.get(trip.trip_id, 0),
            )
        )
    return out


@app.get("/trips/{trip_id}", response_model=TripStatusOut)
def get_trip(trip_id: str, db: Db, role: Annotated[str, Depends(require_trip_access)],
             ) -> TripStatusOut:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "no such trip")

    cities = trip_cities(db, trip)
    city_ids = [c.city_id for c in cities]
    runs = latest_runs(db, city_ids)
    run = trip_ingest(runs, city_ids)
    run_ids = [runs[c].run_id for c in city_ids if c in runs]

    progress, failures = [], []
    if run_ids:
        rows = db.execute(
            select(IngestTask.kind, IngestTask.status, func.count().label("n"))
            .where(IngestTask.run_id.in_(run_ids))
            .group_by(IngestTask.kind, IngestTask.status)
            .order_by(IngestTask.kind, IngestTask.status)
        ).all()
        progress = [TaskProgress(kind=r.kind, status=r.status, count=r.n) for r in rows]

        # Grouped on the message too: twenty videos failing for one reason is one thing to read.
        bad = db.execute(
            select(IngestTask.kind, IngestTask.status, IngestTask.error_code,
                   IngestTask.last_error, func.count().label("n"))
            .where(IngestTask.run_id.in_(run_ids),
                   IngestTask.status.in_((TaskStatus.FAILED, TaskStatus.BLOCKED)))
            .group_by(IngestTask.kind, IngestTask.status, IngestTask.error_code,
                      IngestTask.last_error)
            .order_by(func.count().desc(), IngestTask.kind)
            .limit(MAX_FAILURES_SHOWN)
        ).all()
        failures = [TaskFailure(kind=r.kind, status=r.status, error_code=r.error_code,
                                last_error=r.last_error, count=r.n) for r in bad]

    # The draft lives in a trip_planning run, which the query above deliberately excludes, so it is
    # appended by hand. Without it the checklist shows nothing while a draft is in flight.
    draft = draft_task(db, trip_id)
    if draft is not None:
        progress.append(TaskProgress(kind=draft.kind, status=draft.status, count=1))

    return TripStatusOut(
        trip_id=trip.trip_id,
        name=trip.name,
        city=CityOut.model_validate(trip.city, from_attributes=True),
        cities=[CityOut.model_validate(c, from_attributes=True) for c in cities],
        arrive_date=trip.arrive_date,
        arrive_time=trip.arrive_time,
        depart_date=trip.depart_date,
        depart_time=trip.depart_time,
        extra_details=trip.extra_details,
        ingest=IngestOut(run_id=run.run_id, status=run.status) if run else None,
        deleted=trip.deleted,
        your_role=role,
        progress=progress,
        failures=failures,
        draft=draft.status if draft is not None else None,
    )


@app.patch("/trips/{trip_id}", response_model=TripOut, dependencies=TripAdmin)
def rename_trip(trip_id: str, body: TripPatch, db: Db) -> TripOut:
    """Rename a trip. An empty name clears it, which restores the city-name fallback."""
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "no such trip")

    trip.name = (body.name or "").strip() or None
    db.commit()

    return TripOut(
        trip_id=trip.trip_id,
        name=trip.name,
        city=CityOut.model_validate(trip.city, from_attributes=True),
        arrive_date=trip.arrive_date,
        arrive_time=trip.arrive_time,
        depart_date=trip.depart_date,
        depart_time=trip.depart_time,
        extra_details=trip.extra_details,
        deleted=trip.deleted,
    )


@app.post("/trips/{trip_id}/draft", status_code=202, dependencies=TripEdit)
def draft_trip(trip_id: str, db: Db) -> dict[str, str | None]:
    """Queue a draft for this trip's empty days. The handler leaves a touched day alone, so this is
    safe to call again; the client warns first only so the user is not surprised by new blocks."""
    trip = db.get(Trip, trip_id)
    if trip is None or trip.deleted:
        raise HTTPException(404, "no such trip")

    pending = draft_task(db, trip_id)
    if pending is not None and pending.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        log.info("draft trip=%s not queued, one is already %s", trip_id[:8], pending.status)
        return {"status": pending.status}

    ensure_trip_plan(db, trip, force=True)
    log.info("draft trip=%s queued", trip_id[:8])
    return {"status": TaskStatus.PENDING}


@app.delete("/trips/{trip_id}", status_code=204, dependencies=TripAdmin)
def delete_trip(trip_id: str, db: Db) -> None:
    """Hide a trip from the list. Soft, so its days and dismissals survive; idempotent."""
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "no such trip")
    trip.deleted = True
    db.commit()
