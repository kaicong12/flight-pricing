"""POST /initiate-plan: one trip per request, one ingest run per city."""

from datetime import UTC, datetime, timedelta

from conftest import HELSINKI, make_city, make_place, plan_body
from sqlalchemy import func, select, update

from libs.db import City, IngestRun, IngestTask, Place, Trip, TripPlace
from libs.db.enums import Confidence, RunStatus, TaskKind
from libs.ingest import plan_after_ingest
from libs.places import NotACity, PlacesError
from tp_api.schemas import today_utc


def test_creates_trip_city_run_and_search_tasks(client, db):
    r = client.post("/initiate-plan", json=plan_body())
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["city"] == {"city_id": HELSINKI, "name": "Helsinki", "country": "FI",
                           "timezone": "Europe/Helsinki"}
    assert body["ingest"]["status"] == "pending"

    trip = db.get(Trip, body["trip_id"])
    assert trip.city_id == HELSINKI
    assert trip.extra_details == "food and design, one proper sauna"
    assert str(trip.arrive_time) == "14:30:00"

    kinds = sorted(db.scalars(select(IngestTask.kind)).all())
    assert kinds == [TaskKind.REDNOTE_SEARCH, TaskKind.YOUTUBE_SEARCH, TaskKind.YOUTUBE_SEARCH]


def test_second_trip_same_city_joins_the_run_and_adds_no_tasks(client, db):
    first = client.post("/initiate-plan", json=plan_body()).json()
    tasks_after_first = db.scalar(select(func.count()).select_from(IngestTask))

    later = today_utc() + timedelta(days=60)
    second = client.post("/initiate-plan", json=plan_body(
        arrive_date=later.isoformat(), depart_date=(later + timedelta(days=4)).isoformat(),
        extra_details="museums only")).json()

    assert second["trip_id"] != first["trip_id"]
    assert second["ingest"]["run_id"] == first["ingest"]["run_id"]
    assert db.scalar(select(func.count()).select_from(IngestTask)) == tasks_after_first
    assert db.scalar(select(func.count()).select_from(IngestRun)) == 1
    assert db.scalar(select(func.count()).select_from(Trip)) == 2
    assert db.scalar(select(func.count()).select_from(City)) == 1


def test_warm_city_returns_no_ingest(client, db):
    make_city(db, last_ingested_at=datetime.now(UTC) - timedelta(days=2))

    body = client.post("/initiate-plan", json=plan_body()).json()

    assert body["ingest"] is None
    assert db.get(Trip, body["trip_id"]) is not None
    # No discovery work, but the draft still has to be queued: a warm city settles no run, so
    # plan_after_ingest never fires and this is the only chance to ask for one.
    kinds = db.scalars(select(IngestTask.kind)).all()
    assert kinds == [TaskKind.ROUTE_PLAN]
    assert db.scalar(select(IngestTask.payload)) == {"trip_id": body["trip_id"]}


def test_a_new_trip_claims_the_city_places_that_already_exist(client, db):
    """A claim is the whole shortlist, so a warm city's places have to be inherited at creation."""
    make_city(db, last_ingested_at=datetime.now(UTC) - timedelta(days=2))
    make_place(db, place_id="p1")
    make_place(db, place_id="p2")

    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]

    claimed = set(db.scalars(select(TripPlace.place_id).where(TripPlace.trip_id == trip_id)))
    assert claimed == {"p1", "p2"}


def test_a_trip_created_mid_run_catches_up_when_the_run_settles(client, db):
    """Neither the trip nor a resolve task sees the other's uncommitted rows, so plan_after_ingest
    reconciles rather than anything locking."""
    run_id = client.post("/initiate-plan", json=plan_body()).json()["ingest"]["run_id"]
    trip_id = db.scalar(select(Trip.trip_id))
    # Resolved without the claim the worker would have written — the race, not a shortcut.
    db.add(Place(place_id="missed", city_id=HELSINKI, name="Missed", confidence=Confidence.HIGH))
    db.execute(update(IngestRun).values(status=RunStatus.DONE))
    db.commit()

    plan_after_ingest(db, run_id)
    db.commit()

    assert set(db.scalars(select(TripPlace.place_id).where(TripPlace.trip_id == trip_id))) \
        == {"missed"}


def test_a_second_trip_on_a_warm_city_gets_its_own_draft(client, db):
    make_city(db, last_ingested_at=datetime.now(UTC) - timedelta(days=2))

    first = client.post("/initiate-plan", json=plan_body()).json()
    second = client.post("/initiate-plan", json=plan_body()).json()

    drafted = {r["trip_id"] for r in db.scalars(select(IngestTask.payload)).all()}
    assert drafted == {first["trip_id"], second["trip_id"]}


def test_a_place_that_is_not_a_city_is_rejected(client, lookup):
    def not_a_city(place_id):
        raise NotACity("['restaurant', 'food'] is not a city")

    lookup["fn"] = not_a_city
    r = client.post("/initiate-plan", json=plan_body())
    assert r.status_code == 422
    assert "not a city" in r.json()["detail"]


def test_places_being_down_is_a_bad_gateway(client, lookup):
    def boom(place_id):
        raise PlacesError("places details returned 500")

    lookup["fn"] = boom
    assert client.post("/initiate-plan", json=plan_body()).status_code == 502


def test_departure_before_arrival_is_rejected(client):
    arrive = today_utc() + timedelta(days=30)
    r = client.post("/initiate-plan", json=plan_body(
        arrive_date=arrive.isoformat(), depart_date=(arrive - timedelta(days=1)).isoformat()))
    assert r.status_code == 422


def test_past_arrival_is_rejected(client):
    past = today_utc() - timedelta(days=5)
    r = client.post("/initiate-plan", json=plan_body(
        arrive_date=past.isoformat(), depart_date=today_utc().isoformat()))
    assert r.status_code == 422


def test_overlong_extra_details_is_rejected(client):
    assert client.post("/initiate-plan", json=plan_body(extra_details="x" * 501)).status_code == 422


def test_times_are_optional(client, db):
    body = client.post("/initiate-plan", json=plan_body(arrive_time=None,
                                                        depart_time=None)).json()
    trip = db.get(Trip, body["trip_id"])
    assert trip.arrive_time is None
    assert trip.depart_time is None
