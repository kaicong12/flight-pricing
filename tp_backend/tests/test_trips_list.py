"""GET /trips: the landing screen's list."""

from datetime import timedelta

from conftest import plan_body, today_utc
from sqlalchemy import update

from libs.db import IngestRun, IngestTask, Place
from libs.db.enums import Confidence, RunStatus, TaskKind, TaskStatus


def test_no_trips_is_an_empty_list(client):
    r = client.get("/trips")
    assert r.status_code == 200
    assert r.json() == []


def test_lists_a_trip_with_its_city_and_dates(client):
    created = client.post("/initiate-plan", json=plan_body()).json()

    body = client.get("/trips").json()

    assert len(body) == 1
    assert body[0]["trip_id"] == created["trip_id"]
    assert body[0]["city"] == created["city"]
    assert body[0]["arrive_date"] == created["arrive_date"]
    assert body[0]["depart_date"] == created["depart_date"]
    assert body[0]["ingest"] == created["ingest"]


def test_task_counts_drive_the_progress_text(client, db):
    client.post("/initiate-plan", json=plan_body())
    db.execute(update(IngestTask)
               .where(IngestTask.kind == TaskKind.YOUTUBE_SEARCH)
               .values(status=TaskStatus.DONE))
    db.commit()

    row = client.get("/trips").json()[0]

    assert (row["tasks_done"], row["tasks_total"]) == (2, 3)


def test_skipped_tasks_count_as_finished(client, db):
    client.post("/initiate-plan", json=plan_body())
    db.execute(update(IngestTask).values(status=TaskStatus.SKIPPED))
    db.commit()

    assert client.get("/trips").json()[0]["tasks_done"] == 3


def test_place_count_comes_from_the_city(client, db):
    created = client.post("/initiate-plan", json=plan_body()).json()
    city_id = created["city"]["city_id"]
    db.add_all([Place(place_id=f"p{i}", city_id=city_id, name=f"Place {i}",
                      confidence=Confidence.HIGH) for i in range(3)])
    db.commit()

    assert client.get("/trips").json()[0]["place_count"] == 3


def test_a_far_future_trip_carries_the_transit_horizon_note(client):
    arrive = today_utc() + timedelta(days=200)
    client.post("/initiate-plan", json=plan_body(
        arrive_date=arrive.isoformat(),
        depart_date=(arrive + timedelta(days=2)).isoformat()))

    assert client.get("/trips").json()[0]["notes"] == ["transit_horizon"]


def test_a_second_trip_in_the_same_city_shares_one_run(client, db):
    first = client.post("/initiate-plan", json=plan_body()).json()
    second = client.post("/initiate-plan", json=plan_body()).json()

    body = client.get("/trips").json()

    assert {t["trip_id"] for t in body} == {first["trip_id"], second["trip_id"]}
    assert body[0]["ingest"]["run_id"] == body[1]["ingest"]["run_id"]


def test_the_latest_run_wins_when_a_city_is_ingested_again(client, db):
    old_run_id = client.post("/initiate-plan", json=plan_body()).json()["ingest"]["run_id"]
    db.execute(update(IngestRun).values(status=RunStatus.DONE))
    db.commit()

    new_run_id = client.post("/initiate-plan", json=plan_body()).json()["ingest"]["run_id"]
    assert new_run_id != old_run_id

    assert {t["ingest"]["run_id"] for t in client.get("/trips").json()} == {new_run_id}
