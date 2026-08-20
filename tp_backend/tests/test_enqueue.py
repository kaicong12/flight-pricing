"""ensure_city / ensure_city_ingest: the get-or-create and join-don't-duplicate behaviour."""

from datetime import UTC, datetime, timedelta

from conftest import HELSINKI, make_city
from sqlalchemy import func, select

from libs.db import City, IngestRun, IngestTask
from libs.db.enums import RunKind, RunStatus, TaskKind
from libs.ingest.enqueue import ensure_city, ensure_city_ingest
from libs.places import CityDetails

DETAILS = CityDetails(place_id=HELSINKI, name="Helsinki", country="FI",
                      timezone="Europe/Helsinki", lat=60.17, lon=24.94)


def test_ensure_city_creates_then_reuses(db):
    city = ensure_city(db, DETAILS)
    assert city.city_id == HELSINKI
    assert city.timezone == "Europe/Helsinki"

    again = ensure_city(db, DETAILS)
    assert again.city_id == HELSINKI
    assert db.scalar(select(func.count()).select_from(City)) == 1


def test_ensure_city_backfills_only_missing_fields(db):
    db.add(City(city_id=HELSINKI, name="Helsinki"))
    db.commit()

    city = ensure_city(db, DETAILS)
    assert city.timezone == "Europe/Helsinki"
    assert city.lat == 60.17


def test_cold_city_gets_a_run_with_search_tasks(db):
    city = ensure_city(db, DETAILS)
    run = ensure_city_ingest(db, city)

    assert run is not None
    assert run.status == RunStatus.PENDING
    kinds = sorted(db.scalars(select(IngestTask.kind)).all())
    assert kinds == [TaskKind.REDNOTE_SEARCH, TaskKind.YOUTUBE_SEARCH, TaskKind.YOUTUBE_SEARCH]


def test_second_request_joins_the_active_run_and_adds_no_tasks(db):
    city = ensure_city(db, DETAILS)
    first = ensure_city_ingest(db, city)
    before = db.scalar(select(func.count()).select_from(IngestTask))

    second = ensure_city_ingest(db, city)

    assert second is not None
    assert second.run_id == first.run_id
    assert db.scalar(select(func.count()).select_from(IngestTask)) == before
    assert db.scalar(select(func.count()).select_from(IngestRun)) == 1


def test_warm_city_gets_no_run(db):
    make_city(db, last_ingested_at=datetime.now(UTC) - timedelta(days=3))
    city = db.get(City, HELSINKI)

    assert ensure_city_ingest(db, city) is None
    assert db.scalar(select(func.count()).select_from(IngestRun)) == 0


def test_stale_city_gets_a_fresh_run(db):
    make_city(db, last_ingested_at=datetime.now(UTC) - timedelta(days=45))
    city = db.get(City, HELSINKI)

    assert ensure_city_ingest(db, city) is not None


def test_a_finished_run_does_not_count_as_active(db):
    city = ensure_city(db, DETAILS)
    done = ensure_city_ingest(db, city)
    done.status = RunStatus.DONE
    db.commit()

    fresh = ensure_city_ingest(db, city)
    assert fresh.run_id != done.run_id


def test_youtube_tasks_are_one_per_language(db):
    city = ensure_city(db, DETAILS)
    run = ensure_city_ingest(db, city)

    yt = db.scalars(select(IngestTask).where(IngestTask.kind == TaskKind.YOUTUBE_SEARCH)).all()
    assert {t.payload["lang"] for t in yt} == {"en", "fi"}
    assert all(t.payload["region"] == "FI" for t in yt)
    assert all(t.run_id == run.run_id for t in yt)


def test_run_is_scoped_to_city_ingest(db):
    city = ensure_city(db, DETAILS)
    run = ensure_city_ingest(db, city)
    assert run.kind == RunKind.CITY_INGEST
    assert run.city_id == HELSINKI
