"""The planning screen's API: a ranked shortlist, the user's ordering, and one routed day.

The order is the user's. Nothing here reorders anything — routing follows the sequence it is given
and the warnings say what does not work.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, distinct, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from libs.db import City, ItineraryItem, Place, PlaceHours, PlaceMention, Trip, TripDismissal
from libs.db.enums import Sentiment
from libs.places import PlacesError
from libs.routing import (
    PlanWarning,
    RouteResult,
    RoutesError,
    Stop,
    TravelLeg,
    duration_for,
    hhmm,
    plan_day,
    sun_times,
)
from libs.settings import settings
from tp_api.deps import (
    HoursLookup,
    RouteCompute,
    db_session,
    hours_lookup,
    route_compute,
)
from tp_api.plan_schemas import (
    BlockOut,
    DaylightOut,
    DayOut,
    DayRouteOut,
    DismissalIn,
    ItemOut,
    ItineraryIn,
    ItineraryOut,
    LegOut,
    RouteDayRequest,
    ShortlistOut,
    ShortlistPlaceOut,
    WarningOut,
    provisional_reasons,
)

router = APIRouter()

Db = Annotated[Session, Depends(db_session)]
Hours = Annotated[HoursLookup, Depends(hours_lookup)]
Route = Annotated[RouteCompute, Depends(route_compute)]

DEFAULT_START = time(9, 0)


def _trip(db: Session, trip_id: str) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "no such trip")
    return trip


def _day_count(trip: Trip) -> int:
    return (trip.depart_date - trip.arrive_date).days + 1


def _google_weekday(d: date) -> int:
    """Places numbers weekdays from Sunday; Python numbers them from Monday."""
    return (d.weekday() + 1) % 7


def _check_day(trip: Trip, day_index: int) -> date:
    if not 0 <= day_index < _day_count(trip):
        raise HTTPException(422, f"day {day_index} is outside the trip")
    return trip.arrive_date + timedelta(days=day_index)


def _mention_facts(db: Session, place_ids: Sequence[str]) -> dict[str, tuple[str | None, str | None]]:
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


@router.get("/trips/{trip_id}/shortlist", response_model=ShortlistOut)
def get_shortlist(
    trip_id: str,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 40,
    offset: Annotated[int, Query(ge=0)] = 0,
    category: Annotated[str | None, Query(max_length=16)] = None,
) -> ShortlistOut:
    """The city's places, ranked by how many independent sources mentioned each one."""
    trip = _trip(db, trip_id)

    mentions = (
        select(PlaceMention.place_id.label("place_id"),
               func.count().label("mention_count"),
               func.array_agg(distinct(PlaceMention.source)).label("sources"))
        .group_by(PlaceMention.place_id)
        .subquery()
    )
    rank = func.coalesce(mentions.c.mention_count, 0)

    stmt = (
        select(Place, rank.label("mention_count"), mentions.c.sources,
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

    facts = _mention_facts(db, [r.Place.place_id for r in rows])
    if category:
        rows = [r for r in rows if facts.get(r.Place.place_id, (None, None))[0] == category]

    places = []
    for r in rows:
        cat, why_go = facts.get(r.Place.place_id, (None, None))
        p = r.Place
        places.append(ShortlistPlaceOut(
            place_id=p.place_id, name=p.name, address=p.address, lat=p.lat, lon=p.lon,
            rating=p.rating, rating_count=p.rating_count, primary_type=p.primary_type,
            category=cat, why_go=why_go, sources=sorted(r.sources or []),
            mention_count=r.mention_count, in_itinerary=r.day_index is not None,
            day_index=r.day_index, default_duration_min=duration_for(cat),
        ))

    return ShortlistOut(total=rows[0].total if rows else 0, shown=len(places), places=places)


def _read_days(db: Session, trip: Trip) -> list[DayOut]:
    rows = db.execute(
        select(ItineraryItem, Place)
        .join(Place, Place.place_id == ItineraryItem.place_id)
        .where(ItineraryItem.trip_id == trip.trip_id)
        .order_by(ItineraryItem.day_index, ItineraryItem.position)
    ).all()
    facts = _mention_facts(db, [r.Place.place_id for r in rows])

    days = [DayOut(day_index=i, date=trip.arrive_date + timedelta(days=i), items=[])
            for i in range(_day_count(trip))]
    for r in rows:
        item, place = r.ItineraryItem, r.Place
        if item.day_index >= len(days):
            continue
        days[item.day_index].items.append(ItemOut(
            place_id=place.place_id, name=place.name, lat=place.lat, lon=place.lon,
            position=item.position, duration_min=item.duration_min,
            category=facts.get(place.place_id, (None, None))[0],
            primary_type=place.primary_type,
        ))
    return days


@router.get("/trips/{trip_id}/itinerary", response_model=ItineraryOut)
def get_itinerary(trip_id: str, db: Db) -> ItineraryOut:
    """Every day of the trip, empty ones included, so the client never derives the dates itself."""
    return ItineraryOut(days=_read_days(db, _trip(db, trip_id)))


@router.put("/trips/{trip_id}/itinerary", response_model=ItineraryOut)
def put_itinerary(trip_id: str, body: ItineraryIn, db: Db) -> ItineraryOut:
    """Replace the listed days wholesale.

    A drag is a statement about a whole sequence, so the whole sequence is what gets sent: positions
    are renumbered densely here and a partial write cannot leave a day with gaps or collisions.
    """
    trip = _trip(db, trip_id)

    if len({d.day_index for d in body.days}) != len(body.days):
        raise HTTPException(422, "a day is listed twice")
    for d in body.days:
        _check_day(trip, d.day_index)

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
        for position, item in enumerate(d.items):
            db.add(ItineraryItem(trip_id=trip_id, place_id=item.place_id, day_index=d.day_index,
                                 position=position, duration_min=item.duration_min))
    db.commit()

    return ItineraryOut(days=_read_days(db, trip))


@router.post("/trips/{trip_id}/dismissals", status_code=204)
def add_dismissal(trip_id: str, body: DismissalIn, db: Db) -> None:
    """Strike a place off this trip's shortlist — the answer to Google's duplicate listings."""
    trip = _trip(db, trip_id)
    if not db.scalar(select(func.count()).select_from(Place)
                     .where(Place.place_id == body.place_id, Place.city_id == trip.city_id)):
        raise HTTPException(422, "not a place in this city")
    db.execute(pg_insert(TripDismissal)
               .values(trip_id=trip_id, place_id=body.place_id)
               .on_conflict_do_nothing(index_elements=["trip_id", "place_id"]))
    db.commit()


@router.delete("/trips/{trip_id}/dismissals/{place_id}", status_code=204)
def remove_dismissal(trip_id: str, place_id: str, db: Db) -> None:
    _trip(db, trip_id)
    db.execute(delete(TripDismissal).where(TripDismissal.trip_id == trip_id,
                                           TripDismissal.place_id == place_id))
    db.commit()


def _tz_minutes(city: City, on: date, fallback: int | None) -> int:
    """The city's UTC offset on the trip's date, so a summer plan is not shifted by winter time."""
    if city.timezone:
        try:
            offset = datetime.combine(on, time(12, 0), ZoneInfo(city.timezone)).utcoffset()
        except (ZoneInfoNotFoundError, ValueError):
            offset = None
        if offset is not None:
            return int(offset.total_seconds() // 60)
    return fallback or 0


def _load_hours(db: Session, place_ids: list[str], fetch: HoursLookup) -> dict[str, PlaceHours]:
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
                    utc_offset_minutes=hit.utc_offset_minutes, has_hours=hit.has_hours,
                    fetched_at=now)
            .on_conflict_do_update(
                index_elements=["place_id"],
                set_={"periods": hit.periods, "weekday_descriptions": hit.weekday_descriptions,
                      "utc_offset_minutes": hit.utc_offset_minutes, "has_hours": hit.has_hours,
                      "fetched_at": now})
        )
    db.commit()
    return {
        row.place_id: row
        for row in db.scalars(select(PlaceHours).where(PlaceHours.place_id.in_(place_ids)))
    }


@router.post("/trips/{trip_id}/days/{day_index}/route", response_model=DayRouteOut)
def route_day(
    trip_id: str,
    day_index: int,
    body: RouteDayRequest,
    db: Db,
    fetch_hours: Hours,
    compute: Route,
) -> DayRouteOut:
    """Route one day in the order it is stored, then say what does not work.

    Synchronous rather than queued: routing has no budget to pace, one walking day is a single call,
    and the user is waiting on the answer. The stop cap is what bounds the worst case.
    """
    trip = _trip(db, trip_id)
    day_date = _check_day(trip, day_index)
    city = trip.city

    rows = db.execute(
        select(ItineraryItem, Place)
        .join(Place, Place.place_id == ItineraryItem.place_id)
        .where(ItineraryItem.trip_id == trip_id, ItineraryItem.day_index == day_index)
        .order_by(ItineraryItem.position)
    ).all()

    # Day 0 cannot start before the flight lands; later days have no such anchor.
    start = body.start_time or (trip.arrive_time if day_index == 0 else None) or DEFAULT_START
    provisional = provisional_reasons(day_date)

    if not rows:
        return DayRouteOut(day_index=day_index, date=day_date, mode=body.mode, start_time=start,
                           provisional=provisional)

    if len(rows) > settings().max_stops_per_day:
        raise HTTPException(422, f"a day takes at most {settings().max_stops_per_day} stops")

    place_ids = [r.Place.place_id for r in rows]
    facts = _mention_facts(db, place_ids)
    hours = _load_hours(db, place_ids, fetch_hours)

    tz_min = _tz_minutes(
        city, day_date,
        next((h.utc_offset_minutes for h in hours.values() if h.utc_offset_minutes is not None),
             None),
    )
    start_min = start.hour * 60 + start.minute
    # Transit times are time-dependent, so the departure has to be a real instant: the spike's
    # naive "<date>T<start>Z" asked for a route two hours out from what the user meant.
    depart_iso = datetime.combine(day_date, start,
                                  tzinfo=timezone(timedelta(minutes=tz_min))).isoformat()

    warnings: list[PlanWarning] = []
    routed = True
    if len(place_ids) < 2:
        # Nothing to route between, so spend nothing.
        result = RouteResult(legs=[], polyline=None, total_seconds=0, total_meters=0)
    else:
        try:
            result = compute(place_ids, body.mode, depart_iso)
        except RoutesError as e:
            raise HTTPException(502, f"routing failed: {e}") from e

    legs = [TravelLeg(seconds=leg.seconds, meters=leg.meters,
                      transit_steps=leg.transit_steps, polyline=leg.polyline)
            for leg in result.legs]
    if len(place_ids) > 1 and not legs:
        # Beyond the transit horizon Routes answers 200 with nothing, which is an absent answer and
        # not a failure. Lay the day out end to end and say the times are not travel-adjusted.
        routed = False
        legs = [TravelLeg(seconds=0, meters=0) for _ in place_ids[:-1]]
        warnings.append(PlanWarning("no_route", None, {"mode": body.mode}))

    sunrise, sunset = (None, None)
    if city.lat is not None and city.lon is not None:
        sunrise, sunset = sun_times(day_date, city.lat, city.lon, tz_min)

    stops = [
        Stop(place_id=r.Place.place_id, name=r.Place.name,
             category=facts.get(r.Place.place_id, (None, None))[0],
             duration_min=r.ItineraryItem.duration_min,
             periods=hours[r.Place.place_id].periods if r.Place.place_id in hours else None)
        for r in rows
    ]
    plan = plan_day(stops, legs, weekday=_google_weekday(day_date), start_min=start_min,
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
