"""route.plan — draft a first itinerary into a trip's empty days, so the plan screen opens filled.

The model picks the places and owns the clock. plan_day then judges the result against real opening
hours and the named violations go back for one more attempt; nothing here reflows a block itself.
The loop only judges hours, so it spends no Places quota beyond the ones it reads.
"""

import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from libs.db import City, IngestTask, ItineraryItem, Trip, trip_cities
from libs.db.enums import TaskKind
from libs.gemini import generate
from libs.places import distance_km
from libs.prompts import ITINERARY_DRAFT
from libs.routing import SLOT_MIN, Stop, fetch_hours, hhmm, plan_day
from libs.routing.plan import CLOSED_TODAY, CLOSES_BEFORE_DONE, OPENS_LATER
from tp_api.route_planning.schemas import DayIn, ItemIn, ItineraryIn
from tp_api.route_planning.service import (
    filled_days,
    load_hours,
    lock_itinerary,
    replace_days,
    shortlist,
)
from tp_api.route_planning.utils import (
    available_window,
    day_count,
    google_weekday,
)
from tp_ingestions import limits
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.registry import handles

log = logging.getLogger("route.plan")

LIMIT = 40
CAP = 5
ROUNDS = 3
GRID = (8 * 60, 23 * 60)  # the waking day a draft schedules in; the client grid draws all 24h
MUST_FIX = {CLOSED_TODAY, OPENS_LATER, CLOSES_BEFORE_DONE}


def window(trip: Trip, day_index: int) -> tuple[int, int]:
    """The flight window, narrowed to the waking day."""
    first, last = available_window(trip, day_index)
    return max(first, GRID[0]), min(last, GRID[1])


def snap(m) -> int:
    return int(round((m or 0) / SLOT_MIN) * SLOT_MIN)


def clock(m: int) -> str:
    # hhmm wraps modulo 24, which would print a midnight upper bound as 00:00.
    return "24:00" if m >= 24 * 60 else hhmm(m)


def render(session: Session, trip: Trip, places, open_days, feedback: str = "") -> str:
    """The whole prompt: the candidates, and the clock facts the model needs to time them."""
    cities = trip_cities(session, trip)
    by_id = {c.city_id: c for c in cities}
    missing = {p.city_id for p in places} - set(by_id)
    if missing:
        by_id |= {c.city_id: c
                  for c in session.scalars(select(City).where(City.city_id.in_(missing)))}

    rows = []
    for i, p in enumerate(places):
        c = by_id.get(p.city_id)
        known = None not in (getattr(c, "lat", None), getattr(c, "lon", None), p.lat, p.lon)
        km = distance_km(c.lat, c.lon, p.lat, p.lon) if known else None
        rows.append(f"{i:3}  {p.name} | {p.category or '-'} | {c.name if c else '?'} | "
                    f"{'?' if km is None else format(km, '.1f')}km | {p.mention_count} sources"
                    + (f" | {p.why_go}" if p.why_go else ""))

    days = []
    for i in range(day_count(trip)):
        d = trip.arrive_date + timedelta(days=i)
        first, last = window(trip, i)
        line = (f"day {i}, {d:%A %d %B}: usable {clock(first)}-{clock(last)} "
                f"(start_min {first} to {last})")
        days.append(line)

    return ITINERARY_DRAFT.render(
        city=" and ".join(f"{c.name}, {c.country}" for c in cities),
        days_line="\n".join(days),
        traveller=trip.extra_details or "nothing in particular",
        open_days=", ".join(str(d) for d in open_days),
        cap=CAP,
        places="\n".join(rows),
        feedback=feedback,
    )


def keep(trip: Trip, reply: dict, n: int, open_days, shut=()) -> dict:
    """Refuse what replace_days would 422 — bad index, bad day, repeat, off-grid, no fit — and
    anything already proven closed all day, which no amount of asking stops the model reusing."""
    out, seen = {}, set()
    for d in reply.get("days") or []:
        day = d.get("day")
        if day not in open_days:
            continue
        first, last = window(trip, day)
        floor = -(-first // SLOT_MIN) * SLOT_MIN  # ceiling-divide: first grid minute after landing

        chosen = []
        for it in d.get("picks") or []:
            i = it.get("index")
            if not isinstance(i, int) or not 0 <= i < n or i in seen or (day, i) in shut:
                continue
            start = max(floor, snap(it.get("start_min", floor)))
            dur = max(SLOT_MIN, snap(it.get("duration_min", 60)))
            if start + dur > last:
                continue
            seen.add(i)
            chosen.append((i, start, dur))
        out[day] = sorted(chosen, key=lambda c: c[1])[:CAP]
    return out


def problems(session: Session, trip: Trip, chosen: dict, places) -> dict:
    """plan_day's hours verdict per day."""
    ids = [places[i].place_id for picks in chosen.values() for i, _, _ in picks]
    hours = load_hours(session, ids, fetch_hours) if ids else {}

    out = {}
    for day, picks in chosen.items():
        stops = [Stop(place_id=places[i].place_id, name=places[i].name,
                      start_min=st, duration_min=du,
                      periods=getattr(hours.get(places[i].place_id), "periods", None))
                 for i, st, du in picks]
        plan = plan_day(stops, weekday=google_weekday(trip.arrive_date + timedelta(days=day)))
        block = {b.place_id: b for b in plan.blocks}
        at = {places[i].place_id: i for i, _, _ in picks}

        lines = []
        for w in plan.warnings:
            b = block.get(w.place_id)
            if w.code not in MUST_FIX or b is None:
                continue
            fix = (f"is open only {hhmm(b.open_from)}-{hhmm(b.open_to)} — move it inside that"
                   if b.open_from is not None
                   else "is closed all day — replace it, no time works")
            lines.append((at[w.place_id], b.open_from is None,
                          f"{b.name} is booked {hhmm(b.start_min)}-{hhmm(b.end_min)} but {fix}"))
        if lines:
            out[day] = lines
    return out


def propose(session: Session, trip: Trip, places, open_days) -> tuple[dict, int, dict]:
    """Propose, let plan_day judge, hand back the named violations.

    Stops clean, or the first round that fails to beat the best so far, and always returns that best.
    """
    best, fewest, feedback, shut = ({}, {}), None, "", set()
    for r in range(1, ROUNDS + 1):
        limits.gemini().take()
        reply = generate(ITINERARY_DRAFT, render(session, trip, places, open_days, feedback))
        chosen = keep(trip, reply, len(places), open_days, shut)
        bad = problems(session, trip, chosen, places)

        n = sum(map(len, bad.values()))
        gained = fewest is None or n < fewest
        if gained:
            best, fewest = (chosen, bad), n
        if n == 0 or not gained:
            return best[0], r, best[1]

        shut |= {(d, i) for d, lines in bad.items() for i, allday, _ in lines if allday}
        feedback = "\n".join(
            [("\nYour last attempt scheduled these outside opening hours. Fix exactly these and "
              "leave every other block where it is.")]
            + [f"  day {d}: {ln}" for d, lines in sorted(bad.items()) for _, _, ln in lines])
    return best[0], ROUNDS, best[1]


# Why a draft wrote nothing. The client owns the English.
NO_TRIP = "no_trip"
ALREADY_PLANNING = "already_planning"
ALL_DAYS_FILLED = "all_days_filled"
NO_PLACES = "no_places"
NOTHING_FIT = "nothing_fit"


@handles(TaskKind.ROUTE_PLAN)
def run(session: Session, task: ClaimedTask) -> dict:
    out = draft(session, task.payload["trip_id"], manual=bool(task.payload.get("manual")))
    session.execute(update(IngestTask).where(IngestTask.task_id == task.task_id).values(result=out))
    return out


def draft(session: Session, trip_id: str, manual: bool) -> dict:
    """Fill a trip's empty days. A day with anything on it is the user's, and the automatic draft
    stands down entirely once the user has started planning."""
    trip = session.get(Trip, trip_id)
    if trip is None or trip.deleted:
        return {"skipped": NO_TRIP}

    filled = filled_days(session, trip_id)
    if filled and not manual:
        return {"skipped": ALREADY_PLANNING}
    open_days = [i for i in range(day_count(trip)) if i not in filled]
    if not open_days:
        return {"skipped": ALL_DAYS_FILLED}

    limit = LIMIT * len(trip_cities(session, trip))
    places = [p for p in shortlist(session, trip_id, limit, 0, None).places if not p.in_itinerary]
    if not places:
        return {"skipped": NO_PLACES}

    chosen, rounds, bad = propose(session, trip, places, open_days)

    # The model takes seconds and the user may have planned meanwhile.
    lock_itinerary(session, trip_id)
    now_filled = filled_days(session, trip_id)
    if now_filled and not manual:
        return {"skipped": ALREADY_PLANNING}
    planned = set(session.scalars(
        select(ItineraryItem.place_id).where(ItineraryItem.trip_id == trip_id,
                                             ItineraryItem.place_id.is_not(None))).all())
    days = [DayIn(day_index=day,
                  items=[ItemIn(place_id=places[i].place_id, start_min=st, duration_min=du)
                         for i, st, du in picks if places[i].place_id not in planned])
            for day, picks in sorted(chosen.items()) if day not in now_filled]
    days = [d for d in days if d.items]
    if not days:
        return {"skipped": NOTHING_FIT, "rounds": rounds}

    replace_days(session, trip_id, ItineraryIn(days=days))
    log.info("drafted %d day(s) for %s in %d round(s)", len(days), trip_id[:8], rounds)
    out = {"days": len(days), "blocks": sum(len(d.items) for d in days), "rounds": rounds,
           "unresolved": sum(map(len, bad.values()))}
    if lost := sorted(set(chosen) & (now_filled - filled)):
        out["filled_meanwhile"] = lost
    return out
