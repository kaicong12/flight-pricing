"""Request and response bodies for the shortlist, the itinerary and one checked day.

Warnings and provisional reasons cross the wire as codes. The client owns the English, the same way
it already owns the copy for trip notes.
"""

from datetime import date, time, timedelta

from pydantic import BaseModel, Field

from libs.db.enums import Category
from tp_api.schemas import today_utc

MAX_STOPS_PER_DAY = 25

# The half-hour grid the client drags against; a duration is always a whole number of slots.
SLOT_MIN = 30
MIN_DURATION = SLOT_MIN

# Regular hours are all we can ever have for a future date, so past this many days out the plan is
# validated against them and labelled rather than presented as final.
SPECIAL_HOURS_HORIZON_DAYS = 7
REGULAR_HOURS_ONLY_NOTE = "regular_hours_only"

REFERENCE_URL_MAX = 2048


class SourceRefOut(BaseModel):
    source: str
    title: str
    url: str


class ShortlistPlaceOut(BaseModel):
    place_id: str
    city_id: str
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
    reference_url: str | None = None


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
    # Only the scheme is checked: a booking link is the user's to keep, and we never fetch it.
    reference_url: str | None = Field(default=None, max_length=REFERENCE_URL_MAX,
                                      pattern=r"^https?://\S+$")


class DayIn(BaseModel):
    day_index: int = Field(ge=0)
    items: list[ItemIn] = Field(default=[], max_length=MAX_STOPS_PER_DAY)


class ItineraryIn(BaseModel):
    """Only the listed days are touched. Days the client leaves out are left alone."""

    days: list[DayIn] = Field(min_length=1, max_length=16)


class DismissalIn(BaseModel):
    place_id: str = Field(min_length=1, max_length=255)


class VenueSuggestionOut(BaseModel):
    place_id: str
    name: str
    context: str | None = None


class PlaceAddIn(BaseModel):
    """Only the id is taken on trust — name and coordinates are fetched server-side."""

    place_id: str = Field(min_length=1, max_length=255)
    category: str = Field(pattern=f"^({'|'.join(Category)})$")


class BlockOut(BaseModel):
    place_id: str
    name: str
    start: str
    end: str
    duration_min: int
    open_from: str | None = None
    open_to: str | None = None


class WarningOut(BaseModel):
    code: str
    place_id: str | None = None
    detail: dict = {}


class DaylightOut(BaseModel):
    sunrise: str
    sunset: str


class DayRouteOut(BaseModel):
    day_index: int
    date: date
    # The first block's time, echoed back. None on an empty day.
    start_time: time | None = None
    blocks: list[BlockOut] = []
    daylight: DaylightOut | None = None
    warnings: list[WarningOut] = []
    provisional: list[str] = []


def provisional_reasons(trip_date: date) -> list[str]:
    """Why a plan for this date cannot be presented as final.

    A property of how far out the date is, not of the plan's contents, so a trip booked months ahead
    is always provisional however good its ordering.
    """
    if trip_date > today_utc() + timedelta(days=SPECIAL_HOURS_HORIZON_DAYS):
        return [REGULAR_HOURS_ONLY_NOTE]
    return []
