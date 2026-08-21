"""rednote.extract — read a fetched note's text body for venues, and queue OCR only if it named none."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs import gemini
from libs.db import City, Extraction, RedNotePost
from libs.db.enums import ErrorCode, ExtractedFrom, Source, TaskKind
from libs.ingest import enqueue
from libs.prompts import REDNOTE_TEXT, Prompt
from tp_ingestions import limits
from tp_ingestions.errors import TaskError
from tp_ingestions.places.resolve import enqueue_resolve
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.registry import handles

log = logging.getLogger("rednote.extract")

BODY_LIMIT = 6000


def already_extracted(session: Session, source: Source, ref: str, prompt: Prompt) -> bool:
    """uq_extraction_ref_version is how a source is never paid for twice, zero-yield notes included."""
    return session.scalar(
        select(Extraction.id).where(Extraction.source == source, Extraction.source_ref == ref,
                                    Extraction.prompt_version == prompt.version_key,
                                    Extraction.model == prompt.model)
    ) is not None


def city_name(session: Session, task: ClaimedTask) -> str:
    name = task.payload.get("city_name")
    if name:
        return name
    city_id = task.payload.get("city_id")
    return (city_id and session.scalar(select(City.name).where(City.city_id == city_id))) or ""


def extract_note(session: Session, task: ClaimedTask, note: RedNotePost) -> dict:
    """Run REDNOTE_TEXT over the note's desc and record the result."""
    if already_extracted(session, Source.REDNOTE, note.note_id, REDNOTE_TEXT):
        return {"note_id": note.note_id, "cached": True}

    city = city_name(session, task)
    rendered = REDNOTE_TEXT.render(city=city, title=note.title or "",
                                   body=(note.description or "")[:BODY_LIMIT])
    limits.gemini().take()
    result = gemini.generate(REDNOTE_TEXT, rendered)
    places = result.get("places") or []

    session.add(Extraction(
        source=Source.REDNOTE, source_ref=note.note_id,
        prompt_version=REDNOTE_TEXT.version_key, model=REDNOTE_TEXT.model,
        extracted_from=ExtractedFrom.TEXT, is_useful=bool(result.get("is_useful")),
        is_promotional=bool(result.get("is_promotional")), content_type=result.get("content_type"),
        place_count=len(places), result=result))

    # Desc-first: OCR is ~10x the tokens, so it runs only for the ~38% of notes whose text names nothing.
    queued = 0
    if not places and note.image_urls:
        queued = enqueue(session, [
            {"run_id": task.run_id, "kind": TaskKind.REDNOTE_OCR, "source": Source.REDNOTE,
             "payload": {"note_id": note.note_id, "city_id": task.payload.get("city_id"),
                         "city_name": city},
             "dedupe_key": f"{TaskKind.REDNOTE_OCR}:{note.note_id}"}])

    resolve = enqueue_resolve(session, task, Source.REDNOTE, note.note_id,
                              REDNOTE_TEXT.version_key, REDNOTE_TEXT.model) if places else 0
    return {"note_id": note.note_id, "places": len(places), "ocr_queued": queued,
            "resolve_queued": resolve}


@handles(TaskKind.REDNOTE_EXTRACT)
def rednote_extract(session: Session, task: ClaimedTask) -> dict:
    note_id = task.payload["note_id"]
    note = session.get(RedNotePost, note_id)
    if note is None or not note.description:
        raise TaskError(ErrorCode.PERMANENT, f"rednote note {note_id} has no fetched body")
    return extract_note(session, task, note)
