"""POST /initiate-plan: one trip per request, one ingest run per city."""

from datetime import UTC, datetime, timedelta

from conftest import HELSINKI, make_city, plan_body
from sqlalchemy import func, select

from libs.db import City, IngestRun, IngestTask, Trip
from libs.db.enums import TaskKind
from libs.places import NotACity, PlacesError
from tp_api.schemas import (
    MAX_TRIP_DAYS,
    TRANSIT_HORIZON_DAYS,
    TRANSIT_HORIZON_NOTE,
    today_utc,
)


def test_creates_trip_city_run_and_search_tasks(client, db):
    r = client.post("/initiate-plan", json=plan_body())
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["city"] == {"city_id": HELSINKI, "name": "Helsinki", "country": "FI",
                           "timezone": "Europe/Helsinki"}
    assert body["ingest"]["status"] == "pending"
    assert body["notes"] == []

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
    assert db.scalar(select(func.count()).select_from(IngestTask)) == 0


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


def test_overlong_trip_is_rejected(client):
    arrive = today_utc() + timedelta(days=10)
    r = client.post("/initiate-plan", json=plan_body(
        arrive_date=arrive.isoformat(),
        depart_date=(arrive + timedelta(days=MAX_TRIP_DAYS + 1)).isoformat()))
    assert r.status_code == 422


def test_overlong_extra_details_is_rejected(client):
    assert client.post("/initiate-plan", json=plan_body(extra_details="x" * 501)).status_code == 422


def test_a_trip_beyond_the_transit_horizon_is_accepted_with_a_note(client):
    far = today_utc() + timedelta(days=TRANSIT_HORIZON_DAYS + 30)
    r = client.post("/initiate-plan", json=plan_body(
        arrive_date=far.isoformat(), depart_date=(far + timedelta(days=3)).isoformat()))

    assert r.status_code == 200
    assert r.json()["notes"] == [TRANSIT_HORIZON_NOTE]


def test_times_are_optional(client, db):
    body = client.post("/initiate-plan", json=plan_body(arrive_time=None,
                                                        depart_time=None)).json()
    trip = db.get(Trip, body["trip_id"])
    assert trip.arrive_time is None
    assert trip.depart_time is None
