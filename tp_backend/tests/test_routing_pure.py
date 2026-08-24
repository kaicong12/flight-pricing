"""The validation core: daylight, opening windows, and the schedule walk. No DB, no network."""

from datetime import date

from libs.routing import hhmm, implausible_walk, plan_day, sun_times, window_for
from libs.routing.hours import CLOSED
from libs.routing.plan import (
    AFTER_SUNSET,
    CLOSED_TODAY,
    CLOSES_BEFORE_DONE,
    IMPLAUSIBLE_LEG,
    NO_HOURS,
    NO_ROUTE,
    OPENS_LATER,
    Stop,
    TravelLeg,
    duration_for,
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
    def test_category_defaults(self):
        assert duration_for("eat") == 75
        assert duration_for("do") == 120

    def test_unknown_and_missing_fall_back(self):
        assert duration_for(None) == 60
        assert duration_for("nonsense") == 60

    def test_sleep_is_zero_in_the_table_but_never_returned_as_zero(self):
        # duration_min has a > 0 CHECK, so a zero default would be unstorable.
        assert duration_for("sleep") == 60


def stop(pid, name, *, category="see", minutes=60, periods=ARCTIC_CATHEDRAL):
    return Stop(place_id=pid, name=name, category=category, duration_min=minutes, periods=periods)


class TestPlanDay:
    def test_blocks_advance_by_duration_plus_travel(self):
        plan = plan_day(
            [stop("a", "A", minutes=60), stop("b", "B", minutes=45)],
            [TravelLeg(seconds=9 * 60, meters=700)],
            weekday=1, start_min=10 * 60,
        )
        assert [(b.start_min, b.end_min) for b in plan.blocks] == [(600, 660), (669, 714)]
        assert plan.finish_min == 714

    def test_a_single_stop_needs_no_legs(self):
        plan = plan_day([stop("a", "A", minutes=30)], [], weekday=1, start_min=9 * 60)
        assert plan.blocks[0].start_min == 540
        assert plan.finish_min == 570

    def test_an_empty_day_is_not_an_error(self):
        plan = plan_day([], [], weekday=1, start_min=540)
        assert plan.blocks == []
        assert plan.warnings == []

    def test_arriving_early_waits_and_pushes_the_rest_of_the_day(self):
        plan = plan_day(
            [stop("a", "Arctic Cathedral", minutes=60), stop("b", "B", minutes=30)],
            [TravelLeg(seconds=0, meters=0)],
            weekday=0, start_min=11 * 60, routed=False,
        )
        w = [x for x in plan.warnings if x.code == OPENS_LATER]
        assert w[0].detail == {"name": "Arctic Cathedral", "arrive": "11:00", "opens": "13:00",
                              "wait_min": 120}
        assert plan.blocks[0].start_min == 13 * 60

    def test_closing_is_checked_against_arrival_plus_duration(self):
        # In at 17:43 with 30 minutes needed, shut at 18:00. Arrival alone would look fine.
        plan = plan_day([stop("a", "Uspenski", minutes=30)], [], weekday=1,
                        start_min=17 * 60 + 43)
        w = [x for x in plan.warnings if x.code == CLOSES_BEFORE_DONE]
        assert w[0].detail == {"name": "Uspenski", "arrive": "17:43", "need_min": 30,
                               "closes": "18:00"}

    def test_arriving_with_enough_time_is_silent(self):
        plan = plan_day([stop("a", "A", minutes=30)], [], weekday=1, start_min=10 * 60)
        assert plan.warnings == []

    def test_a_day_the_place_is_shut(self):
        plan = plan_day([stop("a", "Arctic Cathedral")], [], weekday=3, start_min=10 * 60)
        assert [w.code for w in plan.warnings] == [CLOSED_TODAY]

    def test_unfetched_and_unpublished_hours_both_warn(self):
        for periods in (None, []):
            plan = plan_day([stop("a", "A", periods=periods)], [], weekday=1, start_min=600)
            assert [w.code for w in plan.warnings] == [NO_HOURS]

    def test_an_outdoor_stop_after_sunset(self):
        plan = plan_day([stop("a", "Fjellheisen", category="see", periods=FJELLHEISEN)], [],
                        weekday=1, start_min=16 * 60, sunset_min=15 * 60 + 29)
        assert [w.code for w in plan.warnings] == [AFTER_SUNSET]

    def test_an_indoor_stop_after_sunset_is_fine(self):
        plan = plan_day([stop("a", "Bar", category="drink", periods=FJELLHEISEN)], [],
                        weekday=1, start_min=16 * 60, sunset_min=15 * 60 + 29)
        assert plan.warnings == []

    def test_polar_night_raises_no_sunset_warning(self):
        plan = plan_day([stop("a", "Fjellheisen", periods=FJELLHEISEN)], [], weekday=1,
                        start_min=16 * 60, sunset_min=None)
        assert plan.warnings == []

    def test_a_zero_second_leg_on_a_routed_day_means_unreachable(self):
        plan = plan_day([stop("a", "A"), stop("b", "B")], [TravelLeg(seconds=0, meters=0)],
                        weekday=1, start_min=10 * 60)
        w = [x for x in plan.warnings if x.code == NO_ROUTE]
        assert w[0].place_id == "b"
        assert w[0].detail == {"from": "A", "to": "B"}

    def test_an_unrouted_day_does_not_claim_places_are_unreachable(self):
        plan = plan_day([stop("a", "A"), stop("b", "B")], [TravelLeg(seconds=0, meters=0)],
                        weekday=1, start_min=10 * 60, routed=False)
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
        plan = plan_day([stop("a", "Market"), stop("b", "Fortress")],
                        [TravelLeg(seconds=380, meters=2000)],
                        weekday=1, start_min=10 * 60, mode="walk")
        w = [x for x in plan.warnings if x.code == IMPLAUSIBLE_LEG]
        assert w[0].detail == {"from": "Market", "to": "Fortress", "kmh": 19}

    def test_transit_is_supposed_to_be_fast(self):
        plan = plan_day([stop("a", "A"), stop("b", "B")],
                        [TravelLeg(seconds=380, meters=2000)],
                        weekday=1, start_min=10 * 60, mode="transit")
        assert [w.code for w in plan.warnings] == []


class TestHhmm:
    def test_formats_and_wraps(self):
        assert hhmm(0) == "00:00"
        assert hhmm(9 * 60 + 5) == "09:05"
        assert hhmm(25 * 60) == "01:00"
