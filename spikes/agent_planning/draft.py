"""THROWAWAY SPIKE: one Gemini call drafts a first itinerary, which the user then drags into shape.

    cd tp_backend && .venv/bin/python ../spikes/agent_planning/draft.py <trip_id> [--dry]
"""

import sys
from datetime import timedelta

from libs.db import Trip, session
from libs.gemini import generate
from libs.prompts.registry import Prompt
from libs.routing import SLOT_MIN as SLOT
from libs.routing import Stop, fetch_hours, hhmm, plan_day, sun_times
from libs.routing.plan import CLOSED_TODAY, CLOSES_BEFORE_DONE, OPENS_LATER
from tp_api.route_planning.service import load_hours, shortlist
from tp_api.route_planning.utils import available_window, day_count, google_weekday, tz_minutes
from tp_ingestions import limits
from tp_ingestions.places.names import distance_km

LIMIT = 40
CAP = 5  # not settings().max_stops_per_day (25) — that bounds a route, not a draft
GRID = (8 * 60, 23 * 60)  # DAY_START_MIN/DAY_END_MIN in plan-types.ts; outside it a block cannot draw
ROUNDS = 3
MUST_FIX = {CLOSED_TODAY, OPENS_LATER, CLOSES_BEFORE_DONE}

SCHEMA = {
    "type": "object",
    "properties": {
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer"},
                    "picks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "start_min": {"type": "integer"},
                                "duration_min": {"type": "integer"},
                            },
                            "required": ["index", "start_min", "duration_min"],
                        },
                    },
                },
                "required": ["day", "picks"],
            },
        }
    },
    "required": ["days"],
}

TEMPLATE = """Draft a first-pass itinerary. The traveller will rearrange it themselves afterwards,
so a reasonable starting arrangement beats a clever one.

{city}
The traveller says: {traveller}

{days_line}

Fill only these days: {open_days}. The others are already arranged and are not yours to touch.
At most {cap} places per day. Use each place at most once across the whole trip.

You decide the clock. For every place give:
  start_min      when the traveller arrives, in minutes after local midnight (09:30 is 570)
  duration_min   how long they stay, at least 30

Both must be multiples of 30. Every block must fit inside its day's usable range above:
start_min is at or after the range's first minute, and start_min + duration_min is at or before its
last. A day's blocks must not overlap, and you must leave a gap between them for getting across
town — 10 to 20 minutes on foot in the centre, and an hour each way for anything listed far out.

"km" is straight-line distance from the city centre. Past about 5km a place is an excursion that
eats most of a day. Things that need darkness belong after sunset; things that need daylight do not.

Places, by index:
{places}

Return the days you filled and the places you chose, each with its own times. Choose for this
traveller rather than for coverage — leaving a famous place out is correct if they would not enjoy
it. Never invent an index.
{feedback}"""

DRAFT = Prompt(name="itinerary_draft", version="v1", template=TEMPLATE, schema=SCHEMA)


def window(trip, day_index):
    """The flight window, narrowed to the hours the client's grid can actually draw."""
    first, last = available_window(trip, day_index)
    return max(first, GRID[0]), min(last, GRID[1])


def snap(m):
    return int(round((m or 0) / SLOT) * SLOT)


def clock(m):
    # hhmm wraps modulo 24, which would print a midnight upper bound as 00:00.
    return "24:00" if m >= 24 * 60 else hhmm(m)


def render(trip, places, open_days, feedback=""):
    """The whole prompt: the candidates, and the clock facts the model needs to time them."""
    city = trip.city
    rows = []
    for i, p in enumerate(places):
        km = distance_km(city.lat, city.lon, p.lat, p.lon) if p.lat and city.lat else 0.0
        rows.append(f"{i:3}  {p.name} | {p.category or '-'} | {km:.1f}km | {p.mention_count} sources"
                    + (f" | {p.why_go}" if p.why_go else ""))

    days = []
    for i in range(day_count(trip)):
        d = trip.arrive_date + timedelta(days=i)
        first, last = window(trip, i)
        line = (f"day {i}, {d:%A %d %B}: usable {clock(first)}-{clock(last)} "
                f"(start_min {first} to {last})")
        if city.lat is not None and city.lon is not None:
            rise, set_ = sun_times(d, city.lat, city.lon, tz_minutes(city, d, None))
            if rise is not None:
                line += f", sunrise {hhmm(rise)}, sunset {hhmm(set_)}"
        days.append(line)

    return DRAFT.render(
        city=f"{city.name}, {city.country}",
        days_line="\n".join(days),
        traveller=trip.extra_details or "nothing in particular",
        open_days=", ".join(str(d) for d in open_days),
        cap=CAP,
        places="\n".join(rows),
        feedback=feedback,
    )


def problems(s, trip, chosen, places):
    """plan_day's hours verdict per day. routed=False, so the loop spends no Routes quota."""
    ids = [places[i].place_id for picks in chosen.values() for i, _, _ in picks]
    hours = load_hours(s, ids, fetch_hours) if ids else {}

    out = {}
    for day, picks in chosen.items():
        stops = [Stop(place_id=places[i].place_id, name=places[i].name, category=places[i].category,
                      start_min=st, duration_min=du,
                      periods=getattr(hours.get(places[i].place_id), "periods", None))
                 for i, st, du in picks]
        plan = plan_day(stops, [], weekday=google_weekday(trip.arrive_date + timedelta(days=day)),
                        routed=False)
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


def draft(s, trip, places, open_days):
    """Propose, let plan_day judge, hand back the named violations.

    Stops clean, or the first round that fails to beat the best so far, and always returns that best.
    """
    best, fewest, feedback, shut = ({}, {}), None, "", set()
    for r in range(1, ROUNDS + 1):
        limits.gemini().take()
        reply = generate(DRAFT, render(trip, places, open_days, feedback))
        chosen = keep(trip, reply, len(places), open_days, shut)
        bad = problems(s, trip, chosen, places)

        n = sum(map(len, bad.values()))
        print(f"  round {r}: {n} outside opening hours")
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


def keep(trip, reply, n, open_days, shut=()):
    """Refuse what replace_days would 422 — bad index, bad day, repeat, off-grid, no fit — and
    anything already proven closed all day, which no amount of asking stops the model reusing."""
    out, seen = {}, set()
    for d in reply.get("days", []):
        day = d.get("day")
        if day not in open_days:
            continue
        first, last = window(trip, day)
        floor = -(-first // SLOT) * SLOT  # ceiling-divide: first grid minute at or after landing

        chosen = []
        for it in d.get("picks") or []:
            i = it.get("index")
            if not isinstance(i, int) or not 0 <= i < n or i in seen or (day, i) in shut:
                continue
            start = max(floor, snap(it.get("start_min", floor)))
            dur = max(SLOT, snap(it.get("duration_min", 60)))
            if start + dur > last:
                continue
            seen.add(i)
            chosen.append((i, start, dur))
        out[day] = sorted(chosen, key=lambda c: c[1])[:CAP]
    return out


def main(trip_id, dry=False):
    with session() as s:
        trip = s.get(Trip, trip_id)
        if trip is None:
            raise SystemExit(f"no such trip: {trip_id}")

        placed = shortlist(s, trip_id, LIMIT, 0, None).places
        free = [p for p in placed if not p.in_itinerary]
        taken = {p.day_index for p in placed if p.in_itinerary}
        open_days = [i for i in range(day_count(trip)) if i not in taken]

        print(f"{trip.city.name}: {len(free)} free of {len(placed)}, open days {open_days}")
        if dry:
            print(render(trip, free, open_days))
            return

        chosen, rounds, bad = draft(s, trip, free, open_days)
        print(f"{'clean' if not bad else 'gave up with ' + str(sum(map(len, bad.values()))) + ' left'}"
              f" after {rounds} round(s)")

        for day, picks in sorted(chosen.items()):
            first, last = window(trip, day)
            print(f"\nday {day}  ({clock(first)}-{clock(last)})")
            for i, start, dur in picks:
                print(f"  {hhmm(start)}-{hhmm(start + dur)}  {free[i].name}"
                      f"  ({free[i].category or '-'})")
            for _, _, line in bad.get(day, []):
                print(f"  ! {line}")


def check():
    from datetime import date, time
    trip = Trip(arrive_date=date(2026, 9, 19), depart_date=date(2026, 9, 20),
                arrive_time=time(14, 45), depart_time=None)
    reply = {"days": [
        {"day": 0, "picks": [
            {"index": 0, "start_min": 600, "duration_min": 60},   # before landing -> floored to 15:00
            {"index": 99, "start_min": 900, "duration_min": 60},  # index we never sent
            {"index": 1, "start_min": 1010, "duration_min": 47},  # off grid both ways
            {"index": 1, "start_min": 1200, "duration_min": 60},  # repeat
            {"index": 2, "start_min": 1410, "duration_min": 60},  # runs past midnight
        ]},
        {"day": 1, "picks": [{"index": 3, "start_min": 600, "duration_min": 60}]},  # day not offered
    ]}
    assert keep(trip, reply, 4, [0]) == {0: [(0, 900, 60), (1, 1020, 60)]}
    assert keep(trip, {"days": []}, 4, [0]) == {}
    print("ok")


if __name__ == "__main__":
    if sys.argv[1] == "--check":
        check()
    else:
        main(sys.argv[1], "--dry" in sys.argv)
