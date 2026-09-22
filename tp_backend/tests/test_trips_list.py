"""GET /trips: the landing screen's list."""


from conftest import make_place, plan_body
from sqlalchemy import update

from libs.db import City, IngestRun, IngestTask, Place, TripDismissal, TripPlace
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


def test_place_count_is_what_the_trip_claimed(client, db):
    """Resolved after the trip exists, so the count is the ingestion's claims reaching it."""
    created = client.post("/initiate-plan", json=plan_body()).json()
    for i in range(3):
        make_place(db, city_id=created["city"]["city_id"], place_id=f"p{i}", name=f"Place {i}")

    assert client.get("/trips").json()[0]["place_count"] == 3


def test_place_count_agrees_with_the_shortlist(client, db):
    """Both numbers are `in_shortlist`, so an out-of-city claim counts and a dismissal does not."""
    created = client.post("/initiate-plan", json=plan_body()).json()
    trip_id, city_id = created["trip_id"], created["city"]["city_id"]
    db.add(City(city_id="elsewhere", name="Sydney", country="AU"))
    db.commit()
    for i in range(3):
        make_place(db, city_id=city_id, place_id=f"p{i}", name=f"Place {i}")
    # Another city's ingestion claims nothing here; the hand-add is what reaches it.
    make_place(db, city_id="elsewhere", place_id="far", name="Opera House")
    db.add(TripPlace(trip_id=trip_id, place_id="far"))
    db.add(TripDismissal(trip_id=trip_id, place_id="p0"))
    db.commit()

    shortlist_total = client.get(f"/trips/{trip_id}/shortlist").json()["total"]
    assert client.get("/trips").json()[0]["place_count"] == shortlist_total == 3


def test_an_unclaimed_place_in_the_city_is_not_counted(client, db):
    """The city no longer implies the shortlist, so a place no trip claimed is invisible."""
    created = client.post("/initiate-plan", json=plan_body()).json()
    db.add(Place(place_id="orphan", city_id=created["city"]["city_id"], name="Orphan",
                 confidence=Confidence.HIGH))
    db.commit()

    assert client.get("/trips").json()[0]["place_count"] == 0


def test_a_dismissal_on_one_trip_does_not_change_anothers_count(client, db):
    first = client.post("/initiate-plan", json=plan_body()).json()
    second = client.post("/initiate-plan", json=plan_body()).json()
    make_place(db, city_id=first["city"]["city_id"], place_id="p0", name="Place 0")
    db.add(TripDismissal(trip_id=first["trip_id"], place_id="p0"))
    db.commit()

    counts = {t["trip_id"]: t["place_count"] for t in client.get("/trips").json()}
    assert counts == {first["trip_id"]: 0, second["trip_id"]: 1}


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
