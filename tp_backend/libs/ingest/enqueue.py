"""Get-or-create a city and its ingest run. Everything here has to be safe to call concurrently."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from libs.db import City, IngestRun, IngestTask, Trip
from libs.db.enums import RunKind, RunStatus, Source, TaskKind
from libs.places import CityDetails
from libs.settings import settings

ACTIVE = (RunStatus.PENDING, RunStatus.RUNNING)

# Corpora are fully disjoint per language, so each is worth its own search. Thai is omitted
# deliberately — English already wins Bangkok.
LOCAL_LANGUAGE = {
    "CN": "zh", "DE": "de", "DK": "da", "ES": "es", "FI": "fi", "FR": "fr", "HK": "zh",
    "ID": "id", "IT": "it", "JP": "ja", "KR": "ko", "NL": "nl", "NO": "no", "PL": "pl",
    "PT": "pt", "SE": "sv", "TR": "tr", "TW": "zh", "VN": "vi",
}


def query_languages(country: str | None) -> list[str]:
    """English always, plus the local language when we have one for the country."""
    local = LOCAL_LANGUAGE.get((country or "").upper())
    return ["en", local] if local else ["en"]


def ensure_city(session: Session, details: CityDetails) -> City:
    """Get-or-create the city keyed by its Google place_id."""
    city = session.get(City, details.place_id)
    if city is None:
        session.execute(
            pg_insert(City)
            .values(city_id=details.place_id, name=details.name, country=details.country,
                    timezone=details.timezone, lat=details.lat, lon=details.lon)
            .on_conflict_do_nothing(index_elements=["city_id"])
        )
        session.commit()
        city = session.get(City, details.place_id)

    # Backfill only what a previous partial insert left empty; never overwrite good data.
    for field in ("country", "timezone", "lat", "lon"):
        if getattr(city, field) is None and getattr(details, field) is not None:
            setattr(city, field, getattr(details, field))
    session.commit()
    return city


def _active_run(session: Session, city_id: str) -> IngestRun | None:
    return session.scalars(
        select(IngestRun).where(
            IngestRun.city_id == city_id,
            IngestRun.kind == RunKind.CITY_INGEST,
            IngestRun.status.in_(ACTIVE),
        )
    ).first()


def _is_fresh(city: City) -> bool:
    if city.last_ingested_at is None:
        return False
    return city.last_ingested_at > datetime.now(UTC) - timedelta(days=settings().city_refresh_days)


def ensure_city_ingest(session: Session, city: City) -> IngestRun | None:
    """The run a client should poll, or None when the city is fresh enough to need no work."""
    if _is_fresh(city):
        return None

    existing = _active_run(session, city.city_id)
    if existing is not None:
        return existing

    run = IngestRun(run_id=str(uuid4()), city_id=city.city_id, kind=RunKind.CITY_INGEST,
                    status=RunStatus.PENDING)
    try:
        with session.begin_nested():
            session.add(run)
            session.flush()
    except IntegrityError:
        # uq_run_active_city fired: another request created the run since we looked.
        return _active_run(session, city.city_id)

    seed_search_tasks(session, run, city)
    session.commit()
    return run


def ensure_trip_plan(session: Session, trip: Trip, force: bool = False) -> IngestRun | None:
    """Queue one route.plan for a trip, or None if it already has one.

    Once only, ever, when automatic: the draft seeds empty days and a day the user has touched is
    theirs, so a second pass has nothing to add. Keyed on the task's payload because runs are per
    city, not per trip. `force` is the user asking again from the plan screen — the handler still
    fills only empty days, so asking twice cannot overwrite anything.
    """
    if not force and session.scalars(
        select(IngestTask.task_id).where(
            IngestTask.kind == TaskKind.ROUTE_PLAN,
            IngestTask.payload["trip_id"].astext == trip.trip_id,
        )
    ).first():
        return None

    run = IngestRun(run_id=str(uuid4()), city_id=trip.city_id, kind=RunKind.TRIP_PLANNING,
                    status=RunStatus.PENDING)
    session.add(run)
    session.flush()
    enqueue(session, [{
        "run_id": run.run_id,
        "kind": TaskKind.ROUTE_PLAN,
        "source": Source.GEMINI,
        "payload": {"trip_id": trip.trip_id},
        "dedupe_key": f"{TaskKind.ROUTE_PLAN}:{trip.trip_id}",
    }])
    session.commit()
    return run


def plan_after_ingest(session: Session, run_id: str) -> int:
    """After a city's ingestion settles, draft for every trip waiting on that city."""
    run = session.get(IngestRun, run_id)
    if run is None or run.kind != RunKind.CITY_INGEST or run.status != RunStatus.DONE:
        return 0
    trips = session.scalars(
        select(Trip).where(Trip.city_id == run.city_id, Trip.deleted.is_(False))
    ).all()
    return sum(1 for t in trips if ensure_trip_plan(session, t) is not None)


def seed_search_tasks(session: Session, run: IngestRun, city: City) -> None:
    """Enqueue the discovery tasks only. Their handlers fan out per video and per note."""
    rows = [
        {
            "run_id": run.run_id,
            "kind": TaskKind.YOUTUBE_SEARCH,
            "source": Source.YOUTUBE,
            "payload": {"city_id": city.city_id, "city_name": city.name,
                        "lang": lang, "region": city.country},
            "dedupe_key": f"{TaskKind.YOUTUBE_SEARCH}:{city.city_id}:{lang}",
        }
        for lang in query_languages(city.country)
    ]
    rows.append({
        "run_id": run.run_id,
        "kind": TaskKind.REDNOTE_SEARCH,
        "source": Source.REDNOTE,
        "payload": {"city_id": city.city_id, "keyword": f"{city.name} 美食"},
        "dedupe_key": f"{TaskKind.REDNOTE_SEARCH}:{city.city_id}",
    })

    enqueue(session, rows)


def enqueue(session: Session, rows: list[dict]) -> int:
    """Idempotent fan-out. A re-run search never duplicates its follow-on work.

    Counted via RETURNING because rowcount is -1 for a multi-row ON CONFLICT DO NOTHING.
    """
    if not rows:
        return 0
    return len(session.execute(
        pg_insert(IngestTask).values(rows)
        .on_conflict_do_nothing(constraint="uq_task_run_dedupe")
        .returning(IngestTask.task_id)
    ).all())
