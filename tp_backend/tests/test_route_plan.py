"""route.plan: the sanitiser that stands between a model reply and the itinerary write."""

from datetime import date, time

from libs.db import Trip
from tp_ingestions.plan.draft import CAP, keep, window


def trip(arrive=time(14, 45), depart=None, days=2) -> Trip:
    return Trip(arrive_date=date(2026, 9, 19), depart_date=date(2026, 9, 19 + days - 1),
                arrive_time=arrive, depart_time=depart)


def picks(*items) -> dict:
    return {"days": [{"day": 0, "picks": list(items)}]}


def test_window_is_clamped_to_the_drawable_grid():
    assert window(trip(arrive=time(1, 36)), 0) == (8 * 60, 23 * 60)
    assert window(trip(arrive=time(14, 45)), 0) == (885, 23 * 60)
    assert window(trip(depart=time(18, 5), days=2), 1) == (8 * 60, 1085)


def test_a_block_before_landing_is_floored_to_the_grid():
    kept = keep(trip(), picks({"index": 0, "start_min": 540, "duration_min": 60}), 4, [0])
    assert kept == {0: [(0, 900, 60)]}  # 14:45 landing -> first usable grid minute is 15:00


def test_off_grid_times_are_snapped():
    kept = keep(trip(), picks({"index": 1, "start_min": 1010, "duration_min": 47}), 4, [0])
    assert kept == {0: [(1, 1020, 60)]}


def test_an_index_we_never_sent_is_dropped():
    assert keep(trip(), picks({"index": 99, "start_min": 900, "duration_min": 60}), 4, [0]) == {0: []}


def test_a_repeated_place_is_kept_once():
    kept = keep(trip(), picks({"index": 2, "start_min": 900, "duration_min": 60},
                              {"index": 2, "start_min": 1080, "duration_min": 60}), 4, [0])
    assert kept == {0: [(2, 900, 60)]}


def test_a_block_running_past_the_window_is_dropped():
    kept = keep(trip(), picks({"index": 0, "start_min": 1350, "duration_min": 60}), 4, [0])
    assert kept == {0: []}  # 22:30 + 60 = 23:30, past the 23:00 bound


def test_a_day_we_did_not_offer_is_ignored():
    reply = {"days": [{"day": 1, "picks": [{"index": 0, "start_min": 900, "duration_min": 60}]}]}
    assert keep(trip(), reply, 4, [0]) == {}


def test_a_place_proven_closed_all_day_cannot_come_back():
    item = {"index": 3, "start_min": 900, "duration_min": 60}
    assert keep(trip(), picks(item), 4, [0]) == {0: [(3, 900, 60)]}
    assert keep(trip(), picks(item), 4, [0], shut={(0, 3)}) == {0: []}


def test_a_day_is_capped_and_returned_in_time_order():
    reply = picks(*[{"index": i, "start_min": 1320 - i * 30, "duration_min": 30} for i in range(8)])
    kept = keep(trip(), reply, 8, [0])
    assert len(kept[0]) == CAP
    assert [start for _, start, _ in kept[0]] == sorted(start for _, start, _ in kept[0])


def test_a_reply_with_no_days_is_not_an_error():
    assert keep(trip(), {}, 4, [0]) == {}
    assert keep(trip(), {"days": None}, 4, [0]) == {}
