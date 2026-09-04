"""The validation core: daylight, opening windows, and the check of a pinned day. No DB, no network."""

from datetime import date

from libs.routing import hhmm, implausible_walk, plan_day, sun_times, window_for
from libs.routing.hours import CLOSED
from libs.routing.plan import (
    AFTER_SUNSET,
    CLOSED_TODAY,
    CLOSES_BEFORE_DONE,
    DEFAULT_DURATION,
    IMPLAUSIBLE_LEG,
    MIN_DURATION,
    NO_HOURS,
    NO_ROUTE,
    OPENS_LATER,
    SLOT_MIN,
    TRAVEL_DOES_NOT_FIT,
    Stop,
    TravelLeg,
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
        # The old plan_day derived these by accumulating durations and travel. Now they are input:
        # a 9-minute walk into a 30-minute gap changes nothing about where the blocks sit.
        plan = plan_day(
            [stop("a", "A", start=600, minutes=60), stop("b", "B", start=690, minutes=30)],
            [TravelLeg(seconds=9 * 60, meters=700)],
            weekday=1,
        )
        assert [(b.start_min, b.end_min) for b in plan.blocks] == [(600, 660), (690, 720)]
        assert plan.finish_min == 720
        assert plan.warnings == []

    def test_stops_are_checked_in_time_order_whatever_order_they_arrive_in(self):
        plan = plan_day(
            [stop("b", "B", start=690), stop("a", "A", start=600)],
            [TravelLeg(seconds=300, meters=400)],
            weekday=1,
        )
        assert [b.place_id for b in plan.blocks] == ["a", "b"]

    def test_two_blocks_at_the_same_time_are_ordered_by_place_id(self):
        # Overlap is a legitimate thing to say about a day, so it needs a stable sequence.
        plan = plan_day([stop("z", "Z", start=600), stop("a", "A", start=600)], [], weekday=1)
        assert [b.place_id for b in plan.blocks] == ["a", "z"]

    def test_a_single_stop_needs_no_legs(self):
        plan = plan_day([stop("a", "A", start=540, minutes=30)], [], weekday=1)
        assert plan.blocks[0].start_min == 540
        assert plan.finish_min == 570

    def test_an_empty_day_is_not_an_error(self):
        plan = plan_day([], [], weekday=1)
        assert plan.blocks == []
        assert plan.warnings == []
        assert plan.finish_min == 0

    def test_a_block_pinned_before_opening_warns_and_is_not_moved(self):
        plan = plan_day([stop("a", "Arctic Cathedral", start=11 * 60, minutes=60)], [], weekday=0)
        w = [x for x in plan.warnings if x.code == OPENS_LATER]
        assert w[0].detail == {"name": "Arctic Cathedral", "start": "11:00", "opens": "13:00",
                               "early_min": 120}
        # The whole point: the block stays where the user put it.
        assert plan.blocks[0].start_min == 11 * 60

    def test_closing_is_checked_against_the_end_not_the_start(self):
        # In at 17:43 with 30 minutes needed, shut at 18:00. The start alone would look fine.
        plan = plan_day([stop("a", "Uspenski", start=17 * 60 + 43, minutes=30)], [], weekday=1)
        w = [x for x in plan.warnings if x.code == CLOSES_BEFORE_DONE]
        assert w[0].detail == {"name": "Uspenski", "start": "17:43", "need_min": 30,
                               "closes": "18:00"}

    def test_a_block_wholly_inside_opening_hours_is_silent(self):
        plan = plan_day([stop("a", "A", start=10 * 60, minutes=30)], [], weekday=1)
        assert plan.warnings == []

    def test_a_day_the_place_is_shut(self):
        plan = plan_day([stop("a", "Arctic Cathedral", start=10 * 60)], [], weekday=3)
        assert [w.code for w in plan.warnings] == [CLOSED_TODAY]

    def test_unfetched_and_unpublished_hours_both_warn(self):
        for periods in (None, []):
            plan = plan_day([stop("a", "A", start=600, periods=periods)], [], weekday=1)
            assert [w.code for w in plan.warnings] == [NO_HOURS]

    def test_an_outdoor_stop_after_sunset(self):
        plan = plan_day([stop("a", "Fjellheisen", start=16 * 60, category="see",
                              periods=FJELLHEISEN)], [], weekday=1, sunset_min=15 * 60 + 29)
        assert [w.code for w in plan.warnings] == [AFTER_SUNSET]

    def test_an_indoor_stop_after_sunset_is_fine(self):
        plan = plan_day([stop("a", "Bar", start=16 * 60, category="drink",
                              periods=FJELLHEISEN)], [], weekday=1, sunset_min=15 * 60 + 29)
        assert plan.warnings == []

    def test_polar_night_raises_no_sunset_warning(self):
        plan = plan_day([stop("a", "Fjellheisen", start=16 * 60, periods=FJELLHEISEN)], [],
                        weekday=1, sunset_min=None)
        assert plan.warnings == []

    def test_a_zero_second_leg_on_a_routed_day_means_unreachable(self):
        plan = plan_day([stop("a", "A", start=600), stop("b", "B", start=700)],
                        [TravelLeg(seconds=0, meters=0)], weekday=1)
        w = [x for x in plan.warnings if x.code == NO_ROUTE]
        assert w[0].place_id == "b"
        assert w[0].detail == {"from": "A", "to": "B"}

    def test_an_unrouted_day_does_not_claim_places_are_unreachable(self):
        plan = plan_day([stop("a", "A", start=600), stop("b", "B", start=700)],
                        [TravelLeg(seconds=0, meters=0)], weekday=1, routed=False)
        assert [w.code for w in plan.warnings] == []


class TestTravelDoesNotFit:
    def test_a_gap_too_small_for_the_walk(self):
        # A ends 11:00, B starts 11:00, and the walk is 25 minutes.
        plan = plan_day(
            [stop("a", "A", start=600, minutes=60), stop("b", "B", start=660)],
            [TravelLeg(seconds=25 * 60, meters=1800)],
            weekday=1,
        )
        w = [x for x in plan.warnings if x.code == TRAVEL_DOES_NOT_FIT]
        assert w[0].place_id == "b"
        assert w[0].detail == {"from": "A", "to": "B", "need_min": 25, "gap_min": 0}
        # And nothing was moved to make it fit.
        assert [b.start_min for b in plan.blocks] == [600, 660]

    def test_a_gap_that_fits_is_silent(self):
        plan = plan_day(
            [stop("a", "A", start=600, minutes=60), stop("b", "B", start=690)],
            [TravelLeg(seconds=25 * 60, meters=1800)],
            weekday=1,
        )
        assert [w.code for w in plan.warnings] == []

    def test_a_gap_exactly_the_length_of_the_walk_fits(self):
        plan = plan_day(
            [stop("a", "A", start=600, minutes=60), stop("b", "B", start=660 + 25)],
            [TravelLeg(seconds=25 * 60, meters=1800)],
            weekday=1,
        )
        assert [w.code for w in plan.warnings] == []

    def test_deliberately_overlapping_blocks_report_a_negative_gap(self):
        # Allowed and rendered side by side, but you still cannot be in both at once.
        plan = plan_day(
            [stop("a", "A", start=600, minutes=60), stop("b", "B", start=630)],
            [TravelLeg(seconds=300, meters=400)],
            weekday=1,
        )
        w = [x for x in plan.warnings if x.code == TRAVEL_DOES_NOT_FIT]
        assert w[0].detail["gap_min"] == -30
        assert w[0].detail["need_min"] == 5

    def test_an_unrouted_day_makes_no_travel_claim(self):
        plan = plan_day(
            [stop("a", "A", start=600, minutes=60), stop("b", "B", start=660)],
            [TravelLeg(seconds=25 * 60, meters=1800)],
            weekday=1, routed=False,
        )
        assert [w.code for w in plan.warnings] == []


class TestImplausibleWalk:
    def test_the_suomenlinna_shape(self):
        # Google routes the ferry as a walk: ~2 km in ~6.5 min is 19 km/h.
        assert implausible_walk(seconds=380, meters=2000) is True

    def test_a_real_walk_is_plausible(self):
        # 700 m in 9 min is 4.7 km/h.
        assert implausible_walk(seconds=540, meters=700) is False

    def test_zero_values_are_not_claims(self):
        assert implausible_walk(seconds=0, meters=500) is False
        assert implausible_walk(seconds=300, meters=0) is False

    def test_a_walking_day_warns_on_a_ferry_leg(self):
        plan = plan_day([stop("a", "Market", start=600), stop("b", "Fortress", start=700)],
                        [TravelLeg(seconds=380, meters=2000)],
                        weekday=1, mode="walk")
        w = [x for x in plan.warnings if x.code == IMPLAUSIBLE_LEG]
        assert w[0].detail == {"from": "Market", "to": "Fortress", "kmh": 19}

    def test_transit_is_supposed_to_be_fast(self):
        plan = plan_day([stop("a", "A", start=600), stop("b", "B", start=700)],
                        [TravelLeg(seconds=380, meters=2000)],
                        weekday=1, mode="transit")
        assert [w.code for w in plan.warnings] == []


class TestHhmm:
    def test_formats_and_wraps(self):
        assert hhmm(0) == "00:00"
        assert hhmm(9 * 60 + 5) == "09:05"
        assert hhmm(25 * 60) == "01:00"
