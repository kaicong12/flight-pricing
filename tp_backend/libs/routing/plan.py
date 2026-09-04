"""Check one day of pinned activity blocks and say what is wrong with it.

Pure: the caller supplies the travel legs, the hours and the daylight, so this never touches the
network and the whole of the validation is testable.

Every block carries its own start time. Nothing here derives a time and nothing here moves a block —
the user put it at 14:00, so it stays at 14:00 and the warnings say what does not work.
"""

from dataclasses import dataclass, field

from libs.routing.hours import CLOSED, Window, window_for

# The grid the client drags against, so a duration is always a whole number of slots.
SLOT_MIN = 30
MIN_DURATION = SLOT_MIN

DEFAULT_DURATION = 60

# Categories worth doing in daylight. A closed museum is a hard failure; a dark viewpoint is a
# wasted trip, which is the same problem one step softer.
OUTDOOR = {"see", "do"}

# Warning codes. The client owns the English.
CLOSED_TODAY = "closed"
OPENS_LATER = "opens_later"
CLOSES_BEFORE_DONE = "closes_before_done"
AFTER_SUNSET = "after_sunset"
NO_HOURS = "no_hours"
NO_ROUTE = "no_route"
IMPLAUSIBLE_LEG = "implausible_leg"
TRAVEL_DOES_NOT_FIT = "travel_does_not_fit"

# Faster than anyone walks, so the leg is really crossing water. Google routes the Suomenlinna
# ferry as a walk at 19 km/h with no wait and no timetable, tagged only as a toll — and the tag is
# not reliable enough to ask for. Implied speed catches every scheduled crossing instead.
MAX_WALK_KMH = 9.0


@dataclass(frozen=True)
class Stop:
    """One place on a day, at the time the user pinned it to."""

    place_id: str
    name: str
    category: str | None
    start_min: int
    duration_min: int
    periods: list[dict] | None = None  # None = never fetched; [] = Places publishes none


@dataclass(frozen=True)
class TravelLeg:
    seconds: int
    meters: int
    transit_steps: list[str] = field(default_factory=list)
    polyline: str | None = None


@dataclass(frozen=True)
class Block:
    place_id: str
    name: str
    start_min: int
    end_min: int
    duration_min: int
    open_from: int | None
    open_to: int | None


@dataclass(frozen=True)
class PlanWarning:
    code: str
    place_id: str | None
    detail: dict


@dataclass(frozen=True)
class DayPlan:
    blocks: list[Block]
    warnings: list[PlanWarning]
    finish_min: int


def hhmm(minutes: float) -> str:
    """Local minutes past midnight as HH:MM, wrapping a day that runs past midnight."""
    m = int(minutes)
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def implausible_walk(seconds: int, meters: int) -> bool:
    """Whether a walking leg is too fast to be walked, and so is really a boat."""
    if seconds <= 0 or meters <= 0:
        return False
    return (meters / seconds) * 3.6 > MAX_WALK_KMH


def in_time_order(stops: list[Stop]) -> list[Stop]:
    """The day's sequence. place_id breaks a tie, because two blocks may share a start time."""
    return sorted(stops, key=lambda s: (s.start_min, s.place_id))


def plan_day(
    stops: list[Stop],
    legs: list[TravelLeg],
    *,
    weekday: int,
    sunset_min: float | None = None,
    routed: bool = True,
    mode: str = "walk",
) -> DayPlan:
    """Validate a day of pinned blocks.

    `stops` may arrive in any order; `legs[i]` is the travel between the i-th and (i+1)-th stop
    **in time order**, which is what the caller routed. `weekday` is Google's 0=Sunday.
    `routed=False` means no travel times were available, so the travel checks are skipped rather
    than guessed at — the caller says so with its own warning.
    """
    ordered = in_time_order(stops)
    blocks: list[Block] = []
    warnings: list[PlanWarning] = []

    for i, stop in enumerate(ordered):
        end_min = stop.start_min + stop.duration_min
        window: Window = window_for(stop.periods, weekday) if stop.periods is not None else None
        open_from = open_to = None

        if stop.periods is None or window is None:
            warnings.append(PlanWarning(NO_HOURS, stop.place_id, {"name": stop.name}))
        elif window == CLOSED:
            warnings.append(PlanWarning(CLOSED_TODAY, stop.place_id, {"name": stop.name}))
        else:
            open_from, open_to = window
            if stop.start_min < open_from:
                warnings.append(PlanWarning(OPENS_LATER, stop.place_id, {
                    "name": stop.name, "start": hhmm(stop.start_min), "opens": hhmm(open_from),
                    "early_min": open_from - stop.start_min}))
            # Against the end, not the start: arriving at 15:43 for a 30-minute visit does not work
            # if it closes at 16:00.
            if end_min > open_to:
                warnings.append(PlanWarning(CLOSES_BEFORE_DONE, stop.place_id, {
                    "name": stop.name, "start": hhmm(stop.start_min),
                    "need_min": stop.duration_min, "closes": hhmm(open_to)}))

        if (stop.category in OUTDOOR) and sunset_min is not None and stop.start_min > sunset_min:
            warnings.append(PlanWarning(AFTER_SUNSET, stop.place_id, {
                "name": stop.name, "start": hhmm(stop.start_min), "sunset": hhmm(sunset_min)}))

        blocks.append(Block(place_id=stop.place_id, name=stop.name, start_min=stop.start_min,
                            end_min=end_min, duration_min=stop.duration_min,
                            open_from=open_from, open_to=open_to))

        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        if nxt is None or not routed or i >= len(legs):
            continue

        leg = legs[i]
        if leg.seconds == 0:
            warnings.append(PlanWarning(NO_ROUTE, nxt.place_id, {
                "from": stop.name, "to": nxt.name}))
            continue
        if mode == "walk" and implausible_walk(leg.seconds, leg.meters):
            warnings.append(PlanWarning(IMPLAUSIBLE_LEG, nxt.place_id, {
                "from": stop.name, "to": nxt.name,
                "kmh": round((leg.meters / leg.seconds) * 3.6)}))

        # The whole point of pinning: a gap too small for the walk is reported, never closed. A
        # negative gap is two blocks the user deliberately overlapped, which is the same failure.
        need_min = round(leg.seconds / 60)
        gap_min = nxt.start_min - end_min
        if need_min > gap_min:
            warnings.append(PlanWarning(TRAVEL_DOES_NOT_FIT, nxt.place_id, {
                "from": stop.name, "to": nxt.name, "need_min": need_min, "gap_min": gap_min}))

    finish = max((b.end_min for b in blocks), default=0)
    return DayPlan(blocks=blocks, warnings=warnings, finish_min=finish)
