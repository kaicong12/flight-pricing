"""What the planning endpoints actually do: rank a shortlist, store an ordering, route one day.

The order is the user's. Nothing here reorders anything — routing follows the sequence it is given
and the warnings say what does not work.

These functions raise `HTTPException` directly rather than a private exception hierarchy the router
would only translate one-to-one. Everything they return is already a response schema.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import Row, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from libs.db import (
    ItineraryItem,
    Place,
    PlaceHours,
    PlaceMention,
    RedNotePost,
    Trip,
    TripDismissal,
    YouTubeVideo,
)
from libs.db.enums import Sentiment, Source
from libs.places import PlacesError
from libs.routing import (
    PlanWarning,
    RouteResult,
    RoutesError,
    Stop,
    TravelLeg,
    hhmm,
    plan_day,
    sun_times,
)
from libs.settings import settings
from tp_api.deps import HoursLookup, RouteCompute
from tp_api.route_planning.schemas import (
    BlockOut,
    DaylightOut,
    DayOut,
    DayRouteOut,
    ItemOut,
    ItineraryIn,
    ItineraryOut,
    LegOut,
    RouteDayRequest,
    ShortlistOut,
    ShortlistPlaceOut,
    SourceRefOut,
    WarningOut,
    provisional_reasons,
)
from tp_api.route_planning.utils import (
    available_window,
    day_count,
    depart_instant,
    google_weekday,
    source_title,
    source_url,
    tz_minutes,
)


def get_trip(db: Session, trip_id: str) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "no such trip")
    return trip


def check_day(trip: Trip, day_index: int) -> date:
    if not 0 <= day_index < day_count(trip):
        raise HTTPException(422, f"day {day_index} is outside the trip")
    return trip.arrive_date + timedelta(days=day_index)


def mention_facts(db: Session, place_ids: Sequence[str]) -> dict[str, tuple[str | None, str | None]]:
    """Modal category and a why_go blurb per place.

    Both are opinions from mentions rather than facts from Places, so they are derived here rather
    than denormalised onto `places` — a new mention should change them without a migration.
    """
    if not place_ids:
        return {}
    rows = db.execute(
        select(PlaceMention.place_id, PlaceMention.category, PlaceMention.why_go,
               PlaceMention.sentiment)
        .where(PlaceMention.place_id.in_(place_ids))
    ).all()

    categories: dict[str, Counter] = {}
    blurbs: dict[str, str] = {}
    for r in rows:
        if r.category:
            categories.setdefault(r.place_id, Counter())[r.category] += 1
        # Prefer the fullest recommendation: one sentence of why-go beats a three-word one.
        if (r.why_go and r.sentiment == Sentiment.RECOMMENDED
                and len(r.why_go) > len(blurbs.get(r.place_id, ""))):
            blurbs[r.place_id] = r.why_go

    return {pid: (categories[pid].most_common(1)[0][0] if pid in categories else None,
                  blurbs.get(pid))
            for pid in set(place_ids)}


def mention_sources(db: Session, place_ids: Sequence[str]) -> dict[str, list[SourceRefOut]]:
    """The videos and notes behind each place, so a shortlist row can link back to its evidence.

    Each join is gated on the source, or a note_id would be matched against a video_id.
    """
    if not place_ids:
        return {}
    rows = db.execute(
        select(PlaceMention.place_id, PlaceMention.source, PlaceMention.source_ref,
               YouTubeVideo.title.label("video_title"),
               RedNotePost.title.label("note_title"), RedNotePost.description,
               RedNotePost.xsec_token)
        .outerjoin(YouTubeVideo, (PlaceMention.source == Source.YOUTUBE)
                   & (YouTubeVideo.video_id == PlaceMention.source_ref))
        .outerjoin(RedNotePost, (PlaceMention.source == Source.REDNOTE)
                   & (RedNotePost.note_id == PlaceMention.source_ref))
        .where(PlaceMention.place_id.in_(place_ids))
        .order_by(PlaceMention.place_id, PlaceMention.source, PlaceMention.id)
    ).all()

    out: dict[str, list[SourceRefOut]] = {}
    for r in rows:
        url = source_url(r.source, r.source_ref, r.xsec_token)
        if url is None:
            continue
        title = source_title(r.source, r.video_title, r.note_title, r.description)
        out.setdefault(r.place_id, []).append(
            SourceRefOut(source=r.source, title=title, url=url))
    return out


def shortlist(db: Session, trip_id: str, limit: int, offset: int,
              category: str | None) -> ShortlistOut:
    """The city's places, ranked by how many independent sources mentioned each one."""
    trip = get_trip(db, trip_id)

    mentions = (
        select(PlaceMention.place_id.label("place_id"), func.count().label("mention_count"))
        .group_by(PlaceMention.place_id)
        .subquery()
    )
    rank = func.coalesce(mentions.c.mention_count, 0)

    stmt = (
        select(Place, rank.label("mention_count"),
               ItineraryItem.day_index,
               # Computed before LIMIT, so one query yields both the page and the full count.
               func.count().over().label("total"))
        .outerjoin(mentions, mentions.c.place_id == Place.place_id)
        .outerjoin(ItineraryItem,
                   (ItineraryItem.place_id == Place.place_id)
                   & (ItineraryItem.trip_id == trip_id))
        .where(Place.city_id == trip.city_id,
               ~select(TripDismissal.place_id)
               .where(TripDismissal.trip_id == trip_id,
                      TripDismissal.place_id == Place.place_id)
               .exists())
        .order_by(rank.desc(), Place.rating_count.desc().nullslast(), Place.name)
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()

    place_ids = [r.Place.place_id for r in rows]
    facts = mention_facts(db, place_ids)
    srcs = mention_sources(db, place_ids)
    if category:
        rows = [r for r in rows if facts.get(r.Place.place_id, (None, None))[0] == category]

    places = []
    for r in rows:
        cat, why_go = facts.get(r.Place.place_id, (None, None))
        p = r.Place
        places.append(ShortlistPlaceOut(
            place_id=p.place_id, name=p.name, address=p.address, lat=p.lat, lon=p.lon,
            primary_type=p.primary_type,
            category=cat, why_go=why_go, sources=srcs.get(p.place_id, []),
            mention_count=r.mention_count, in_itinerary=r.day_index is not None,
            day_index=r.day_index,
        ))

    return ShortlistOut(total=rows[0].total if rows else 0, shown=len(places), places=places)


def day_rows(db: Session, trip_id: str,
             day_index: int | None = None) -> list[Row[tuple[ItineraryItem, Place]]]:
    """One day's stored items, or the whole trip's, each joined to its place and in order."""
    stmt = (
        select(ItineraryItem, Place)
        .join(Place, Place.place_id == ItineraryItem.place_id)
        .where(ItineraryItem.trip_id == trip_id)
        .order_by(ItineraryItem.day_index, ItineraryItem.start_min, ItineraryItem.place_id)
    )
    if day_index is not None:
        stmt = stmt.where(ItineraryItem.day_index == day_index)
    return db.execute(stmt).all()


def read_days(db: Session, trip: Trip) -> ItineraryOut:
    """Every day of the trip, empty ones included, so the client never derives the dates itself."""
    rows = day_rows(db, trip.trip_id)
    facts = mention_facts(db, [r.Place.place_id for r in rows])

    days = [DayOut(day_index=i, date=trip.arrive_date + timedelta(days=i), items=[])
            for i in range(day_count(trip))]
    for r in rows:
        item, place = r.ItineraryItem, r.Place
        if item.day_index >= len(days):
            continue
        days[item.day_index].items.append(ItemOut(
            place_id=place.place_id, name=place.name, lat=place.lat, lon=place.lon,
            start_min=item.start_min, duration_min=item.duration_min,
            category=facts.get(place.place_id, (None, None))[0],
            primary_type=place.primary_type,
        ))
    return ItineraryOut(days=days)


def replace_days(db: Session, trip_id: str, body: ItineraryIn) -> ItineraryOut:
    """Replace the listed days wholesale.

    A drag restates a whole day, so a whole day is what gets sent. Times come from the client and are
    stored as given — nothing here reflows a block to make one fit.
    """
    trip = get_trip(db, trip_id)

    if len({d.day_index for d in body.days}) != len(body.days):
        raise HTTPException(422, "a day is listed twice")
    for d in body.days:
        check_day(trip, d.day_index)
        first, last = available_window(trip, d.day_index)
        for item in d.items:
            if item.start_min < first or item.start_min + item.duration_min > last:
                raise HTTPException(
                    422,
                    f"day {d.day_index} is only usable {hhmm(first)}-{hhmm(last)}: "
                    f"{hhmm(item.start_min)} for {item.duration_min} min does not fit",
                )

    place_ids = [i.place_id for d in body.days for i in d.items]
    if len(set(place_ids)) != len(place_ids):
        raise HTTPException(422, "a place is listed twice")

    if place_ids:
        known = set(db.scalars(
            select(Place.place_id).where(Place.place_id.in_(place_ids),
                                         Place.city_id == trip.city_id)
        ).all())
        missing = [p for p in place_ids if p not in known]
        if missing:
            raise HTTPException(422, f"not a place in this city: {missing[0]}")

    # Delete by submitted place_id as well as by day, so dragging a place in from an unlisted day
    # moves it instead of colliding with uq_itinerary_trip_place.
    conditions = [ItineraryItem.day_index.in_([d.day_index for d in body.days])]
    if place_ids:
        conditions.append(ItineraryItem.place_id.in_(place_ids))
    db.execute(delete(ItineraryItem).where(ItineraryItem.trip_id == trip_id, or_(*conditions)))

    for d in body.days:
        for item in d.items:
            db.add(ItineraryItem(trip_id=trip_id, place_id=item.place_id, day_index=d.day_index,
                                 start_min=item.start_min, duration_min=item.duration_min))
    db.commit()

    return read_days(db, trip)


def add_dismissal(db: Session, trip_id: str, place_id: str) -> None:
    """Strike a place off this trip's shortlist — the answer to Google's duplicate listings."""
    trip = get_trip(db, trip_id)
    if not db.scalar(select(func.count()).select_from(Place)
                     .where(Place.place_id == place_id, Place.city_id == trip.city_id)):
        raise HTTPException(422, "not a place in this city")
    db.execute(pg_insert(TripDismissal)
               .values(trip_id=trip_id, place_id=place_id)
               .on_conflict_do_nothing(index_elements=["trip_id", "place_id"]))
    db.commit()


def remove_dismissal(db: Session, trip_id: str, place_id: str) -> None:
    get_trip(db, trip_id)
    db.execute(delete(TripDismissal).where(TripDismissal.trip_id == trip_id,
                                           TripDismissal.place_id == place_id))
    db.commit()


def load_hours(db: Session, place_ids: list[str], fetch: HoursLookup) -> dict[str, PlaceHours]:
    """Cached hours, refetching only what is missing or past its TTL."""
    ttl = timedelta(days=settings().place_hours_ttl_days)
    cutoff = datetime.now(UTC) - ttl
    cached = {
        row.place_id: row
        for row in db.scalars(select(PlaceHours).where(PlaceHours.place_id.in_(place_ids)))
    }
    stale = [p for p in place_ids if p not in cached or cached[p].fetched_at < cutoff]
    if not stale:
        return cached

    try:
        fetched = fetch(stale)
    except PlacesError:
        # Hours we could not reach are simply unknown; plan_day warns rather than failing the day.
        return cached

    now = datetime.now(UTC)
    for pid, hit in fetched.items():
        db.execute(
            pg_insert(PlaceHours)
            .values(place_id=pid, periods=hit.periods,
                    weekday_descriptions=hit.weekday_descriptions,
                    utc_offset_minutes=hit.utc_offset_minutes, fetched_at=now)
            .on_conflict_do_update(
                index_elements=["place_id"],
                set_={"periods": hit.periods, "weekday_descriptions": hit.weekday_descriptions,
                      "utc_offset_minutes": hit.utc_offset_minutes, "fetched_at": now})
        )
    db.commit()
    return {
        row.place_id: row
        for row in db.scalars(select(PlaceHours).where(PlaceHours.place_id.in_(place_ids)))
    }


def _route_legs(compute: RouteCompute, place_ids: list[str], mode: str,
                depart_iso: str) -> tuple[RouteResult, list[TravelLeg], bool]:
    """The day's travel legs, and whether they are real. One `computeRoutes` call at most."""
    if len(place_ids) < 2:
        # Nothing to route between, so spend nothing.
        return RouteResult(legs=[], polyline=None, total_seconds=0, total_meters=0), [], True

    try:
        result = compute(place_ids, mode, depart_iso)
    except RoutesError as e:
        raise HTTPException(502, f"routing failed: {e}") from e

    legs = [TravelLeg(seconds=leg.seconds, meters=leg.meters,
                      transit_steps=leg.transit_steps, polyline=leg.polyline)
            for leg in result.legs]
    if not legs:
        # Beyond the transit horizon Routes answers 200 with nothing, which is an absent answer and
        # not a failure. Lay the day out end to end and say the times are not travel-adjusted.
        return result, [TravelLeg(seconds=0, meters=0) for _ in place_ids[:-1]], False
    return result, legs, True


def route_day(db: Session, trip_id: str, day_index: int, body: RouteDayRequest,
              fetch_hours: HoursLookup, compute: RouteCompute) -> DayRouteOut:
    """Route one day in the order it is stored, then say what does not work.

    Synchronous rather than queued: routing has no budget to pace, one walking day is a single call,
    and the user is waiting on the answer. The stop cap is what bounds the worst case.
    """
    trip = get_trip(db, trip_id)
    day_date = check_day(trip, day_index)
    city = trip.city
    rows = day_rows(db, trip_id, day_index)

    provisional = provisional_reasons(day_date)

    if not rows:
        return DayRouteOut(day_index=day_index, date=day_date, mode=body.mode,
                           provisional=provisional)

    if len(rows) > settings().max_stops_per_day:
        raise HTTPException(422, f"a day takes at most {settings().max_stops_per_day} stops")

    # The day starts when its first block does. Rows are already in time order.
    start = time(rows[0].ItineraryItem.start_min // 60, rows[0].ItineraryItem.start_min % 60)

    place_ids = [r.Place.place_id for r in rows]
    facts = mention_facts(db, place_ids)
    hours = load_hours(db, place_ids, fetch_hours)

    tz_min = tz_minutes(
        city, day_date,
        next((h.utc_offset_minutes for h in hours.values() if h.utc_offset_minutes is not None),
             None),
    )
    result, legs, routed = _route_legs(compute, place_ids, body.mode,
                                       depart_instant(day_date, start, tz_min))
    warnings: list[PlanWarning] = ([] if routed
                                   else [PlanWarning("no_route", None, {"mode": body.mode})])

    sunrise, sunset = (None, None)
    if city.lat is not None and city.lon is not None:
        sunrise, sunset = sun_times(day_date, city.lat, city.lon, tz_min)

    stops = [
        Stop(place_id=r.Place.place_id, name=r.Place.name,
             category=facts.get(r.Place.place_id, (None, None))[0],
             start_min=r.ItineraryItem.start_min, duration_min=r.ItineraryItem.duration_min,
             periods=hours[r.Place.place_id].periods if r.Place.place_id in hours else None)
        for r in rows
    ]
    plan = plan_day(stops, legs, weekday=google_weekday(day_date),
                    sunset_min=sunset, routed=routed, mode=body.mode)

    return DayRouteOut(
        day_index=day_index, date=day_date, mode=body.mode, start_time=start,
        blocks=[BlockOut(place_id=b.place_id, name=b.name, start=hhmm(b.start_min),
                         end=hhmm(b.end_min), duration_min=b.duration_min,
                         open_from=hhmm(b.open_from) if b.open_from is not None else None,
                         open_to=hhmm(b.open_to) if b.open_to is not None else None)
                for b in plan.blocks],
        legs=[LegOut(from_place_id=place_ids[i], to_place_id=place_ids[i + 1],
                     seconds=leg.seconds, meters=leg.meters,
                     transit_steps=leg.transit_steps, polyline=leg.polyline)
              for i, leg in enumerate(legs) if i + 1 < len(place_ids)],
        polyline=result.polyline,
        total_distance_m=result.total_meters,
        total_travel_s=result.total_seconds,
        routed=routed,
        daylight=(DaylightOut(sunrise=hhmm(sunrise), sunset=hhmm(sunset))
                  if sunrise is not None and sunset is not None else None),
        warnings=[WarningOut(code=w.code, place_id=w.place_id, detail=w.detail)
                  for w in warnings + plan.warnings],
        provisional=provisional,
    )
