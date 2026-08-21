"""places.resolve — turn one extraction's candidate names into places + place_mentions.

place_id is the identity, so the six transcribed spellings of one cable car become one places row
with six mentions. Names are gated before the call, never after: Places answers a bare "bakery" with
a real, well-rated bakery and nothing in the response says the query was a category.
"""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from libs.db import City, Extraction, Place, PlaceMention, PlaceQuery
from libs.db.enums import Category, ErrorCode, ExtractedFrom, Sentiment, Source, TaskKind
from libs.ingest import enqueue
from libs.places import PlacesError, VenueHit, search_venue
from libs.settings import settings
from tp_ingestions.errors import TaskError
from tp_ingestions.places import names
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.registry import handles

log = logging.getLogger("places.resolve")


def candidate_name(source: str, place: dict) -> str:
    """The name to search on. RedNote's name_local is the venue's own sign, when the model knew it."""
    if source == Source.REDNOTE:
        local = place.get("name_local")
        if local and place.get("name_local_confidence") != "unknown":
            return local
        return place.get("name_as_written") or ""
    return place.get("name") or ""


def category_of(place: dict) -> str | None:
    value = (place.get("category") or "").strip().lower()
    return value if value in set(Category) else None


def cached(session: Session, city_id: str, key: str) -> str | None:
    """The place_id this search string resolved to before, or None if it was never resolved."""
    row = session.get(PlaceQuery, (city_id, key))
    return row.place_id if row else None


def remember(session: Session, city_id: str, key: str, place_id: str) -> None:
    """Only hits: see PlaceQuery on why caching a miss would poison the name."""
    session.execute(
        pg_insert(PlaceQuery)
        .values(city_id=city_id, query_norm=key, place_id=place_id)
        .on_conflict_do_nothing(index_elements=["city_id", "query_norm"])
    )


def upsert_place(session: Session, city: City, hit: VenueHit, query: str,
                 confidence: str, reason: str) -> None:
    """Ratings move, so refresh them; never overwrite the name a better resolution already set."""
    session.execute(
        pg_insert(Place)
        .values(place_id=hit.place_id, city_id=city.city_id, name=hit.name, address=hit.address,
                lat=hit.lat, lon=hit.lon, rating=hit.rating, rating_count=hit.rating_count,
                primary_type=hit.primary_type, resolved_from_name=query,
                confidence=confidence, confidence_reason=reason)
        .on_conflict_do_update(
            index_elements=["place_id"],
            set_={"rating": hit.rating, "rating_count": hit.rating_count, "address": hit.address})
    )


def upsert_mention(session: Session, place_id: str, extraction: Extraction, place: dict) -> None:
    """uq_mention_place_source_ref omits prompt_version, so a note's text and OCR passes collide
    here by design — the later prompt version wins rather than adding a duplicate mention."""
    session.execute(
        pg_insert(PlaceMention)
        .values(place_id=place_id, source=extraction.source, source_ref=extraction.source_ref,
                name_as_written=place.get("name") or place.get("name_as_written"),
                category=category_of(place), why_go=place.get("why_go"), dish=place.get("dish"),
                quoted_price=place.get("quoted_price") or place.get("spoken_price"),
                sentiment=place.get("sentiment") or Sentiment.RECOMMENDED,
                source_timestamp=place.get("timestamp"),
                extracted_from=extraction.extracted_from or ExtractedFrom.TEXT,
                prompt_version=extraction.prompt_version, model=extraction.model)
        .on_conflict_do_update(
            constraint="uq_mention_place_source_ref",
            set_={"why_go": place.get("why_go"), "dish": place.get("dish"),
                  "category": category_of(place),
                  "prompt_version": extraction.prompt_version, "model": extraction.model})
    )


def enqueue_resolve(session: Session, task: ClaimedTask, source: Source, ref: str,
                    prompt_version: str, model: str) -> int:
    """Queue resolution for one extraction. prompt_version is in the dedupe key, or a note's text
    and OCR extractions would collapse into a single task and one of them go unresolved."""
    city_id = task.payload.get("city_id")
    if not city_id:
        return 0
    return enqueue(session, [
        {"run_id": task.run_id, "kind": TaskKind.PLACES_RESOLVE, "source": Source.PLACES,
         "payload": {"source": str(source), "source_ref": ref, "prompt_version": prompt_version,
                     "model": model, "city_id": city_id},
         "dedupe_key": f"{TaskKind.PLACES_RESOLVE}:{source}:{ref}:{prompt_version}"}])


@handles(TaskKind.PLACES_RESOLVE)
def places_resolve(session: Session, task: ClaimedTask) -> dict:
    payload = task.payload
    city = session.get(City, payload["city_id"])
    if city is None or city.lat is None or city.lon is None:
        raise TaskError(ErrorCode.PERMANENT, f"city {payload['city_id']} has no coordinates")

    extraction = session.scalar(
        select(Extraction).where(Extraction.source == payload["source"],
                                 Extraction.source_ref == payload["source_ref"],
                                 Extraction.prompt_version == payload["prompt_version"],
                                 Extraction.model == payload["model"]))
    if extraction is None:
        raise TaskError(ErrorCode.PERMANENT,
                        f"no extraction for {payload['source_ref']} {payload['prompt_version']}")

    radius = settings().places_search_radius_m
    counts = dict.fromkeys(("candidates", "filtered", "cached", "resolved", "rejected"), 0)
    # Misses are not cached in place_queries, so this keeps a name repeated inside one extraction
    # from costing two calls. In-process only: it cannot poison a later run.
    missed: set[str] = set()

    for place in (extraction.result or {}).get("places") or []:
        counts["candidates"] += 1
        name = candidate_name(extraction.source, place)

        if place.get("sentiment") == Sentiment.NOT_RECOMMENDED:
            counts["filtered"] += 1
            continue
        skip = names.reject_before_call(name)
        if skip:
            log.info("skipped %r: %s", name, skip)
            counts["filtered"] += 1
            continue

        # remember() writes inside this transaction, so a name repeated within one extraction is
        # already a cache hit by the second time round.
        key = names.query_norm(name)
        place_id = cached(session, city.city_id, key)
        if place_id:
            counts["cached"] += 1
            upsert_mention(session, place_id, extraction, place)
            continue
        if key in missed:
            counts["rejected"] += 1
            continue

        # The city suffix is not optional: bare "Tromso Cathedral" resolves to a different church.
        try:
            hit = search_venue(f"{name}, {city.name}", city.lat, city.lon, radius)
        except PlacesError as e:
            raise TaskError(ErrorCode.TRANSIENT, str(e)) from e

        if hit is None:
            log.info("unresolved %r: no result", name)
            missed.add(key)
            counts["rejected"] += 1
            continue

        away = names.distance_km(city.lat, city.lon, hit.lat or city.lat, hit.lon or city.lon)
        if away > radius / 1000:
            log.info("unresolved %r: %s is %.0fkm from %s", name, hit.name, away, city.name)
            missed.add(key)
            counts["rejected"] += 1
            continue

        confidence, reason = names.judge(name, hit)
        if confidence is None:
            log.info("unresolved %r: %s", name, reason)
            missed.add(key)
            counts["rejected"] += 1
            continue

        remember(session, city.city_id, key, hit.place_id)
        upsert_place(session, city, hit, name, confidence, reason)
        session.flush()
        upsert_mention(session, hit.place_id, extraction, place)
        counts["resolved"] += 1

    return {"ref": extraction.source_ref, **counts}
