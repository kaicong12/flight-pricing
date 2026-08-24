"""Opening hours: the pure window arithmetic, and the Place Details fetch that feeds it.

Only regular hours are ever fetched. currentOpeningHours.specialDays covers the coming week, so a
plan for a date further out cannot know about holiday closures — which is what makes such a plan
provisional rather than wrong.
"""

from dataclasses import dataclass
from typing import Literal

import httpx

from libs.http import client
from libs.places import DETAILS_URL, PlacesError
from libs.settings import settings

HOURS_FIELDS = ("id,regularOpeningHours.periods,regularOpeningHours.weekdayDescriptions,"
                "utcOffsetMinutes")

CLOSED = "closed"

Window = tuple[int, int] | Literal["closed"] | None


@dataclass(frozen=True)
class HoursHit:
    """What Places knows about one place's regular hours. has_hours=False means it published none."""

    place_id: str
    periods: list[dict]
    weekday_descriptions: list[str]
    utc_offset_minutes: int | None
    has_hours: bool


def window_for(periods: list[dict], weekday: int) -> Window:
    """Opening window in local minutes for a weekday, "closed", or None when hours are unknown.

    `weekday` is Google's numbering: 0=Sunday. (weekdayDescriptions is Monday-first, so the two are
    not interchangeable.) A period carrying `open` but no `close` runs 24 hours. A close whose `day`
    differs from its open's has rolled past midnight, which we clamp to the end of the day rather
    than letting it wrap to a smaller number than the open.
    """
    if not periods:
        return None
    if len(periods) == 1 and "close" not in periods[0]:
        return (0, 24 * 60)
    for p in periods:
        o = p.get("open") or {}
        if o.get("day") != weekday:
            continue
        c = p.get("close") or {}
        start = o.get("hour", 0) * 60 + o.get("minute", 0)
        end = c.get("hour", 24) * 60 + c.get("minute", 0)
        if c.get("day") != weekday:
            end = 24 * 60
        return (start, end)
    return CLOSED


def fetch_hours(place_ids: list[str], *, timeout: float = 20.0) -> dict[str, HoursHit]:
    """One Place Details call per place. A place Places does not know is simply absent from the map."""
    key = settings().google_api_key
    if not key:
        raise PlacesError("GOOGLE_API_KEY is not set")

    out: dict[str, HoursHit] = {}
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": HOURS_FIELDS}
    for pid in place_ids:
        try:
            r = client().get(f"{DETAILS_URL}/{pid}", timeout=timeout, headers=headers)
        except httpx.HTTPError as e:
            raise PlacesError(f"places details failed: {e}") from e
        if r.status_code == 404:
            continue
        if r.status_code != 200:
            raise PlacesError(f"places details returned {r.status_code}: {r.text[:200]}")

        body = r.json()
        oh = body.get("regularOpeningHours") or {}
        periods = oh.get("periods") or []
        out[pid] = HoursHit(
            place_id=pid,
            periods=periods,
            weekday_descriptions=oh.get("weekdayDescriptions") or [],
            utc_offset_minutes=body.get("utcOffsetMinutes"),
            has_hours=bool(periods),
        )
    return out
