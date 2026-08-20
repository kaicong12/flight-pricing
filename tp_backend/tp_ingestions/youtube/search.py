"""youtube.search — find candidate videos for a city and fan out one extract task per keeper."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from libs.db import YouTubeVideo
from libs.db.enums import Source, TaskKind
from libs.ingest import enqueue
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.registry import handles
from tp_ingestions.youtube import client

log = logging.getLogger("youtube.search")

MIN_SECONDS = 360
MIN_VIEWS = 3000
LOOKBACK_YEARS = 3
RESULTS_PER_QUERY = 10


def keep(hit: dict, meta: dict | None, city_name: str) -> tuple[bool, str]:
    """Quality and city-name gate. Must be able to reject everything: 'Kutaisi Georgia' once
    returned five videos that passed every other filter, none about Kutaisi."""
    if not meta:
        return False, "no metadata"
    if meta["duration_s"] < MIN_SECONDS:
        return False, f"too short ({meta['duration_s']}s)"
    if meta["view_count"] < MIN_VIEWS:
        return False, f"too few views ({meta['view_count']})"
    blob = f"{hit['title']} {meta['description'][:600]}".lower()
    if city_name.split(",")[0].strip().lower() not in blob:
        return False, "city not named in title or description"
    return True, ""


@handles(TaskKind.YOUTUBE_SEARCH)
def youtube_search(session: Session, task: ClaimedTask) -> dict:
    payload = task.payload
    city_id, city_name = payload["city_id"], payload["city_name"]
    lang, region = payload.get("lang"), payload.get("region")

    since = (datetime.now(UTC) - timedelta(days=365 * LOOKBACK_YEARS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hits = client.search(f"{city_name} travel guide things to do", lang=lang, region=region,
                         published_after=since, limit=RESULTS_PER_QUERY)
    meta = client.hydrate([h["video_id"] for h in hits])

    kept, dropped = [], []
    for hit in hits:
        ok, why = keep(hit, meta.get(hit["video_id"]), city_name)
        (kept if ok else dropped).append((hit, why))
    for hit, why in dropped:
        log.info("dropped %s: %s", hit["video_id"], why)

    for hit, _ in kept:
        m = meta[hit["video_id"]]
        session.execute(
            pg_insert(YouTubeVideo)
            .values(video_id=hit["video_id"], title=hit["title"], channel=hit["channel"],
                    published_at=hit["published_at"], duration_s=m["duration_s"],
                    view_count=m["view_count"], captions=m["captions"], lang=m["lang"])
            # A cached video keeps its transcript; only the metadata is worth refreshing.
            .on_conflict_do_update(
                index_elements=["video_id"],
                set_={"title": hit["title"], "view_count": m["view_count"],
                      "captions": m["captions"]})
        )

    queued = enqueue(session, [
        {"run_id": task.run_id, "kind": TaskKind.YOUTUBE_EXTRACT, "source": Source.YOUTUBE,
         "payload": {"video_id": hit["video_id"], "city_id": city_id},
         "dedupe_key": f"{TaskKind.YOUTUBE_EXTRACT}:{hit['video_id']}"}
        for hit, _ in kept
    ])
    return {"lang": lang, "found": len(hits), "kept": len(kept), "queued": queued}
