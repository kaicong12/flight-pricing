"""rednote.ocr — read venue names off a note's image cards, for notes whose text named none."""

import logging

import httpx
from sqlalchemy.orm import Session

from libs import gemini
from libs.db import Extraction, RedNotePost
from libs.db.enums import ErrorCode, ExtractedFrom, Source, TaskKind
from libs.http import client
from libs.prompts import REDNOTE_OCR
from libs.settings import settings
from tp_ingestions import limits
from tp_ingestions.errors import TaskError
from tp_ingestions.places.resolve import enqueue_resolve
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.rednote.extract import already_extracted, city_name
from tp_ingestions.registry import handles

log = logging.getLogger("rednote.ocr")

MIN_IMAGE_BYTES = 500
# The body named no venues — it is context only, so it does not need to be sent in full.
CONTEXT_LIMIT = 600


def download(urls: list[str]) -> list[bytes]:
    """Fetch the image cards. Some failing is normal; the caller decides if none is fatal."""
    got = []
    for url in urls:
        try:
            r = client().get(url)
        except httpx.HTTPError as e:
            log.info("image fetch failed %s: %s", url[-40:], e)
            continue
        if r.status_code != 200 or len(r.content) < MIN_IMAGE_BYTES:
            log.info("image fetch failed %s: %d, %db", url[-40:], r.status_code, len(r.content))
            continue
        got.append(r.content)
    return got


@handles(TaskKind.REDNOTE_OCR)
def rednote_ocr(session: Session, task: ClaimedTask) -> dict:
    note_id = task.payload["note_id"]
    note = session.get(RedNotePost, note_id)
    if note is None or not note.image_urls:
        raise TaskError(ErrorCode.PERMANENT, f"rednote note {note_id} has no image cards")
    if already_extracted(session, Source.REDNOTE, note_id, REDNOTE_OCR):
        return {"note_id": note_id, "cached": True}

    # Gemini's gate first: it is the budget that can defer, and downloading before it would throw
    # away the images. The cards sit on a CDN, not the logged-in API, so they need no RedNote budget.
    limits.gemini().take()
    images = download(note.image_urls[:settings().rednote_ocr_max_images])
    if not images:
        raise TaskError(ErrorCode.PERMANENT, f"rednote note {note_id}: no image card downloaded")

    rendered = REDNOTE_OCR.render(city=city_name(session, task), title=note.title or "",
                                  body=(note.description or "")[:CONTEXT_LIMIT])
    result = gemini.generate(REDNOTE_OCR, rendered, images=images)
    places = result.get("places") or []

    session.add(Extraction(
        source=Source.REDNOTE, source_ref=note_id,
        prompt_version=REDNOTE_OCR.version_key, model=REDNOTE_OCR.model,
        extracted_from=ExtractedFrom.IMAGE, is_useful=bool(result.get("is_useful")),
        is_promotional=bool(result.get("is_promotional")), content_type=result.get("content_type"),
        place_count=len(places), result=result))

    resolve = enqueue_resolve(session, task, Source.REDNOTE, note_id,
                              REDNOTE_OCR.version_key, REDNOTE_OCR.model) if places else 0
    return {"note_id": note_id, "images": len(images), "places": len(places),
            "resolve_queued": resolve}
