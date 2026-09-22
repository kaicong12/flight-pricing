"""Check one day of pinned activity blocks and say what is wrong with it.

Pure: the caller supplies the hours and the daylight, so this never touches the network and the whole
of the validation is testable.

Every block carries its own start time. Nothing here derives a time and nothing here moves a block —
the user put it at 14:00, so it stays at 14:00 and the warnings say what does not work.

Travel between blocks is not modelled at all — not the time, not the distance, not whether a route
exists. A day may name two places on opposite sides of the world and this will not object.
"""

from dataclasses import dataclass

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


def in_time_order(stops: list[Stop]) -> list[Stop]:
    """The day's sequence. place_id breaks a tie, because two blocks may share a start time."""
    return sorted(stops, key=lambda s: (s.start_min, s.place_id))


def plan_day(
    stops: list[Stop],
    *,
    weekday: int,
    sunset_min: float | None = None,
) -> DayPlan:
    """Validate a day of pinned blocks.

    `stops` may arrive in any order. `weekday` is Google's 0=Sunday.
    """
    blocks: list[Block] = []
    warnings: list[PlanWarning] = []

    for stop in in_time_order(stops):
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

    finish = max((b.end_min for b in blocks), default=0)
    return DayPlan(blocks=blocks, warnings=warnings, finish_min=finish)
