"""Claiming and settling tasks. The SQL here is the contract tests/test_schema_guarantees.py pins."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from libs.db import City, IngestRun, IngestTask
from libs.db.enums import ErrorCode, RunStatus, TaskStatus

ACTIVE_TASK = (TaskStatus.PENDING, TaskStatus.RUNNING)
ACTIVE_RUN = (RunStatus.PENDING, RunStatus.RUNNING)

_CLAIM = text("""
UPDATE ingest_tasks SET status='running', locked_by=:worker, locked_at=now(),
       attempts=attempts+1
WHERE task_id = (
  SELECT task_id FROM ingest_tasks
  WHERE status='pending' AND run_after <= now()
  ORDER BY task_id
  FOR UPDATE SKIP LOCKED
  LIMIT 1)
RETURNING task_id, run_id, kind, source, payload, attempts, max_attempts
""")

_REAP = text("""
UPDATE ingest_tasks SET status='pending', locked_by=NULL, locked_at=NULL
WHERE status='running' AND locked_at < now() - make_interval(secs => :seconds)
RETURNING task_id
""")


@dataclass(frozen=True)
class ClaimedTask:
    task_id: int
    run_id: str
    kind: str
    source: str | None
    payload: dict
    attempts: int
    max_attempts: int


def claim(session: Session, worker: str) -> ClaimedTask | None:
    """Take one due task, or None. SKIP LOCKED means two workers never get the same row."""
    row = session.execute(_CLAIM, {"worker": worker}).first()
    return ClaimedTask(*row) if row else None


def reap_expired(session: Session, lease: timedelta) -> list[int]:
    """Return tasks whose worker died back to pending. locked_at is the lease."""
    return [r[0] for r in session.execute(_REAP, {"seconds": lease.total_seconds()}).all()]


def mark_running(session: Session, run_id: str) -> None:
    session.execute(
        update(IngestRun)
        .where(IngestRun.run_id == run_id, IngestRun.status == RunStatus.PENDING)
        .values(status=RunStatus.RUNNING)
    )


def complete(session: Session, task_id: int) -> None:
    session.execute(
        update(IngestTask).where(IngestTask.task_id == task_id)
        .values(status=TaskStatus.DONE, finished_at=func.now(), locked_by=None, locked_at=None,
                error_code=None, last_error=None)
    )


def block(session: Session, task_id: int, reason: str) -> None:
    """Parked, not failed: the work is valid but nothing can run it yet."""
    session.execute(
        update(IngestTask).where(IngestTask.task_id == task_id)
        .values(status=TaskStatus.BLOCKED, finished_at=func.now(), locked_by=None, locked_at=None,
                last_error=reason[:2000])
    )


def defer(session: Session, task_id: int, code: ErrorCode, error: str, when: datetime) -> None:
    session.execute(
        update(IngestTask).where(IngestTask.task_id == task_id)
        .values(status=TaskStatus.PENDING, run_after=when, locked_by=None, locked_at=None,
                error_code=code, last_error=error[:2000])
    )


def reschedule(session: Session, task_id: int, reason: str, when: datetime) -> None:
    """Put a task back without spending an attempt — it only waited its turn, it did not fail.

    error_code is left alone so an earlier real failure's classification is not erased.
    """
    session.execute(
        update(IngestTask).where(IngestTask.task_id == task_id)
        .values(status=TaskStatus.PENDING, run_after=when, locked_by=None, locked_at=None,
                attempts=IngestTask.attempts - 1, last_error=reason[:2000])
    )


def fail(session: Session, task_id: int, code: ErrorCode, error: str) -> None:
    session.execute(
        update(IngestTask).where(IngestTask.task_id == task_id)
        .values(status=TaskStatus.FAILED, finished_at=func.now(), locked_by=None, locked_at=None,
                error_code=code, last_error=error[:2000])
    )


def finish_run_if_done(session: Session, run_id: str) -> str | None:
    """Settle the run once nothing is outstanding. Returns the status set, or None if still busy.

    Guarded on the run still being active, so whichever worker finishes last settles it exactly once.
    """
    counts = dict(session.execute(
        select(IngestTask.status, func.count())
        .where(IngestTask.run_id == run_id)
        .group_by(IngestTask.status)
    ).all())
    if counts.get(TaskStatus.PENDING) or counts.get(TaskStatus.RUNNING):
        return None

    done = counts.get(TaskStatus.DONE, 0)
    failed = counts.get(TaskStatus.FAILED, 0)
    needs_credentials = session.scalar(
        select(func.count()).select_from(IngestTask)
        .where(IngestTask.run_id == run_id, IngestTask.error_code == ErrorCode.CREDENTIALS)
    )
    # A run that got anything out of any source is a success; failed_task_count is how the UI says
    # what we could not read. Blocked tasks are neither — they are work nothing can run yet.
    if needs_credentials:
        status = RunStatus.NEEDS_CREDENTIALS
    elif failed and not done:
        status = RunStatus.FAILED
    else:
        status = RunStatus.DONE

    settled = session.execute(
        update(IngestRun)
        .where(IngestRun.run_id == run_id, IngestRun.status.in_(ACTIVE_RUN))
        .values(status=status, finished_at=func.now(), failed_task_count=failed)
    ).rowcount
    if not settled:
        return None

    # Only real completed work makes a city fresh; otherwise a run that did nothing would suppress
    # the next one for city_refresh_days.
    if done:
        run_city = select(IngestRun.city_id).where(IngestRun.run_id == run_id).scalar_subquery()
        session.execute(
            update(City).where(City.city_id == run_city).values(last_ingested_at=func.now())
        )
    return status
