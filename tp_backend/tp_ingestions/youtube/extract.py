"""youtube.extract — read a video's transcript for places, then queue their resolution."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs import gemini
from libs.db import Extraction, YouTubeVideo
from libs.db.enums import ErrorCode, ExtractedFrom, Source, TaskKind
from libs.prompts import YOUTUBE_TRANSCRIPT
from tp_ingestions import limits
from tp_ingestions.errors import TaskError
from tp_ingestions.places.resolve import enqueue_resolve
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.registry import handles
from tp_ingestions.youtube import transcript as tx

log = logging.getLogger("youtube.extract")


@handles(TaskKind.YOUTUBE_EXTRACT)
def youtube_extract(session: Session, task: ClaimedTask) -> dict:
    video_id = task.payload["video_id"]
    video = session.get(YouTubeVideo, video_id)
    if video is None:
        raise TaskError(ErrorCode.PERMANENT, f"video {video_id} was never inserted by search")

    if session.scalar(
        select(Extraction.id).where(
            Extraction.source == Source.YOUTUBE, Extraction.source_ref == video_id,
            Extraction.prompt_version == YOUTUBE_TRANSCRIPT.version_key,
            Extraction.model == YOUTUBE_TRANSCRIPT.model)
    ) is not None:
        return {"video_id": video_id, "cached": True}

    text = video.transcript
    if not text:
        text = tx.to_prompt_text(tx.fetch_transcript(video_id))
        if not text:
            raise TaskError(ErrorCode.PERMANENT, f"transcript {video_id} is empty")
        video.transcript = text
        session.flush()

    limits.gemini().take()
    result = gemini.generate(YOUTUBE_TRANSCRIPT, YOUTUBE_TRANSCRIPT.render(transcript=text))
    places = result.get("places") or []

    # A non-travel video still gets its row, so the gate is never paid for twice.
    session.add(Extraction(
        source=Source.YOUTUBE, source_ref=video_id,
        prompt_version=YOUTUBE_TRANSCRIPT.version_key, model=YOUTUBE_TRANSCRIPT.model,
        extracted_from=ExtractedFrom.TEXT, is_useful=bool(result.get("is_travel_content")),
        is_promotional=False, content_type=result.get("content_type"),
        place_count=len(places), result=result))

    resolve = enqueue_resolve(session, task, Source.YOUTUBE, video_id,
                              YOUTUBE_TRANSCRIPT.version_key, YOUTUBE_TRANSCRIPT.model) \
        if places else 0
    return {"video_id": video_id, "travel": bool(result.get("is_travel_content")),
            "places": len(places), "resolve_queued": resolve}
