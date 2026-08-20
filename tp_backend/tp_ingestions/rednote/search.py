"""rednote.search — find candidate notes for a city and fan out one fetch task per new note."""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from libs.db import RedNotePost
from libs.db.enums import Source, TaskKind
from libs.ingest import enqueue
from libs.settings import settings
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.rednote import client
from tp_ingestions.rednote.throttle import await_budget
from tp_ingestions.registry import handles

log = logging.getLogger("rednote.search")


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

    # page_size is 20 and throttle.MAX_PER_HOUR is 20, so an uncapped fan-out would spend the whole
    # hourly budget of a real logged-in account on one city. Keep the API's relevance order.
    fresh = [n for n in notes if n["note_id"] not in known][:settings().rednote_max_fetch_per_search]
    queued = enqueue(session, [
        {"run_id": task.run_id, "kind": TaskKind.REDNOTE_FETCH, "source": Source.REDNOTE,
         "payload": {"note_id": n["note_id"], "xsec_token": n["xsec_token"], "city_id": city_id},
         "dedupe_key": f"{TaskKind.REDNOTE_FETCH}:{n['note_id']}"}
        for n in fresh
    ])
    return {"keyword": keyword, "found": len(notes), "cached": len(known), "queued": queued}
