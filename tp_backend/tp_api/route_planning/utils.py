"""Pure helpers for the planning endpoints: trip arithmetic, timezones, source links.

No database and no HTTP — everything here is a function of its arguments.
"""

import html
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from libs.db import City, Trip
from libs.db.enums import Source

SOURCE_TITLE_MAX = 80
FALLBACK_TITLE = {Source.YOUTUBE: "YouTube video", Source.REDNOTE: "RedNote post"}


def day_count(trip: Trip) -> int:
    return (trip.depart_date - trip.arrive_date).days + 1


def available_window(trip: Trip, day_index: int) -> tuple[int, int]:
    """Local minutes a day's blocks must fit inside.

    The flight is the only hard bound: you cannot be somewhere before you land or after you leave.
    Mirrored by availableWindow in tp_client/src/lib/plan-types.ts, which stops the drop happening.
    """
    first, last = 0, 24 * 60
    if day_index == 0 and trip.arrive_time:
        first = trip.arrive_time.hour * 60 + trip.arrive_time.minute
    if day_index == day_count(trip) - 1 and trip.depart_time:
        last = trip.depart_time.hour * 60 + trip.depart_time.minute
    return first, last


def google_weekday(d: date) -> int:
    """Places numbers weekdays from Sunday; Python numbers them from Monday."""
    return (d.weekday() + 1) % 7


def tz_minutes(city: City, on: date, fallback: int | None) -> int:
    """The city's UTC offset on the trip's date, so a summer plan is not shifted by winter time."""
    if city.timezone:
        try:
            offset = datetime.combine(on, time(12, 0), ZoneInfo(city.timezone)).utcoffset()
        except (ZoneInfoNotFoundError, ValueError):
            offset = None
        if offset is not None:
            return int(offset.total_seconds() // 60)
    return fallback or 0


def depart_instant(on: date, start: time, tz_min: int) -> str:
    """When the day begins, as an offset-aware ISO string.

    Transit times are time-dependent, so this has to be a real instant: the spike's naive
    "<date>T<start>Z" asked for a route two hours out from what the user meant.
    """
    return datetime.combine(on, start, tzinfo=timezone(timedelta(minutes=tz_min))).isoformat()


def source_url(source: str, ref: str, token: str | None) -> str | None:
    if source == Source.YOUTUBE:
        return f"https://www.youtube.com/watch?v={ref}"
    if source == Source.REDNOTE:
        # The token expires, and RedNote then falls back to whatever the reader's own login can see.
        return (f"https://www.xiaohongshu.com/explore/{ref}?xsec_token={token}" if token
                else f"https://www.xiaohongshu.com/explore/{ref}")
    return None


def source_title(source: str, video_title: str | None, note_title: str | None,
                 description: str | None) -> str:
    """A mention outlives the cache row it came from, and YouTube titles arrive HTML-escaped."""
    return html.unescape(video_title or note_title or (description or "")[:SOURCE_TITLE_MAX]
                         or FALLBACK_TITLE[source])
