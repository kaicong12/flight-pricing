"""The validation core: daylight, opening windows, and the check of a pinned day. No DB, no network."""

from datetime import date

from libs.routing import hhmm, plan_day, sun_times, window_for
from libs.routing.hours import CLOSED
from libs.routing.plan import (
    AFTER_SUNSET,
    CLOSED_TODAY,
    CLOSES_BEFORE_DONE,
    DEFAULT_DURATION,
    MIN_DURATION,
    NO_HOURS,
    OPENS_LATER,
    SLOT_MIN,
    Stop,
)

# Google's periods use 0=Sunday. Two real shapes, taken from live Place Details responses.
ARCTIC_CATHEDRAL = [
    {"open": {"day": 0, "hour": 13, "minute": 0}, "close": {"day": 0, "hour": 18, "minute": 0}},
    {"open": {"day": 1, "hour": 9, "minute": 0}, "close": {"day": 1, "hour": 18, "minute": 0}},
    {"open": {"day": 2, "hour": 9, "minute": 0}, "close": {"day": 2, "hour": 18, "minute": 0}},
]
# Opens 09:00 and closes at midnight, so the close carries the *next* day's number.
FJELLHEISEN = [
    {"open": {"day": 0, "hour": 9, "minute": 0}, "close": {"day": 1, "hour": 0, "minute": 0}},
    {"open": {"day": 1, "hour": 9, "minute": 0}, "close": {"day": 2, "hour": 0, "minute": 0}},
]


class TestDaylight:
    def test_helsinki_in_december_has_about_six_hours(self):
        # Published values are 08:58–15:16. This is an approximation, so it is asserted to the
        # ten minutes that matter for "is this block after dark", not to the minute.
        rise, set_ = sun_times(date(2026, 12, 4), 60.17, 24.94, 120)
        assert abs(rise - (8 * 60 + 58)) < 10
        assert abs(set_ - (15 * 60 + 16)) < 10
        assert 6.0 < (set_ - rise) / 60 < 6.5

    def test_tromso_midwinter_is_polar_night(self):
        assert sun_times(date(2026, 12, 21), 69.65, 18.96, 60) == (None, None)

    def test_tromso_midsummer_is_midnight_sun(self):
        assert sun_times(date(2026, 6, 21), 69.65, 18.96, 120) == (None, None)

    def test_a_temperate_summer_day_is_long(self):
        rise, set_ = sun_times(date(2026, 6, 21), 41.39, 2.17, 120)
        assert set_ - rise > 15 * 60


class TestWindowFor:
    def test_sunday_is_day_zero(self):
        assert window_for(ARCTIC_CATHEDRAL, 0) == (13 * 60, 18 * 60)
        assert window_for(ARCTIC_CATHEDRAL, 1) == (9 * 60, 18 * 60)

    def test_a_close_rolling_past_midnight_clamps_to_end_of_day(self):
        # Not (540, 0), which would read as a window that closes before it opens.
        assert window_for(FJELLHEISEN, 0) == (9 * 60, 24 * 60)

    def test_a_weekday_with_no_period_is_closed(self):
        assert window_for(ARCTIC_CATHEDRAL, 3) == CLOSED

    def test_one_period_with_no_close_is_always_open(self):
        assert window_for([{"open": {"day": 0, "hour": 0, "minute": 0}}], 4) == (0, 24 * 60)

    def test_no_periods_is_unknown_not_closed(self):
        assert window_for([], 1) is None


class TestDurations:
    def test_the_default_is_one_hour_and_grid_aligned(self):
        # There are no per-category durations any more: one hour, and the user drags from there.
        assert DEFAULT_DURATION == 60
        assert DEFAULT_DURATION % SLOT_MIN == 0
        assert MIN_DURATION == SLOT_MIN


def stop(pid, name, *, start, category="see", minutes=60, periods=ARCTIC_CATHEDRAL):
    return Stop(place_id=pid, name=name, category=category, start_min=start,
                duration_min=minutes, periods=periods)


class TestPlanDay:
    def test_blocks_keep_exactly_the_times_they_were_given(self):
        # The old plan_day derived these by accumulating durations and travel. Now they are input.
        plan = plan_day(
            [stop("a", "A", start=600, minutes=60), stop("b", "B", start=690, minutes=30)],
            weekday=1,
        )
        assert [(b.start_min, b.end_min) for b in plan.blocks] == [(600, 660), (690, 720)]
        assert plan.finish_min == 720
        assert plan.warnings == []

    def test_stops_are_checked_in_time_order_whatever_order_they_arrive_in(self):
        plan = plan_day(
            [stop("b", "B", start=690), stop("a", "A", start=600)],
            weekday=1,
        )
        assert [b.place_id for b in plan.blocks] == ["a", "b"]

    def test_two_blocks_at_the_same_time_are_ordered_by_place_id(self):
        # Overlap is a legitimate thing to say about a day, so it needs a stable sequence.
        plan = plan_day([stop("z", "Z", start=600), stop("a", "A", start=600)], weekday=1)
        assert [b.place_id for b in plan.blocks] == ["a", "z"]

    def test_a_single_stop_is_checked_on_its_own(self):
        plan = plan_day([stop("a", "A", start=540, minutes=30)], weekday=1)
        assert plan.blocks[0].start_min == 540
        assert plan.finish_min == 570

    def test_an_empty_day_is_not_an_error(self):
        plan = plan_day([], weekday=1)
        assert plan.blocks == []
        assert plan.warnings == []
        assert plan.finish_min == 0

    def test_a_block_pinned_before_opening_warns_and_is_not_moved(self):
        plan = plan_day([stop("a", "Arctic Cathedral", start=11 * 60, minutes=60)], weekday=0)
        w = [x for x in plan.warnings if x.code == OPENS_LATER]
        assert w[0].detail == {"name": "Arctic Cathedral", "start": "11:00", "opens": "13:00",
                               "early_min": 120}
        # The whole point: the block stays where the user put it.
        assert plan.blocks[0].start_min == 11 * 60

    def test_closing_is_checked_against_the_end_not_the_start(self):
        # In at 17:43 with 30 minutes needed, shut at 18:00. The start alone would look fine.
        plan = plan_day([stop("a", "Uspenski", start=17 * 60 + 43, minutes=30)], weekday=1)
        w = [x for x in plan.warnings if x.code == CLOSES_BEFORE_DONE]
        assert w[0].detail == {"name": "Uspenski", "start": "17:43", "need_min": 30,
                               "closes": "18:00"}

    def test_a_block_wholly_inside_opening_hours_is_silent(self):
        plan = plan_day([stop("a", "A", start=10 * 60, minutes=30)], weekday=1)
        assert plan.warnings == []

    def test_a_day_the_place_is_shut(self):
        plan = plan_day([stop("a", "Arctic Cathedral", start=10 * 60)], weekday=3)
        assert [w.code for w in plan.warnings] == [CLOSED_TODAY]

    def test_unfetched_and_unpublished_hours_both_warn(self):
        for periods in (None, []):
            plan = plan_day([stop("a", "A", start=600, periods=periods)], weekday=1)
            assert [w.code for w in plan.warnings] == [NO_HOURS]

    def test_an_outdoor_stop_after_sunset(self):
        plan = plan_day([stop("a", "Fjellheisen", start=16 * 60, category="see",
                              periods=FJELLHEISEN)], weekday=1, sunset_min=15 * 60 + 29)
        assert [w.code for w in plan.warnings] == [AFTER_SUNSET]

    def test_an_indoor_stop_after_sunset_is_fine(self):
        plan = plan_day([stop("a", "Bar", start=16 * 60, category="drink",
                              periods=FJELLHEISEN)], weekday=1, sunset_min=15 * 60 + 29)
        assert plan.warnings == []

    def test_polar_night_raises_no_sunset_warning(self):
        plan = plan_day([stop("a", "Fjellheisen", start=16 * 60, periods=FJELLHEISEN)], weekday=1, sunset_min=None)
        assert plan.warnings == []

    def test_two_places_an_ocean_apart_are_not_objected_to(self):
        # Travel is not modelled, so nothing here can call a pair unreachable.
        plan = plan_day([stop("a", "Bergen", start=600), stop("b", "Tromso", start=700)],
                        weekday=1)
        assert [b.place_id for b in plan.blocks] == ["a", "b"]
        assert plan.warnings == []


class TestHhmm:
    def test_formats_and_wraps(self):
        assert hhmm(0) == "00:00"
        assert hhmm(9 * 60 + 5) == "09:05"
        assert hhmm(25 * 60) == "01:00"
