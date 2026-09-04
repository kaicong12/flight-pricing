"""Request and response bodies for the planning API."""

from datetime import UTC, date, datetime, time, timedelta

from pydantic import BaseModel, Field, model_validator

MAX_TRIP_DAYS = 14

# Routes API TRANSIT returns ROUTE_NOT_FOUND beyond roughly this far out, so a plan made earlier
# can only be routed on walking times.
TRANSIT_HORIZON_DAYS = 100
TRANSIT_HORIZON_NOTE = "transit_horizon"


def today_utc() -> date:
    """Trip dates are local to the city, so compare against UTC and allow a day of slack."""
    return datetime.now(UTC).date()


NAME_MAX = 120


class TripPatch(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX)


class InitiatePlanRequest(BaseModel):
    city_place_id: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=NAME_MAX)
    arrive_date: date
    arrive_time: time | None = None
    depart_date: date
    depart_time: time | None = None
    extra_details: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_span(self):
        if self.depart_date < self.arrive_date:
            raise ValueError("depart_date is before arrive_date")
        if (self.depart_date - self.arrive_date).days > MAX_TRIP_DAYS:
            raise ValueError(f"trip is longer than {MAX_TRIP_DAYS} days")
        if self.arrive_date < today_utc() - timedelta(days=1):
            raise ValueError("arrive_date is in the past")
        return self


class CitySuggestionOut(BaseModel):
    place_id: str
    description: str
    main_text: str | None = None


class CityOut(BaseModel):
    city_id: str
    name: str
    country: str | None = None
    timezone: str | None = None


class IngestOut(BaseModel):
    run_id: str
    status: str


class TaskProgress(BaseModel):
    kind: str
    status: str
    count: int


class TaskFailure(BaseModel):
    """Sources we could not read, grouped by why."""

    kind: str
    status: str
    error_code: str | None = None
    last_error: str | None = None
    count: int = 1


class TripOut(BaseModel):
    trip_id: str
    name: str | None = None
    city: CityOut
    arrive_date: date
    arrive_time: time | None = None
    depart_date: date
    depart_time: time | None = None
    extra_details: str | None = None
    ingest: IngestOut | None = None
    notes: list[str] = []
    deleted: bool = False


class TripStatusOut(TripOut):
    progress: list[TaskProgress] = []
    failures: list[TaskFailure] = []


class TripSummaryOut(BaseModel):
    trip_id: str
    name: str | None = None
    city: CityOut
    arrive_date: date
    depart_date: date
    ingest: IngestOut | None = None
    tasks_done: int = 0
    tasks_total: int = 0
    place_count: int = 0
    notes: list[str] = []


def notes_for(arrive: date) -> list[str]:
    """Warnings the client must show. Never a reason to reject the trip."""
    if arrive > today_utc() + timedelta(days=TRANSIT_HORIZON_DAYS):
        return [TRANSIT_HORIZON_NOTE]
    return []
