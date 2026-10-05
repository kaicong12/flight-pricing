"""The trip as one .xlsx: the ordered days, then the shortlist behind them.

Colours are tp_client/docs/design-system.md.
"""

import json
import textwrap
from datetime import UTC, date, datetime, timedelta
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from libs.db import Trip, trip_cities
from libs.db.enums import Category
from libs.routing import hhmm
from tp_api.expenses import service as expense_service
from tp_api.route_planning import service
from tp_api.route_planning.utils import day_count

INK, PAPER, SAND = "252B20", "FDFBF3", "F3F0E6"
BRAND, BRAND_BG = "2C6B64", "E5EFEC"
ALERT = "8B4526"
FAINT, HAIRLINE = "98A08D", "E3DDCB"

LINK_ICON = "🔗"

ITINERARY_COLUMNS = [("Day", 6), ("Date", 10), ("#", 4), ("Start", 7), ("End", 7), ("Block", 32),
                     ("Category", 10)]
DETAILS_COLUMN = ("Details", 44)
REFERENCE_COLUMN = ("Ref", 5)
SHORTLIST_COLUMNS = [("Place", 32), ("Category", 10), ("Mentions", 10), ("Used on", 10),
                     ("Why go", 60), ("Source", 7)]
EXPENSE_COLUMNS = [("Day", 6), ("Date", 10), ("Expense", 34), ("Paid by", 18), ("Amount", 12),
                   ("Cur", 5)]
CENTRED = {"#", "Start", "End", "Ref", "Source", "Mentions", "Used on", "Cur"}
WRAPPED = {"Block", "Details", "Why go", "Expense"}
MONEY_FORMAT = "#,##0.00"

META_SHEET = "_trip_planner"
MARKER = "trip-planner-export"
VERSION = 1
ROW_KEY = "_row"
CHUNK = 30000  # a cell holds at most 32767 characters

HAIRLINE_BOTTOM = Border(bottom=Side(style="thin", color=HAIRLINE))
LINE_HEIGHT = 15


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


def _lines(text, width: int) -> int:
    """Excel will not auto-fit a row that holds a merged cell, so the height is counted here."""
    return sum(len(textwrap.wrap(part, width)) or 1 for part in str(text).split("\n"))


def _body_row(ws: Worksheet, row: int, columns: list[tuple[str, int]], values: list,
              *, stripe: str, faint: set[int] = frozenset()) -> None:
    tallest = 1
    for i, (label, width) in enumerate(columns, start=1):
        cell = ws.cell(row=row, column=i, value=values[i - 1])
        cell.fill = PatternFill("solid", fgColor=stripe)
        cell.border = HAIRLINE_BOTTOM
        cell.font = Font(color=FAINT if i in faint else INK)
        wrap = label in WRAPPED
        cell.alignment = Alignment(horizontal="center" if label in CENTRED else "left",
                                   vertical="top", wrap_text=wrap)
        if wrap and values[i - 1]:
            tallest = max(tallest, _lines(values[i - 1], width))
    ws.row_dimensions[row].height = tallest * LINE_HEIGHT


def _merge_down(ws: Worksheet, top: int, bottom: int, columns: tuple[int, ...]) -> None:
    """Day and Date repeat unchanged down a band, so each becomes one tall cell."""
    if bottom <= top:
        return
    for column in columns:
        ws.merge_cells(start_row=top, start_column=column, end_row=bottom, end_column=column)
        ws.cell(row=top, column=column).alignment = Alignment(horizontal="center",
                                                             vertical="center")


def _link(ws: Worksheet, row: int, column: int, url: str | None, title: str | None) -> None:
    """One cell, one link icon — Excel and Sheets both open a hyperlink in the browser."""
    if not url:
        return
    cell = ws.cell(row=row, column=column, value=LINK_ICON)
    # Excel shows the hyperlink's tooltip on hover.
    cell.hyperlink = Hyperlink(ref=cell.coordinate, target=url, tooltip=title)
    cell.font = Font(color=BRAND)
    cell.alignment = Alignment(horizontal="center")


def _tint(ws: Worksheet, row: int, column: int, fill: str, ink: str) -> None:
    cell = ws.cell(row=row, column=column)
    cell.fill = PatternFill("solid", fgColor=fill)
    cell.font = Font(color=ink)


def _category_dropdown(ws: Worksheet, cells: list[str]) -> None:
    """A list validation is what Sheets draws as a chip and Excel as a dropdown."""
    if not cells:
        return
    dv = DataValidation(type="list", formula1=f'"{",".join(Category)}"', allow_blank=True,
                        sqref=" ".join(cells))
    ws.add_data_validation(dv)


def until(day: int, end: int) -> str:
    """A block's end as the sheet writes it: "24:00" at midnight, "Day N HH:MM" on a later day."""
    extra = (end - 1) // (24 * 60)
    local = end - extra * 24 * 60
    text = "24:00" if local == 24 * 60 else hhmm(local)
    return text if extra == 0 else f"Day {day + 1 + extra} {text}"


def meta_sheet(ws: Worksheet, db: Session, trip: Trip, rows: dict[str, dict]) -> None:
    ws.sheet_state = "veryHidden"
    payload = json.dumps({
        "trip": {"name": trip.name, "extra_details": trip.extra_details,
                 "cities": [{"city_id": c.city_id, "name": c.name} for c in trip_cities(db, trip)],
                 "arrive_date": trip.arrive_date.isoformat(),
                 "depart_date": trip.depart_date.isoformat(),
                 "arrive_time": trip.arrive_time.isoformat() if trip.arrive_time else None,
                 "depart_time": trip.depart_time.isoformat() if trip.depart_time else None},
        "rows": rows,
    }, sort_keys=True, separators=(",", ":"))
    ws.cell(row=1, column=1, value=MARKER)
    ws.cell(row=1, column=2, value=VERSION)
    for i in range(0, len(payload), CHUNK):
        ws.cell(row=2 + i // CHUNK, column=1, value=payload[i:i + CHUNK])


def itinerary_sheet(ws: Worksheet, db: Session, trip: Trip) -> dict[str, dict]:
    """Returns each written row's identity, keyed by the hidden `_row` cell an upload reads back."""
    city = trip.city
    rows = service.day_rows(db, trip.trip_id)
    details = any(r.ItineraryItem.description for r in rows)
    refs = any(r.ItineraryItem.reference_url for r in rows)
    columns = (ITINERARY_COLUMNS + ([DETAILS_COLUMN] if details else [])
               + ([REFERENCE_COLUMN] if refs else []))

    ws.cell(row=1, column=1, value=f"{trip.name or city.name} · "
            f"{trip.arrive_date:%d %b}–{trip.depart_date:%d %b %Y}").font = Font(
                bold=True, size=14, color=INK)
    ws.cell(row=2, column=1, value=f"exported {datetime.now(UTC):%d %b %Y}").font = Font(color=FAINT, size=10)
    _header(ws, 3, columns)
    key_column = len(columns) + 1
    ws.cell(row=3, column=key_column, value=ROW_KEY)
    ws.column_dimensions[get_column_letter(key_column)].hidden = True
    identities: dict[str, dict] = {}

    place_ids = [r.Place.place_id for r in rows if r.Place]
    facts = service.mention_facts(db, place_ids)

    categories: list[str] = []
    by_day: dict[int, list] = {}
    for r in rows:
        by_day.setdefault(r.ItineraryItem.day_index, []).append(r)

    at = 4
    for day in range(day_count(trip)):
        day_date = trip.arrive_date + timedelta(days=day)
        items = by_day.get(day, [])
        _band(ws, at, len(columns), f"Day {day + 1} · {day_date:%a %d %b}")
        at += 1

        top = at
        for n, r in enumerate(items, start=1):
            item = r.ItineraryItem
            _body_row(ws, at, columns,
                      [day + 1, f"{day_date:%d %b}", n, hhmm(item.start_min),
                       until(day, item.start_min + item.duration_min),
                       r.Place.name if r.Place else item.title,
                       service.category_of(r.Place, facts) or "" if r.Place else ""]
                      + ([item.description] if details else [])
                      + ([None] if refs else []),
                      stripe=SAND if n % 2 else PAPER, faint={4, 5})
            if r.Place:
                categories.append(f"G{at}")
            if refs:
                _link(ws, at, len(columns), item.reference_url, "Your link for this block")
            key = f"r{len(identities) + 1}"
            ws.cell(row=at, column=key_column, value=key)
            identities[key] = {"kind": item.kind, "place_id": item.place_id,
                               "block_id": item.block_id,
                               "name": r.Place.name if r.Place else item.title,
                               "reference_url": item.reference_url}
            at += 1
        _merge_down(ws, top, at - 1, (1, 2))
    _category_dropdown(ws, categories)
    return identities


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
    _category_dropdown(ws, [f"B4:B{3 + len(listing.places)}"] if listing.places else [])


def _money(ws: Worksheet, row: int, column: int, cents: int | None, *, bold: bool = False,
           ink: str = INK) -> None:
    if cents is None:
        return
    cell = ws.cell(row=row, column=column, value=cents / 100)
    cell.number_format = MONEY_FORMAT
    cell.alignment = Alignment(horizontal="right", vertical="top")
    cell.font = Font(color=ink, bold=bold)


def _who(member) -> str:
    return (member.name or member.email).split()[0].split("@")[0]


def expenses_sheet(ws: Worksheet, db: Session, trip: Trip) -> None:
    """Who paid what, then the balances. One column per person, so a row reads across as a split.

    Each currency gets its own balance block: nothing here is converted, so nothing is ever summed
    across two of them.
    """
    tab = expense_service.overview(db, trip.trip_id)
    spenders = {s.user_id for e in tab.expenses for s in e.shares} | {e.payer_id
                                                                     for e in tab.expenses}
    people = [m for m in tab.members if m.user_id in spenders] or tab.members
    columns = EXPENSE_COLUMNS + [(_who(m), 13) for m in people]
    names = {m.user_id: _who(m) for m in tab.members}
    last = len(columns)

    ws.cell(row=1, column=1, value="Expenses · who paid, and what each person owes of it").font = (
        Font(bold=True, size=14, color=INK))
    ws.cell(row=2, column=1, value="every amount is in the expense's own currency — nothing here "
            "is converted").font = Font(color=FAINT, size=10)
    _header(ws, 3, columns)

    by_date: dict[date, list] = {}
    for e in tab.expenses:
        by_date.setdefault(e.spent_on, []).append(e)

    at = 4
    for when in sorted(by_date):
        items = by_date[when]
        day = (when - trip.arrive_date).days
        label = f"Day {day + 1} · " if 0 <= day < day_count(trip) else ""
        _band(ws, at, last, f"{label}{when:%a %d %b} · "
              f"{len(items)} expense{'' if len(items) == 1 else 's'}")
        at += 1

        top = at
        for n, e in enumerate(items, start=1):
            share = {s.user_id: s.amount_cents for s in e.shares}
            what = (f"{e.description} · {e.block_title}"
                    if e.block_title and e.block_title != e.description else e.description)
            _body_row(ws, at, columns,
                      [day + 1 if label else "", f"{when:%d %b}", what,
                       names.get(e.payer_id, "?"), None, e.currency]
                      + [None] * len(people),
                      stripe=SAND if n % 2 else PAPER)
            _money(ws, at, 5, e.amount_cents, bold=True)
            for i, m in enumerate(people):
                _money(ws, at, len(EXPENSE_COLUMNS) + 1 + i, share.get(m.user_id),
                       ink=FAINT if m.user_id != e.payer_id else INK)
            at += 1
        _merge_down(ws, top, at - 1, (1, 2))

    for balance in tab.balances:
        net = {b.user_id: b for b in balance.members}
        at += 1
        _band(ws, at, last, f"Balance · {balance.currency} · "
              f"{balance.total_cents / 100:,.2f} spent · a positive net is owed back")
        at += 1
        rows = [("Paid", "paid_cents"), ("Share", "share_cents"), ("Net", "net_cents")]
        if any(b.settled_cents for b in balance.members):
            rows.insert(2, ("Settled", "settled_cents"))
        for n, (row_label, field) in enumerate(rows):
            _body_row(ws, at, columns, ["", "", row_label, "", None, balance.currency]
                      + [None] * len(people), stripe=PAPER if n % 2 else SAND)
            for i, m in enumerate(people):
                figure = getattr(net[m.user_id], field) if m.user_id in net else None
                _money(ws, at, len(EXPENSE_COLUMNS) + 1 + i, figure, bold=row_label == "Net",
                       ink=ALERT if row_label == "Net" and (figure or 0) < 0 else INK)
            at += 1
        for transfer in balance.transfers:
            pays = (f"{names.get(transfer.from_user_id, '?')} pays "
                    f"{names.get(transfer.to_user_id, '?')}")
            _body_row(ws, at, columns, ["", "", pays, "", None, balance.currency]
                      + [None] * len(people), stripe=BRAND_BG)
            _money(ws, at, 5, transfer.amount_cents, bold=True, ink=BRAND)
            at += 1

    if not tab.expenses:
        ws.cell(row=5, column=1, value="Nothing spent yet.").font = Font(color=FAINT)


def workbook_bytes(db: Session, trip: Trip) -> bytes:
    wb = Workbook()
    identities = itinerary_sheet(wb.active, db, trip)
    wb.active.title = "Itinerary"
    expenses_sheet(wb.create_sheet("Expenses"), db, trip)
    shortlist_sheet(wb.create_sheet("Shortlist"), db, trip)
    meta_sheet(wb.create_sheet(META_SHEET), db, trip, identities)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def filename(trip: Trip) -> str:
    stem = (trip.name or trip.city.name).replace(" ", "-")
    return f"{stem}-{trip.arrive_date:%Y-%m-%d}.xlsx"
