"""Request and response bodies for the shortlist, the itinerary and a routed day.

Warnings and provisional reasons cross the wire as codes. The client owns the English, the same way
it already owns the copy for trip notes.
"""

from datetime import date, time, timedelta

from pydantic import BaseModel, Field

from tp_api.schemas import TRANSIT_HORIZON_DAYS, TRANSIT_HORIZON_NOTE, today_utc

MAX_STOPS_PER_DAY = 25

# The half-hour grid the client drags against; a duration is always a whole number of slots.
SLOT_MIN = 30
MIN_DURATION = SLOT_MIN

# Regular hours are all we can ever have for a future date, so past this many days out the plan is
# validated against them and labelled rather than presented as final.
SPECIAL_HOURS_HORIZON_DAYS = 7
REGULAR_HOURS_ONLY_NOTE = "regular_hours_only"

WALK = "walk"
TRANSIT = "transit"


class SourceRefOut(BaseModel):
    source: str
    title: str
    url: str


class ShortlistPlaceOut(BaseModel):
    place_id: str
    name: str
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    primary_type: str | None = None
    category: str | None = None
    why_go: str | None = None
    sources: list[SourceRefOut] = []
    mention_count: int = 0
    in_itinerary: bool = False
    day_index: int | None = None


class ShortlistOut(BaseModel):
    total: int
    shown: int
    places: list[ShortlistPlaceOut] = []


class ItemOut(BaseModel):
    place_id: str
    name: str
    lat: float | None = None
    lon: float | None = None
    start_min: int
    duration_min: int
    category: str | None = None
    primary_type: str | None = None


class DayOut(BaseModel):
    day_index: int
    date: date
    items: list[ItemOut] = []


class ItineraryOut(BaseModel):
    days: list[DayOut] = []


class ItemIn(BaseModel):
    """A block the user pinned. Both times are grid-aligned, which the database also enforces."""

    place_id: str = Field(min_length=1, max_length=255)
    start_min: int = Field(ge=0, lt=24 * 60, multiple_of=SLOT_MIN)
    duration_min: int = Field(ge=MIN_DURATION, le=24 * 60, multiple_of=SLOT_MIN)


class DayIn(BaseModel):
    day_index: int = Field(ge=0)
    items: list[ItemIn] = Field(default=[], max_length=MAX_STOPS_PER_DAY)


class ItineraryIn(BaseModel):
    """Only the listed days are touched. Days the client leaves out are left alone."""

    days: list[DayIn] = Field(min_length=1, max_length=16)


class DismissalIn(BaseModel):
    place_id: str = Field(min_length=1, max_length=255)


class BlockOut(BaseModel):
    place_id: str
    name: str
    start: str
    end: str
    duration_min: int
    open_from: str | None = None
    open_to: str | None = None


class LegOut(BaseModel):
    from_place_id: str
    to_place_id: str
    seconds: int
    meters: int
    transit_steps: list[str] = []
    polyline: str | None = None


class WarningOut(BaseModel):
    code: str
    place_id: str | None = None
    detail: dict = {}


class DaylightOut(BaseModel):
    sunrise: str
    sunset: str


class RouteDayRequest(BaseModel):
    """No start time: every block carries its own, so there is nothing left for the day to say."""

    mode: str = Field(default=WALK, pattern=f"^({WALK}|{TRANSIT})$")


class DayRouteOut(BaseModel):
    day_index: int
    date: date
    mode: str
    # The first block's time, echoed back. None on an empty day.
    start_time: time | None = None
    blocks: list[BlockOut] = []
    legs: list[LegOut] = []
    polyline: str | None = None
    total_distance_m: int = 0
    total_travel_s: int = 0
    # False when no travel times were available, so the times are laid end to end and optimistic.
    routed: bool = True
    daylight: DaylightOut | None = None
    warnings: list[WarningOut] = []
    provisional: list[str] = []


def provisional_reasons(trip_date: date) -> list[str]:
    """Why a plan for this date cannot be presented as final.

    Both reasons are properties of how far out the date is, not of the plan's contents, so a trip
    booked months ahead is always provisional however good its ordering.
    """
    today = today_utc()
    out = []
    if trip_date > today + timedelta(days=TRANSIT_HORIZON_DAYS):
        out.append(TRANSIT_HORIZON_NOTE)
    if trip_date > today + timedelta(days=SPECIAL_HOURS_HORIZON_DAYS):
        out.append(REGULAR_HOURS_ONLY_NOTE)
    return out
