"""The polling loop: claiming, retry/backoff, terminal failures, leases, run settlement."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import HELSINKI, make_city
from sqlalchemy import select, update

from libs.db import City, IngestRun, IngestTask
from libs.db.enums import ErrorCode, RunKind, RunStatus, Source, TaskKind, TaskStatus
from tp_ingestions import queue
from tp_ingestions.errors import TaskError
from tp_ingestions.registry import HANDLERS
from tp_ingestions.worker import Worker


@pytest.fixture
def run(db):
    make_city(db)
    r = IngestRun(run_id="run-1", city_id=HELSINKI, kind=RunKind.CITY_INGEST,
                  status=RunStatus.PENDING)
    db.add(r)
    db.commit()
    return r


def add_task(db, run, kind=TaskKind.YOUTUBE_SEARCH, dedupe_key="t:1", **kw):
    task = IngestTask(run_id=run.run_id, kind=kind, source=Source.YOUTUBE,
                      payload={"city_id": HELSINKI}, dedupe_key=dedupe_key, **kw)
    db.add(task)
    db.commit()
    return task


@pytest.fixture
def worker(monkeypatch):
    """A worker with an empty handler table, so tests register exactly what they need."""
    monkeypatch.setattr("tp_ingestions.worker.load_handlers", lambda: None)
    saved = dict(HANDLERS)
    HANDLERS.clear()
    yield Worker(name="w1", poll_interval=0, reap_interval=1e9)
    HANDLERS.clear()
    HANDLERS.update(saved)


def test_nothing_due_returns_false(worker, db):
    assert worker.run_once() is False


def test_a_handled_task_completes_and_settles_the_run(worker, db, run):
    task = add_task(db, run)
    HANDLERS[TaskKind.YOUTUBE_SEARCH] = lambda s, t: {"kept": 3}

    assert worker.run_once() is True

    db.expire_all()
    assert db.get(IngestTask, task.task_id).status == TaskStatus.DONE
    assert db.get(IngestTask, task.task_id).attempts == 1
    assert db.get(IngestRun, run.run_id).status == RunStatus.DONE
    assert db.get(IngestRun, run.run_id).finished_at is not None


def test_a_completed_run_marks_the_city_ingested(worker, db, run):
    add_task(db, run)
    HANDLERS[TaskKind.YOUTUBE_SEARCH] = lambda s, t: {}

    worker.run_once()

    db.expire_all()
    assert db.get(City, HELSINKI).last_ingested_at is not None


def test_an_unhandled_kind_is_blocked_not_failed(worker, db, run):
    task = add_task(db, run, kind=TaskKind.REDNOTE_FETCH, dedupe_key="fetch:1")

    worker.run_once()

    db.expire_all()
    row = db.get(IngestTask, task.task_id)
    assert row.status == TaskStatus.BLOCKED
    assert "no handler" in row.last_error
    # Blocked work still lets the run settle, so a partial pipeline does not hang forever.
    assert db.get(IngestRun, run.run_id).status == RunStatus.DONE


def test_a_transient_failure_is_deferred_for_a_retry(worker, db, run):
    task = add_task(db, run)

    def boom(s, t):
        raise TaskError(ErrorCode.TRANSIENT, "upstream hiccup")

    HANDLERS[TaskKind.YOUTUBE_SEARCH] = boom
    worker.run_once()

    db.expire_all()
    row = db.get(IngestTask, task.task_id)
    assert row.status == TaskStatus.PENDING
    assert row.error_code == ErrorCode.TRANSIENT
    assert row.run_after > datetime.now(UTC)
    assert row.locked_by is None
    # Still outstanding, so the run must not be settled.
    assert db.get(IngestRun, run.run_id).status == RunStatus.RUNNING


def test_a_deferred_task_is_not_claimable_yet(worker, db, run):
    add_task(db, run, run_after=datetime.now(UTC) + timedelta(hours=1))
    HANDLERS[TaskKind.YOUTUBE_SEARCH] = lambda s, t: {}
    assert worker.run_once() is False


def test_credentials_failures_do_not_retry(worker, db, run):
    task = add_task(db, run)

    def no_auth(s, t):
        raise TaskError(ErrorCode.CREDENTIALS, "cookie expired")

    HANDLERS[TaskKind.YOUTUBE_SEARCH] = no_auth
    worker.run_once()

    db.expire_all()
    assert db.get(IngestTask, task.task_id).status == TaskStatus.FAILED
    assert db.get(IngestTask, task.task_id).attempts == 1
    assert db.get(IngestRun, run.run_id).status == RunStatus.NEEDS_CREDENTIALS


def test_attempts_are_exhausted_then_the_task_fails(worker, db, run):
    task = add_task(db, run, max_attempts=2)

    def boom(s, t):
        raise TaskError(ErrorCode.TRANSIENT, "still broken")

    HANDLERS[TaskKind.YOUTUBE_SEARCH] = boom
    worker.run_once()
    # Skip past the backoff rather than sleeping through it.
    db.execute(update(IngestTask).where(IngestTask.task_id == task.task_id)
               .values(run_after=datetime.now(UTC)))
    db.commit()
    worker.run_once()

    db.expire_all()
    row = db.get(IngestTask, task.task_id)
    assert (row.status, row.attempts) == (TaskStatus.FAILED, 2)
    assert db.get(IngestRun, run.run_id).status == RunStatus.FAILED
    assert db.get(IngestRun, run.run_id).failed_task_count == 1
    # A run with nothing to show for it must not mark the city as freshly ingested.
    assert db.get(City, HELSINKI).last_ingested_at is None


def test_an_unexpected_exception_is_treated_as_transient(worker, db, run):
    task = add_task(db, run)

    def kaboom(s, t):
        raise ValueError("not a TaskError")

    HANDLERS[TaskKind.YOUTUBE_SEARCH] = kaboom
    worker.run_once()

    db.expire_all()
    row = db.get(IngestTask, task.task_id)
    assert row.status == TaskStatus.PENDING
    assert row.error_code == ErrorCode.TRANSIENT
    assert "ValueError" in row.last_error


def test_one_failure_does_not_stop_the_run_from_succeeding(worker, db, run):
    add_task(db, run, dedupe_key="ok:1")
    add_task(db, run, kind=TaskKind.REDNOTE_SEARCH, dedupe_key="bad:1", max_attempts=1)

    def dispatch(s, t):
        if t.kind == TaskKind.REDNOTE_SEARCH:
            raise TaskError(ErrorCode.PERMANENT, "no")
        return {}

    HANDLERS[TaskKind.YOUTUBE_SEARCH] = dispatch
    HANDLERS[TaskKind.REDNOTE_SEARCH] = dispatch
    worker.drain()

    db.expire_all()
    settled = db.get(IngestRun, run.run_id)
    assert settled.status == RunStatus.DONE
    assert settled.failed_task_count == 1


def test_a_handler_can_enqueue_follow_on_work_that_drains_too(worker, db, run):
    add_task(db, run, dedupe_key="search:1")

    def fan_out(s, t):
        from libs.ingest import enqueue
        enqueue(s, [{"run_id": t.run_id, "kind": TaskKind.YOUTUBE_EXTRACT,
                     "source": Source.YOUTUBE, "payload": {"video_id": f"v{i}"},
                     "dedupe_key": f"extract:{i}"} for i in range(3)])
        return {"queued": 3}

    HANDLERS[TaskKind.YOUTUBE_SEARCH] = fan_out
    HANDLERS[TaskKind.YOUTUBE_EXTRACT] = lambda s, t: {}

    assert worker.drain() == 4

    db.expire_all()
    statuses = db.scalars(select(IngestTask.status)).all()
    assert statuses == [TaskStatus.DONE] * 4


def test_a_handlers_writes_roll_back_when_it_fails(worker, db, run):
    add_task(db, run, dedupe_key="search:1", max_attempts=1)

    def half_done(s, t):
        from libs.ingest import enqueue
        enqueue(s, [{"run_id": t.run_id, "kind": TaskKind.YOUTUBE_EXTRACT,
                     "source": Source.YOUTUBE, "payload": {}, "dedupe_key": "extract:1"}])
        raise TaskError(ErrorCode.PERMANENT, "died after enqueueing")

    HANDLERS[TaskKind.YOUTUBE_SEARCH] = half_done
    worker.run_once()

    db.expire_all()
    kinds = db.scalars(select(IngestTask.kind)).all()
    assert TaskKind.YOUTUBE_EXTRACT not in kinds


def test_an_expired_lease_is_reclaimed(db, run):
    task = add_task(db, run, status=TaskStatus.RUNNING, locked_by="dead",
                    locked_at=datetime.now(UTC) - timedelta(minutes=30))

    with_session_reap = queue.reap_expired(db, timedelta(minutes=10))
    db.commit()

    assert with_session_reap == [task.task_id]
    db.expire_all()
    row = db.get(IngestTask, task.task_id)
    assert (row.status, row.locked_by) == (TaskStatus.PENDING, None)


def test_a_live_lease_is_left_alone(db, run):
    add_task(db, run, status=TaskStatus.RUNNING, locked_by="alive",
             locked_at=datetime.now(UTC) - timedelta(minutes=1))
    assert queue.reap_expired(db, timedelta(minutes=10)) == []


def test_two_workers_never_claim_the_same_task(db, run, engine):
    from sqlalchemy.orm import sessionmaker
    add_task(db, run, dedupe_key="a")
    add_task(db, run, kind=TaskKind.REDNOTE_SEARCH, dedupe_key="b")

    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s1, s2 = factory(), factory()
    try:
        first = queue.claim(s1, "w1")
        second = queue.claim(s2, "w2")
        assert first is not None and second is not None
        assert first.task_id != second.task_id
    finally:
        s1.rollback(), s1.close()
        s2.rollback(), s2.close()
