"""GET /trips/{trip_id}: what the loading screen polls."""

from conftest import plan_body
from sqlalchemy import select, update

from libs.db import IngestTask
from libs.db.enums import ErrorCode, TaskKind, TaskStatus


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


def test_failures_group_by_message_and_include_blocked(client, db):
    """Blocked is terminal, so it belongs here — the checklist alone renders it as still waiting."""
    created = client.post("/initiate-plan", json=plan_body()).json()
    db.execute(update(IngestTask)
               .where(IngestTask.kind == TaskKind.YOUTUBE_SEARCH)
               .values(status=TaskStatus.FAILED, error_code=ErrorCode.PERMANENT,
                       last_error="transcript abc: TranscriptsDisabled"))
    db.execute(update(IngestTask)
               .where(IngestTask.kind == TaskKind.REDNOTE_SEARCH)
               .values(status=TaskStatus.BLOCKED, last_error="no handler registered"))
    db.commit()

    failures = client.get(f"/trips/{created['trip_id']}").json()["failures"]

    # Two youtube.search tasks share one message, so they are one row of count 2, not two rows.
    assert [(f["kind"], f["status"], f["error_code"], f["count"]) for f in failures] == [
        (TaskKind.YOUTUBE_SEARCH, TaskStatus.FAILED, ErrorCode.PERMANENT, 2),
        (TaskKind.REDNOTE_SEARCH, TaskStatus.BLOCKED, None, 1),
    ]
    assert failures[0]["last_error"] == "transcript abc: TranscriptsDisabled"


def test_a_clean_run_has_no_failures(client, db):
    created = client.post("/initiate-plan", json=plan_body()).json()
    db.execute(update(IngestTask).values(status=TaskStatus.DONE))
    db.commit()

    assert client.get(f"/trips/{created['trip_id']}").json()["failures"] == []


def test_progress_reflects_a_finished_run(client, db):
    created = client.post("/initiate-plan", json=plan_body()).json()
    db.execute(update(IngestTask).values(status=TaskStatus.DONE))
    db.commit()
    assert db.scalars(select(IngestTask.status)).all() == [TaskStatus.DONE] * 3

    body = client.get(f"/trips/{created['trip_id']}").json()
    assert all(p["status"] == TaskStatus.DONE for p in body["progress"])


def test_name_defaults_to_null_so_the_client_can_fall_back(client):
    created = client.post("/initiate-plan", json=plan_body()).json()
    assert created["name"] is None


def test_initiate_plan_accepts_a_name(client):
    created = client.post("/initiate-plan", json=plan_body() | {"name": "  Sauna week  "}).json()
    assert created["name"] == "Sauna week"


def test_patch_renames_and_blank_clears_back_to_null(client):
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]

    assert client.patch(f"/trips/{trip_id}", json={"name": "Sauna week"}).json()["name"] == "Sauna week"
    assert client.get(f"/trips/{trip_id}").json()["name"] == "Sauna week"
    assert client.get("/trips").json()[0]["name"] == "Sauna week"

    # Blank restores the fallback rather than storing an empty string.
    assert client.patch(f"/trips/{trip_id}", json={"name": "   "}).json()["name"] is None


def test_patch_rejects_an_over_long_name_and_404s_on_a_missing_trip(client):
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
    assert client.patch(f"/trips/{trip_id}", json={"name": "x" * 121}).status_code == 422
    assert client.patch("/trips/nope", json={"name": "x"}).status_code == 404
