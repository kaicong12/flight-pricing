"""GET /trips/{trip_id}: what the loading screen polls."""

from conftest import plan_body
from sqlalchemy import select, update

from libs.db import IngestTask
from libs.db.enums import TaskKind, TaskStatus


def test_unknown_trip_is_a_404(client):
    assert client.get("/trips/nope").status_code == 404


def test_status_echoes_the_trip_and_its_run(client):
    created = client.post("/initiate-plan", json=plan_body()).json()

    body = client.get(f"/trips/{created['trip_id']}").json()

    assert body["trip_id"] == created["trip_id"]
    assert body["city"] == created["city"]
    assert body["arrive_date"] == created["arrive_date"]
    assert body["extra_details"] == created["extra_details"]
    assert body["ingest"] == created["ingest"]


def test_progress_counts_tasks_by_kind_and_status(client, db):
    created = client.post("/initiate-plan", json=plan_body()).json()
    db.execute(update(IngestTask)
               .where(IngestTask.kind == TaskKind.YOUTUBE_SEARCH)
               .values(status=TaskStatus.DONE))
    db.commit()

    progress = client.get(f"/trips/{created['trip_id']}").json()["progress"]

    counts = {(p["kind"], p["status"]): p["count"] for p in progress}
    assert counts == {(TaskKind.YOUTUBE_SEARCH, TaskStatus.DONE): 2,
                      (TaskKind.REDNOTE_SEARCH, TaskStatus.PENDING): 1}


def test_progress_reflects_a_finished_run(client, db):
    created = client.post("/initiate-plan", json=plan_body()).json()
    db.execute(update(IngestTask).values(status=TaskStatus.DONE))
    db.commit()
    assert db.scalars(select(IngestTask.status)).all() == [TaskStatus.DONE] * 3

    body = client.get(f"/trips/{created['trip_id']}").json()
    assert all(p["status"] == TaskStatus.DONE for p in body["progress"])
