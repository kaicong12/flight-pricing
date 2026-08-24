"""Turn one ordered day into a schedule plus the list of things wrong with it.

Pure: the caller supplies the travel legs, the hours and the daylight, so this never touches the
network and the whole of the validation is testable. The order is the user's and is never changed —
warnings tell them what to move, they decide.
"""

from dataclasses import dataclass, field

from libs.routing.hours import CLOSED, Window, window_for

# Fallbacks when nothing better is known, keyed on the mention category.
DURATIONS = {"see": 75, "do": 120, "eat": 75, "drink": 60, "buy": 45, "sleep": 0, "other": 60}
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

# Faster than anyone walks, so the leg is really crossing water. Google routes the Suomenlinna
# ferry as a walk at 19 km/h with no wait and no timetable, tagged only as a toll — and the tag is
# not reliable enough to ask for. Implied speed catches every scheduled crossing instead.
MAX_WALK_KMH = 9.0


@dataclass(frozen=True)
class Stop:
    """One place on a day, in the position the user put it."""

    place_id: str
    name: str
    category: str | None
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


def duration_for(category: str | None) -> int:
    return DURATIONS.get(category or "", DEFAULT_DURATION) or DEFAULT_DURATION


def hhmm(minutes: float) -> str:
    """Local minutes past midnight as HH:MM, wrapping a day that runs past midnight."""
    m = int(minutes)
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def implausible_walk(seconds: int, meters: int) -> bool:
    """Whether a walking leg is too fast to be walked, and so is really a boat."""
    if seconds <= 0 or meters <= 0:
        return False
    return (meters / seconds) * 3.6 > MAX_WALK_KMH


def plan_day(
    stops: list[Stop],
    legs: list[TravelLeg],
    *,
    weekday: int,
    start_min: int,
    sunset_min: float | None = None,
    routed: bool = True,
    mode: str = "walk",
) -> DayPlan:
    """Walk the day accumulating a clock, and warn about everything that does not fit.

    `weekday` is Google's 0=Sunday. `legs[i]` is the travel from stops[i] to stops[i+1].
    `routed=False` means no travel times were available, so blocks are laid end to end and the
    times are optimistic — the caller says so with its own warning rather than silently lying here.
    """
    blocks: list[Block] = []
    warnings: list[PlanWarning] = []
    t = float(start_min)

    for i, stop in enumerate(stops):
        window: Window = window_for(stop.periods, weekday) if stop.periods is not None else None
        open_from = open_to = None

        if stop.periods is None or window is None:
            warnings.append(PlanWarning(NO_HOURS, stop.place_id, {"name": stop.name}))
        elif window == CLOSED:
            warnings.append(PlanWarning(CLOSED_TODAY, stop.place_id, {"name": stop.name}))
        else:
            open_from, open_to = window
            if t < open_from:
                warnings.append(PlanWarning(OPENS_LATER, stop.place_id, {
                    "name": stop.name, "arrive": hhmm(t), "opens": hhmm(open_from),
                    "wait_min": int(open_from - t)}))
                t = float(open_from)
            # Against arrival + duration, not arrival: getting in at 15:43 for a 30-minute visit
            # does not work if it closes at 16:00.
            if t + stop.duration_min > open_to:
                warnings.append(PlanWarning(CLOSES_BEFORE_DONE, stop.place_id, {
                    "name": stop.name, "arrive": hhmm(t), "need_min": stop.duration_min,
                    "closes": hhmm(open_to)}))

        if (stop.category in OUTDOOR) and sunset_min is not None and t > sunset_min:
            warnings.append(PlanWarning(AFTER_SUNSET, stop.place_id, {
                "name": stop.name, "start": hhmm(t), "sunset": hhmm(sunset_min)}))

        blocks.append(Block(place_id=stop.place_id, name=stop.name, start_min=int(t),
                            end_min=int(t) + stop.duration_min, duration_min=stop.duration_min,
                            open_from=open_from, open_to=open_to))
        t += stop.duration_min

        if i < len(legs):
            leg = legs[i]
            if routed and i + 1 < len(stops):
                if leg.seconds == 0:
                    warnings.append(PlanWarning(NO_ROUTE, stops[i + 1].place_id, {
                        "from": stop.name, "to": stops[i + 1].name}))
                elif mode == "walk" and implausible_walk(leg.seconds, leg.meters):
                    warnings.append(PlanWarning(IMPLAUSIBLE_LEG, stops[i + 1].place_id, {
                        "from": stop.name, "to": stops[i + 1].name,
                        "kmh": round((leg.meters / leg.seconds) * 3.6)}))
            t += leg.seconds / 60

    return DayPlan(blocks=blocks, warnings=warnings, finish_min=int(t))
