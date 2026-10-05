"""GET /trips/{trip_id}: what the loading screen polls."""

import threading
import time

from conftest import plan_body
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from libs.db import IngestTask, Trip
from libs.db.enums import ErrorCode, TaskKind, TaskStatus
from libs.ingest import ensure_trip_plan
from tp_api.main import draft_trip
from tp_api.route_planning.service import lock_itinerary
from tp_ingestions.plan import draft


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
    assert {(p["kind"], p["status"]) for p in body["progress"]} == {
        (TaskKind.YOUTUBE_SEARCH, TaskStatus.DONE), (TaskKind.REDNOTE_SEARCH, TaskStatus.DONE)}


def test_a_trip_with_no_draft_reports_none(client):
    created = client.post("/initiate-plan", json=plan_body()).json()
    body = client.get(f"/trips/{created['trip_id']}").json()

    assert body["draft"] is None
    assert TaskKind.ROUTE_PLAN not in [p["kind"] for p in body["progress"]]


def test_the_draft_shows_as_a_checklist_row_while_it_runs(client, db):
    """The plan run is excluded from the progress query by kind, so without the explicit append the
    checklist shows nothing at all while a draft is in flight — which reads as "not implemented"."""
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
    assert client.post(f"/trips/{trip_id}/draft").status_code == 202

    body = client.get(f"/trips/{trip_id}").json()
    assert body["draft"] == TaskStatus.PENDING
    assert (TaskKind.ROUTE_PLAN, TaskStatus.PENDING, 1) in [
        (p["kind"], p["status"], p["count"]) for p in body["progress"]
    ]

    db.execute(update(IngestTask)
               .where(IngestTask.kind == TaskKind.ROUTE_PLAN)
               .values(status=TaskStatus.RUNNING))
    db.commit()
    assert client.get(f"/trips/{trip_id}").json()["draft"] == TaskStatus.RUNNING


def test_drafting_twice_does_not_queue_a_second_pending_task(client):
    """The button is clickable again the moment the request returns, so this must be idempotent."""
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]

    client.post(f"/trips/{trip_id}/draft")
    client.post(f"/trips/{trip_id}/draft")

    body = client.get(f"/trips/{trip_id}").json()
    rows = [p for p in body["progress"] if p["kind"] == TaskKind.ROUTE_PLAN]
    assert [(r["status"], r["count"]) for r in rows] == [(TaskStatus.PENDING, 1)]


def test_two_drafts_asked_for_at_once_queue_one(client, db, engine):
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
    other = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    second = threading.Thread(target=lambda: (draft_trip(trip_id, other), other.close()))

    lock_itinerary(db, trip_id)
    second.start()
    time.sleep(0.3)
    ensure_trip_plan(db, db.get(Trip, trip_id))
    second.join(10)

    queued = db.scalars(select(IngestTask).where(IngestTask.kind == TaskKind.ROUTE_PLAN)).all()
    assert len(queued) == 1


def test_a_finished_draft_can_be_asked_for_again(client, db):
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
    client.post(f"/trips/{trip_id}/draft")
    db.execute(update(IngestTask)
               .where(IngestTask.kind == TaskKind.ROUTE_PLAN)
               .values(status=TaskStatus.DONE))
    db.commit()

    assert client.post(f"/trips/{trip_id}/draft").json()["status"] == TaskStatus.PENDING
    assert db.scalars(
        select(IngestTask.status).where(IngestTask.kind == TaskKind.ROUTE_PLAN)
        .order_by(IngestTask.task_id)
    ).all() == [TaskStatus.DONE, TaskStatus.PENDING]


def test_drafting_a_missing_or_deleted_trip_is_a_404(client):
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
    client.delete(f"/trips/{trip_id}")

    assert client.post("/trips/nope/draft").status_code == 404
    assert client.post(f"/trips/{trip_id}/draft").status_code == 404


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

    assert client.patch(f"/trips/{trip_id}", json={"name": "   "}).json()["name"] is None


def test_patch_rejects_an_over_long_name_and_404s_on_a_missing_trip(client):
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
    assert client.patch(f"/trips/{trip_id}", json={"name": "x" * 121}).status_code == 422
    assert client.patch("/trips/nope", json={"name": "x"}).status_code == 404


def test_the_trip_says_why_its_draft_wrote_nothing(client, db):
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
    client.post(f"/trips/{trip_id}/draft")
    db.execute(update(IngestTask).where(IngestTask.kind == TaskKind.ROUTE_PLAN)
               .values(status=TaskStatus.DONE, result={"skipped": draft.ALL_DAYS_FILLED}))
    db.commit()

    result = client.get(f"/trips/{trip_id}").json()["draft_result"]
    assert result == {"skipped": draft.ALL_DAYS_FILLED}


def test_drafting_a_trip_with_every_day_filled_is_a_409(client):
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
    days = [{"day_index": d, "items": [{"kind": "custom", "block_id": f"b{d}", "title": "Stay",
                                        "start_min": 16 * 60, "duration_min": 60}]}
            for d in range(4)]
    assert client.put(f"/trips/{trip_id}/itinerary", json={"days": days}).status_code == 200

    r = client.post(f"/trips/{trip_id}/draft")

    assert r.status_code == 409
    assert "already has something in it" in r.json()["detail"]
