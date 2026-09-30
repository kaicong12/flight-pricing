"""The schema's promises: one active run per city, idempotent enqueue, a closed status vocabulary."""

import uuid

import pytest
from conftest import make_city
from sqlalchemy.exc import IntegrityError

from libs.db import IngestRun, IngestTask
from libs.db.enums import RunKind, RunStatus, Source, TaskKind, TaskStatus


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



def test_invalid_status_is_rejected(db):
    run = make_run(db, make_city(db))
    with pytest.raises(IntegrityError):
        add_task(db, run, status="halfway")
