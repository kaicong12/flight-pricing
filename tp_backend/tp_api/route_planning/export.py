"""The trip as one .xlsx: the ordered days, then the shortlist behind them.

Colours are tp_client/docs/design-system.md, and the warning English lives here because a
spreadsheet has no client to own it. Nothing routes: an export spends no `computeRoutes` call.
"""

from datetime import UTC, datetime, timedelta
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from libs.db import Trip
from libs.routing import PlanWarning, Stop, hhmm, plan_day, sun_times
from tp_api.deps import HoursLookup
from tp_api.route_planning import service
from tp_api.route_planning.utils import day_count, google_weekday, tz_minutes

INK, PAPER, SAND = "252B20", "FDFBF3", "F3F0E6"
BRAND, BRAND_BG = "2C6B64", "E5EFEC"
OK, OK_BG = "4E7A45", "E9F0E0"
WARN, WARN_BG = "8A6524", "F6EBD4"
ALERT, ALERT_BG = "8B4526", "F8E7DC"
FAINT, HAIRLINE = "98A08D", "E3DDCB"

LINK_ICON = "🔗"

WARNING_TEXT = {
    "closed": "closed all day",
    "opens_later": "opens {opens}, you arrive {start}",
    "closes_before_done": "closes {closes} before you finish",
    "after_sunset": "dark by {start} — sunset {sunset}",
    "no_hours": "opening hours unknown",
    "no_route": "no walking route",
}
BLOCKING = {"closed", "no_route"}

ITINERARY_COLUMNS = [("Day", 6), ("Date", 10), ("#", 4), ("Start", 7), ("End", 7), ("Place", 32),
                     ("Category", 10), ("Warning", 36)]
REFERENCE_COLUMN = ("Ref", 5)
SHORTLIST_COLUMNS = [("Place", 32), ("Category", 10), ("Mentions", 10), ("Used on", 10),
                     ("Why go", 60), ("Source", 7)]
CENTRED = {"#", "Start", "End", "Ref", "Source", "Mentions", "Used on"}

HAIRLINE_BOTTOM = Border(bottom=Side(style="thin", color=HAIRLINE))


def _header(ws: Worksheet, row: int, columns: list[tuple[str, int]]) -> None:
    for i, (label, width) in enumerate(columns, start=1):
        cell = ws.cell(row=row, column=i, value=label)
        cell.fill = PatternFill("solid", fgColor=INK)
        cell.font = Font(bold=True, color=PAPER, size=11)
        cell.alignment = Alignment(horizontal="center" if label in CENTRED else "left")
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _band(ws: Worksheet, row: int, columns: int, text: str) -> None:
    for i in range(1, columns + 1):
        ws.cell(row=row, column=i).fill = PatternFill("solid", fgColor=BRAND_BG)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=columns)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(bold=True, color=BRAND)


def _body_row(ws: Worksheet, row: int, columns: list[tuple[str, int]], values: list,
              *, stripe: str, faint: set[int] = frozenset()) -> None:
    for i, (label, _) in enumerate(columns, start=1):
        cell = ws.cell(row=row, column=i, value=values[i - 1])
        cell.fill = PatternFill("solid", fgColor=stripe)
        cell.border = HAIRLINE_BOTTOM
        cell.font = Font(color=FAINT if i in faint else INK)
        if label in CENTRED:
            cell.alignment = Alignment(horizontal="center")


def _link(ws: Worksheet, row: int, column: int, url: str | None, title: str | None) -> None:
    """One cell, one link icon — Excel and Sheets both open a hyperlink in the browser."""
    if not url:
        return
    cell = ws.cell(row=row, column=column, value=LINK_ICON)
    # Excel shows the hyperlink's own tooltip on hover, which is where the source title goes.
    cell.hyperlink = Hyperlink(ref=cell.coordinate, target=url, tooltip=title)
    cell.font = Font(color=BRAND)
    cell.alignment = Alignment(horizontal="center")


def _tint(ws: Worksheet, row: int, column: int, fill: str, ink: str) -> None:
    cell = ws.cell(row=row, column=column)
    cell.fill = PatternFill("solid", fgColor=fill)
    cell.font = Font(color=ink)


def _warning_cell(found: list[PlanWarning]) -> tuple[str, str, str]:
    text = "; ".join(WARNING_TEXT[w.code].format(**w.detail) for w in found) or "ok"
    if any(w.code in BLOCKING for w in found):
        return text, ALERT_BG, ALERT
    return (text, WARN_BG, WARN) if found else (text, OK_BG, OK)


def itinerary_sheet(ws: Worksheet, db: Session, trip: Trip, fetch: HoursLookup) -> None:
    city = trip.city
    rows = service.day_rows(db, trip.trip_id)
    refs = {r.Place.place_id: r.ItineraryItem.reference_url
            for r in rows if r.ItineraryItem.reference_url}
    columns = ITINERARY_COLUMNS + ([REFERENCE_COLUMN] if refs else [])

    ws.cell(row=1, column=1, value=f"{trip.name or city.name} · "
            f"{trip.arrive_date:%d %b}–{trip.depart_date:%d %b %Y}").font = Font(
                bold=True, size=14, color=INK)
    ws.cell(row=2, column=1, value=f"exported {datetime.now(UTC):%d %b %Y} · opening hours were "
            "checked then, re-check nearer the date").font = Font(color=FAINT, size=10)
    _header(ws, 3, columns)

    place_ids = [r.Place.place_id for r in rows]
    facts = service.mention_facts(db, place_ids)
    hours = service.load_hours(db, place_ids, fetch) if place_ids else {}

    by_day: dict[int, list] = {}
    for r in rows:
        by_day.setdefault(r.ItineraryItem.day_index, []).append(r)

    at = 4
    for day in range(day_count(trip)):
        day_date = trip.arrive_date + timedelta(days=day)
        items = by_day.get(day, [])
        places = {r.Place.place_id: r.Place for r in items}

        sunset = None
        daylight = ""
        if city.lat is not None and city.lon is not None:
            tz_min = tz_minutes(city, day_date, next(
                (h.utc_offset_minutes for h in hours.values()
                 if h.utc_offset_minutes is not None), None))
            sunrise, sunset = sun_times(day_date, city.lat, city.lon, tz_min)
            # (None, None) is polar day or night, which the plan screen also shows as no daylight.
            if sunrise is not None and sunset is not None:
                daylight = f" · daylight {hhmm(sunrise)}–{hhmm(sunset)}"

        _band(ws, at, len(columns), f"Day {day + 1} · {day_date:%a %d %b} · "
              f"{len(items) or 'no'} block{'' if len(items) == 1 else 's'}{daylight}")
        at += 1

        plan = plan_day(
            [Stop(place_id=r.Place.place_id, name=r.Place.name,
                  category=service.category_of(r.Place, facts),
                  start_min=r.ItineraryItem.start_min, duration_min=r.ItineraryItem.duration_min,
                  periods=hours[r.Place.place_id].periods if r.Place.place_id in hours else None)
             for r in items],
            [], weekday=google_weekday(day_date), sunset_min=sunset, routed=False)

        found: dict[str, list[PlanWarning]] = {}
        for w in plan.warnings:
            found.setdefault(w.place_id or "", []).append(w)

        for n, block in enumerate(plan.blocks, start=1):
            text, fill, ink = _warning_cell(found.get(block.place_id, []))
            _body_row(ws, at, columns,
                      [day + 1, f"{day_date:%d %b}", n, hhmm(block.start_min), hhmm(block.end_min),
                       block.name, service.category_of(places[block.place_id], facts) or "",
                       text] + ([None] if refs else []),
                      stripe=SAND if n % 2 else PAPER, faint={4, 5})
            _tint(ws, at, 8, fill, ink)
            if refs:
                _link(ws, at, len(columns), refs.get(block.place_id), "Your link for this block")
            at += 1


def shortlist_sheet(ws: Worksheet, db: Session, trip: Trip) -> None:
    """What the videos and notes offered, so the places left out are still in the file."""
    columns = SHORTLIST_COLUMNS
    ws.cell(row=1, column=1, value="Shortlist · ranked by how many sources named it").font = Font(
        bold=True, size=14, color=INK)
    _header(ws, 3, columns)

    listing = service.shortlist(db, trip.trip_id, limit=200, offset=0, category=None)
    for n, place in enumerate(listing.places, start=1):
        at = 3 + n
        used = place.day_index is not None
        src = next(iter(place.sources), None)
        _body_row(ws, at, columns,
                  [place.name, place.category or "", place.mention_count,
                   f"Day {place.day_index + 1}" if used else "not used", place.why_go or "", None],
                  stripe=SAND if n % 2 else PAPER, faint=set() if used else {4})
        if used:
            _tint(ws, at, 4, BRAND_BG, BRAND)
        _link(ws, at, 6, src.url if src else None, src.title if src else None)


def workbook_bytes(db: Session, trip: Trip, fetch: HoursLookup) -> bytes:
    wb = Workbook()
    itinerary_sheet(wb.active, db, trip, fetch)
    wb.active.title = "Itinerary"
    shortlist_sheet(wb.create_sheet("Shortlist"), db, trip)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def filename(trip: Trip) -> str:
    stem = (trip.name or trip.city.name).replace(" ", "-")
    return f"{stem}-{trip.arrive_date:%Y-%m-%d}.xlsx"
