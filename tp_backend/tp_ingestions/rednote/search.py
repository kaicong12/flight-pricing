"""rednote.search — find candidate notes for a city and fan out one fetch task per new note."""

import logging
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from libs.db import RedNotePost
from libs.db.enums import ErrorCode, Source, TaskKind
from libs.ingest import enqueue
from tp_ingestions.errors import TaskError
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.rednote import client, throttle
from tp_ingestions.registry import handles

log = logging.getLogger("rednote.search")

# Below this we wait in-process; above it we hand the wait back to the queue via run_after rather
# than hold a database connection and a task lease while sleeping.
MAX_INLINE_WAIT = 10.0


def await_budget() -> None:
    try:
        wait = throttle.wait_time()
    except throttle.BudgetExhausted as e:
        raise TaskError(ErrorCode.QUOTA, str(e)) from e
    if wait > MAX_INLINE_WAIT:
        raise TaskError(ErrorCode.RATE_LIMITED, f"throttled for {wait:.0f}s",
                        retry_after=timedelta(seconds=wait))
    if wait > 0:
        log.info("throttle: sleeping %.1fs", wait)
        time.sleep(wait)


@handles(TaskKind.REDNOTE_SEARCH)
def rednote_search(session: Session, task: ClaimedTask) -> dict:
    payload = task.payload
    city_id, keyword = payload["city_id"], payload["keyword"]

    await_budget()
    notes = client.search_notes(keyword)

    # A note whose body we already have is never re-fetched.
    known = set(session.scalars(
        select(RedNotePost.note_id)
        .where(RedNotePost.note_id.in_([n["note_id"] for n in notes]),
               RedNotePost.description.is_not(None))
    ).all()) if notes else set()

    for note in notes:
        session.execute(
            pg_insert(RedNotePost)
            .values(note_id=note["note_id"], xsec_token=note["xsec_token"], title=note["title"],
                    likes=note["likes"], author=note["author"])
            # The token is single-use-ish and rotates per search, so refresh it; never clobber a body.
            .on_conflict_do_update(
                index_elements=["note_id"],
                set_={"xsec_token": note["xsec_token"], "likes": note["likes"]})
        )

    fresh = [n for n in notes if n["note_id"] not in known]
    queued = enqueue(session, [
        {"run_id": task.run_id, "kind": TaskKind.REDNOTE_FETCH, "source": Source.REDNOTE,
         "payload": {"note_id": n["note_id"], "xsec_token": n["xsec_token"], "city_id": city_id},
         "dedupe_key": f"{TaskKind.REDNOTE_FETCH}:{n['note_id']}"}
        for n in fresh
    ])
    return {"keyword": keyword, "found": len(notes), "cached": len(known), "queued": queued}
