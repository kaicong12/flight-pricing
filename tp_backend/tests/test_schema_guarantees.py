"""The schema's promises: one active run per city, idempotent enqueue, safe claiming."""

import uuid

import pytest
from conftest import make_city
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from libs.db import IngestRun, IngestTask
from libs.db.enums import RunKind, RunStatus, Source, TaskKind, TaskStatus

CLAIM = text("""
UPDATE ingest_tasks SET status='running', locked_by=:worker, locked_at=now(),
       attempts=attempts+1
WHERE task_id = (
  SELECT task_id FROM ingest_tasks
  WHERE status='pending' AND run_after <= now()
  ORDER BY task_id
  FOR UPDATE SKIP LOCKED
  LIMIT 1)
RETURNING task_id, kind
""")

FINISH_RUN = text("""
UPDATE ingest_runs SET status='done', finished_at=now()
WHERE run_id=:run AND NOT EXISTS (
  SELECT 1 FROM ingest_tasks WHERE run_id=:run AND status IN ('pending','running'))
RETURNING run_id
""")


def make_run(db, city_id, status=RunStatus.RUNNING):
    run = IngestRun(run_id=str(uuid.uuid4()), city_id=city_id, kind=RunKind.CITY_INGEST,
                    status=status)
    db.add(run)
    db.commit()
    return run


def add_task(db, run, kind=TaskKind.REDNOTE_FETCH, dedupe_key="fetch:1",
             status=TaskStatus.PENDING, **kw):
    task = IngestTask(run_id=run.run_id, kind=kind, source=Source.REDNOTE,
                      payload={"note_id": "1"}, dedupe_key=dedupe_key, status=status, **kw)
    db.add(task)
    db.commit()
    return task


def test_one_active_run_per_city(db):
    """Two friends planning the same city must join one run, not spend the budget twice."""
    city = make_city(db)
    make_run(db, city)
    with pytest.raises(IntegrityError):
        make_run(db, city)


def test_finished_run_does_not_block_a_new_one(db):
    city = make_city(db)
    make_run(db, city, status=RunStatus.DONE)
    assert make_run(db, city, status=RunStatus.RUNNING).status == RunStatus.RUNNING


def test_enqueue_is_idempotent(db):
    """Fan-out can be retried, so the same dedupe_key must not create a second task."""
    run = make_run(db, make_city(db))
    add_task(db, run, dedupe_key="fetch:abc")
    with pytest.raises(IntegrityError):
        add_task(db, run, dedupe_key="fetch:abc")


def test_on_conflict_do_nothing_makes_re_fanout_a_noop(db):
    run = make_run(db, make_city(db))
    add_task(db, run, dedupe_key="fetch:abc")
    for _ in range(3):
        db.execute(text("""
            INSERT INTO ingest_tasks (run_id, kind, source, payload, dedupe_key, status)
            VALUES (:run, 'rednote.fetch', 'rednote', '{}'::jsonb, 'fetch:abc', 'pending')
            ON CONFLICT (run_id, dedupe_key) DO NOTHING
        """), {"run": run.run_id})
    db.commit()
    assert db.query(IngestTask).count() == 1


def test_invalid_status_is_rejected(db):
    run = make_run(db, make_city(db))
    with pytest.raises(IntegrityError):
        add_task(db, run, status="halfway")


def test_claim_locks_one_task_and_a_second_worker_gets_another(db, engine):
    """SKIP LOCKED is what lets two workers run without double-processing a task."""
    run = make_run(db, make_city(db))
    add_task(db, run, dedupe_key="fetch:1")
    add_task(db, run, dedupe_key="fetch:2")

    other = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        first = db.execute(CLAIM, {"worker": "w1"}).first()
        second = other.execute(CLAIM, {"worker": "w2"}).first()
        assert first and second
        assert first.task_id != second.task_id
        db.commit()
        other.commit()
    finally:
        other.close()

    assert db.query(IngestTask).filter_by(status=TaskStatus.RUNNING).count() == 2
    assert db.execute(CLAIM, {"worker": "w3"}).first() is None


def test_claim_skips_tasks_scheduled_for_later(db):
    run = make_run(db, make_city(db))
    add_task(db, run, dedupe_key="later", run_after=text("now() + interval '1 hour'"))
    assert db.execute(CLAIM, {"worker": "w1"}).first() is None


def test_run_completes_only_when_no_work_remains(db):
    run = make_run(db, make_city(db))
    task = add_task(db, run, dedupe_key="fetch:1")

    assert db.execute(FINISH_RUN, {"run": run.run_id}).first() is None

    task.status = TaskStatus.DONE
    db.commit()
    assert db.execute(FINISH_RUN, {"run": run.run_id}).first() is not None


def test_expired_lease_is_reclaimable(db):
    """A worker that dies mid-task must not strand it."""
    run = make_run(db, make_city(db))
    add_task(db, run, dedupe_key="fetch:1", status=TaskStatus.RUNNING,
             locked_by="dead-worker", locked_at=text("now() - interval '20 minutes'"))
    db.execute(text("""
        UPDATE ingest_tasks SET status='pending', locked_by=NULL
        WHERE status='running' AND locked_at < now() - interval '10 minutes'
    """))
    db.commit()
    assert db.execute(CLAIM, {"worker": "w1"}).first() is not None


def test_progress_query_shapes_the_checklist(db):
    """The loading screen's 'Reading posts 4 of 7' is a group-by, not a stored counter."""
    run = make_run(db, make_city(db))
    for i in range(7):
        add_task(db, run, dedupe_key=f"fetch:{i}",
                 status=TaskStatus.DONE if i < 4 else TaskStatus.PENDING)
    rows = db.execute(text("""
        SELECT kind, status, count(*) AS n FROM ingest_tasks
        WHERE run_id=:run GROUP BY kind, status
    """), {"run": run.run_id}).all()
    counts = {(r.kind, r.status): r.n for r in rows}
    assert counts[(TaskKind.REDNOTE_FETCH, TaskStatus.DONE)] == 4
    assert counts[(TaskKind.REDNOTE_FETCH, TaskStatus.PENDING)] == 3
