"""The .xlsx export: real cells, the warning colours, and a link back to the source."""

from datetime import timedelta
from io import BytesIO

from conftest import make_mention, make_place, make_video, plan_body
from openpyxl import load_workbook

from libs.routing import HoursHit
from tp_api.route_planning.export import ALERT_BG, WARN_BG
from tp_api.route_planning.utils import google_weekday
from tp_api.schemas import today_utc

OPEN_EARLY_ALL_WEEK = [{"open": {"day": d, "hour": 9, "minute": 0},
                        "close": {"day": d, "hour": 10, "minute": 0}} for d in range(7)]


def export(client, trip):
    r = client.get(f"/trips/{trip}/export.xlsx")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    return load_workbook(BytesIO(r.content))


def a_trip_with_one_block(client, db, **item):
    trip = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
    make_place(db, place_id="p1", name="Löyly")
    make_video(db, "ref1", title="Helsinki in 3 Days")
    make_mention(db, "p1", source_ref="ref1", why_go="The sauna everyone names")
    client.put(f"/trips/{trip}/itinerary",
               json={"days": [{"day_index": 0, "items": [
                   {"place_id": "p1", "start_min": 900, "duration_min": 90} | item]}]})
    return trip


def test_a_block_carries_its_times_and_category(client, db):
    trip = a_trip_with_one_block(client, db)

    ws = export(client, trip)["Itinerary"]

    assert [c.value for c in ws[3]] == ["Day", "Date", "#", "Start", "End", "Block", "Category",
                                        "Warning"]
    # Row 4 is the day band, so the first block is row 5.
    assert [ws.cell(row=5, column=c).value for c in (1, 3, 4, 5, 6, 7)] == [
        1, 1, "15:00", "16:30", "Löyly", "see"]


def test_the_ref_column_exists_only_when_a_block_has_a_link(client, db):
    trip = a_trip_with_one_block(client, db)
    assert [c.value for c in export(client, trip)["Itinerary"][3]][-1] == "Warning"

    client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
        {"place_id": "p1", "start_min": 900, "duration_min": 90,
         "reference_url": "https://www.airbnb.com/rooms/12345"}]}]})

    ws = export(client, trip)["Itinerary"]
    assert [c.value for c in ws[3]][-1] == "Ref"
    assert ws.cell(row=5, column=9).hyperlink.target == "https://www.airbnb.com/rooms/12345"


def test_a_reference_must_be_a_link(client, db):
    trip = a_trip_with_one_block(client, db)
    r = client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
        {"place_id": "p1", "start_min": 900, "duration_min": 90,
         "reference_url": "my booking email"}]}]})
    assert r.status_code == 422


def test_a_block_that_outlasts_the_opening_hours_is_amber(client, db, hours):
    trip = a_trip_with_one_block(client, db)
    # A 15:00 block against 09:00-10:00 hours: shut long before the user gets there.
    hours["fn"] = lambda ids: {i: HoursHit(place_id=i, periods=OPEN_EARLY_ALL_WEEK,
                                           weekday_descriptions=[], utc_offset_minutes=180)
                               for i in ids}

    warning = export(client, trip)["Itinerary"].cell(row=5, column=8)

    assert warning.value == "closes 10:00 before you finish"
    assert warning.fill.fgColor.rgb.endswith(WARN_BG)


def test_a_place_closed_that_day_is_clay_not_amber(client, db, hours):
    """The severity split: a closed door is broken, a tight closing time is only a warning."""
    trip = a_trip_with_one_block(client, db)
    shut = (google_weekday(today_utc() + timedelta(days=30)) + 1) % 7
    hours["fn"] = lambda ids: {i: HoursHit(place_id=i, periods=[
        {"open": {"day": shut, "hour": 9, "minute": 0},
         "close": {"day": shut, "hour": 18, "minute": 0}}],
        weekday_descriptions=[], utc_offset_minutes=180) for i in ids}

    warning = export(client, trip)["Itinerary"].cell(row=5, column=8)

    assert warning.value == "closed all day"
    assert warning.fill.fgColor.rgb.endswith(ALERT_BG)


def test_a_days_day_and_date_are_one_tall_cell_each(client, db):
    trip = a_trip_with_one_block(client, db)
    make_place(db, place_id="p2", name="Oodi")
    client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
        {"place_id": "p1", "start_min": 900, "duration_min": 90},
        {"place_id": "p2", "start_min": 1020, "duration_min": 60}]}]})

    ws = export(client, trip)["Itinerary"]

    merged = {str(r) for r in ws.merged_cells.ranges}
    assert "A5:A6" in merged and "B5:B6" in merged
    assert ws.cell(row=5, column=1).value == 1
    assert ws.cell(row=6, column=1).value is None


def test_a_lone_block_is_not_merged(client, db):
    trip = a_trip_with_one_block(client, db)
    assert "A5:A5" not in {str(r) for r in export(client, trip)["Itinerary"].merged_cells.ranges}


def test_a_custom_block_brings_its_details_and_no_warning(client, db):
    trip = a_trip_with_one_block(client, db)
    client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
        {"kind": "custom", "block_id": "b1", "title": "Hotel Bristol",
         "description": "Kristian IVs gate 7, check in from 15:00",
         "start_min": 1260, "duration_min": 120},
        {"place_id": "p1", "start_min": 900, "duration_min": 90}]}]})

    ws = export(client, trip)["Itinerary"]

    assert [c.value for c in ws[3]] == ["Day", "Date", "#", "Start", "End", "Block", "Category",
                                        "Warning", "Details"]
    assert [ws.cell(row=6, column=c).value for c in (4, 6, 7, 8, 9)] == [
        "21:00", "Hotel Bristol", None, None, "Kristian IVs gate 7, check in from 15:00"]
    assert ws.cell(row=5, column=6).value == "Löyly"


def test_the_details_column_exists_only_when_a_block_has_one(client, db):
    trip = a_trip_with_one_block(client, db)
    assert [c.value for c in export(client, trip)["Itinerary"][3]][-1] == "Warning"


def test_a_long_description_wraps_and_the_row_grows_to_hold_it(client, db):
    trip = a_trip_with_one_block(client, db)
    client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
        {"kind": "custom", "block_id": "b1", "title": "Flight AY 71",
         "description": "Finnair AY 71, HEL 17:00 to SIN 09:15 the next day, 13h05 in the air. "
                        "Ref 4KDQ8W. Be at terminal 2 by 14:30 — check-in opens three hours out "
                        "and the tax-free refund desk is before security.",
         "start_min": 900, "duration_min": 120}]}]})

    ws = export(client, trip)["Itinerary"]

    assert ws.cell(row=5, column=9).alignment.wrap_text
    assert ws.row_dimensions[5].height > 15


def test_a_short_row_stays_one_line_tall(client, db):
    ws = export(client, a_trip_with_one_block(client, db))["Itinerary"]
    assert ws.row_dimensions[5].height == 15


def test_the_shortlist_sheet_keeps_the_places_no_day_uses(client, db):
    trip = a_trip_with_one_block(client, db)
    make_place(db, place_id="p2", name="Not used")
    make_mention(db, "p2", source_ref="ref1")

    ws = export(client, trip)["Shortlist"]

    rows = {ws.cell(row=r, column=1).value: ws.cell(row=r, column=4).value for r in (4, 5)}
    assert rows == {"Löyly": "Day 1", "Not used": "not used"}
    # The shortlist's own link is provenance, not the user's booking — hence a different heading.
    assert ws.cell(row=3, column=6).value == "Source"
    assert ws.cell(row=4, column=6).hyperlink.target == "https://www.youtube.com/watch?v=ref1"


def test_a_viewer_can_export_but_a_stranger_cannot(anon_client, client, db):
    trip = a_trip_with_one_block(client, db)
    assert anon_client.get(f"/trips/{trip}/export.xlsx", headers={"Authorization": ""}
                           ).status_code == 401
