"""Request and response bodies for the shortlist, the itinerary and one checked day.

Warnings and provisional reasons cross the wire as codes. The client owns the English, the same way
it already owns the copy for trip notes.
"""

from datetime import date, time, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from libs.db.enums import BlockKind, Category
from tp_api.schemas import today_utc

MAX_STOPS_PER_DAY = 25

SPECIAL_HOURS_HORIZON_DAYS = 7
REGULAR_HOURS_ONLY_NOTE = "regular_hours_only"

REFERENCE_URL_MAX = 2048
TITLE_MAX = 120
DESCRIPTION_MAX = 1000


class SourceRefOut(BaseModel):
    source: str
    title: str
    url: str


class ShortlistPlaceOut(BaseModel):
    place_id: str
    city_id: str | None = None
    city_name: str | None = None
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
    """`name` resolves to the place's or the custom block's own title, so a client needs neither."""

    kind: str = BlockKind.PLACE
    place_id: str | None = None
    block_id: str | None = None
    name: str
    description: str | None = None
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
    city_id: str | None = None
    items: list[ItemOut] = []


class ItineraryOut(BaseModel):
    days: list[DayOut] = []


class ItemIn(BaseModel):
    """A block the user pinned, to the minute. It may run past midnight into the trip's later days.

    A place block carries a `place_id`; a custom one carries a title. Either may carry the `block_id`
    the client minted, which is its identity; a place block sent without one is given one here.
    """

    kind: BlockKind = BlockKind.PLACE
    place_id: str | None = Field(default=None, min_length=1, max_length=255)
    block_id: str | None = Field(default=None, min_length=1, max_length=36)
    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    start_min: int = Field(ge=0, lt=24 * 60)
    duration_min: int = Field(ge=1)
    reference_url: str | None = Field(default=None, max_length=REFERENCE_URL_MAX,
                                      pattern=r"^https?://\S+$")

    @model_validator(mode="after")
    def _check_identity(self):
        if self.kind is BlockKind.PLACE:
            if not self.place_id or self.title:
                raise ValueError("a place block takes a place_id and no title")
            self.block_id = self.block_id or str(uuid4())
        elif not self.block_id or not self.title or self.place_id:
            raise ValueError("a custom block takes a block_id and a title")
        return self


class DayIn(BaseModel):
    """`city_id` is only written when sent; null unassigns the day."""

    day_index: int = Field(ge=0)
    city_id: str | None = Field(default=None, max_length=255)
    items: list[ItemIn] = Field(default=[], max_length=MAX_STOPS_PER_DAY)


class ItineraryIn(BaseModel):
    """Only the listed days are touched. Days the client leaves out are left alone."""

    days: list[DayIn] = Field(min_length=1)


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
    kind: str = BlockKind.PLACE
    place_id: str | None = None
    block_id: str | None = None
    name: str
    description: str | None = None
    start: str
    end: str
    duration_min: int
    open_from: str | None = None
    open_to: str | None = None


class WarningOut(BaseModel):
    code: str
    place_id: str | None = None
    block_id: str | None = None
    detail: dict = {}


class DayRouteOut(BaseModel):
    day_index: int
    date: date
    start_time: time | None = None
    blocks: list[BlockOut] = []
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
