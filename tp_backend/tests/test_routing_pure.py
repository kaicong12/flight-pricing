"""The validation core: opening windows, and the check of a pinned day. No DB, no network."""

from libs.routing import hhmm, plan_day, window_for
from libs.routing.hours import CLOSED
from libs.routing.plan import (
    CLOSED_TODAY,
    CLOSES_BEFORE_DONE,
    NO_HOURS,
    OPENS_LATER,
    Stop,
)
from tp_api.route_planning.utils import pieces

# Google's periods use 0=Sunday; shapes taken from live Place Details.
ARCTIC_CATHEDRAL = [
    {"open": {"day": 0, "hour": 13, "minute": 0}, "close": {"day": 0, "hour": 18, "minute": 0}},
    {"open": {"day": 1, "hour": 9, "minute": 0}, "close": {"day": 1, "hour": 18, "minute": 0}},
    {"open": {"day": 2, "hour": 9, "minute": 0}, "close": {"day": 2, "hour": 18, "minute": 0}},
]
# Google gives a midnight close the next day's number.
FJELLHEISEN = [
    {"open": {"day": 0, "hour": 9, "minute": 0}, "close": {"day": 1, "hour": 0, "minute": 0}},
    {"open": {"day": 1, "hour": 9, "minute": 0}, "close": {"day": 2, "hour": 0, "minute": 0}},
]


class TestWindowFor:
    def test_sunday_is_day_zero(self):
        assert window_for(ARCTIC_CATHEDRAL, 0) == (13 * 60, 18 * 60)
        assert window_for(ARCTIC_CATHEDRAL, 1) == (9 * 60, 18 * 60)

    def test_a_close_rolling_past_midnight_clamps_to_end_of_day(self):
        assert window_for(FJELLHEISEN, 0) == (9 * 60, 24 * 60)

    def test_a_weekday_with_no_period_is_closed(self):
        assert window_for(ARCTIC_CATHEDRAL, 3) == CLOSED

    def test_one_period_with_no_close_is_always_open(self):
        assert window_for([{"open": {"day": 0, "hour": 0, "minute": 0}}], 4) == (0, 24 * 60)

    def test_no_periods_is_unknown_not_closed(self):
        assert window_for([], 1) is None


def stop(pid, name, *, start, minutes=60, periods=ARCTIC_CATHEDRAL):
    return Stop(place_id=pid, name=name, start_min=start,
                duration_min=minutes, periods=periods)


class TestPlanDay:
    def test_blocks_keep_exactly_the_times_they_were_given(self):
        plan = plan_day(
            [stop("a", "A", start=600, minutes=60), stop("b", "B", start=690, minutes=30)],
            weekday=1,
        )
        assert [(b.start_min, b.end_min) for b in plan.blocks] == [(600, 660), (690, 720)]
        assert plan.warnings == []

    def test_stops_are_checked_in_time_order_whatever_order_they_arrive_in(self):
        plan = plan_day(
            [stop("b", "B", start=690), stop("a", "A", start=600)],
            weekday=1,
        )
        assert [b.place_id for b in plan.blocks] == ["a", "b"]

    def test_two_blocks_at_the_same_time_are_ordered_by_place_id(self):
        plan = plan_day([stop("z", "Z", start=600), stop("a", "A", start=600)], weekday=1)
        assert [b.place_id for b in plan.blocks] == ["a", "z"]

    def test_a_single_stop_is_checked_on_its_own(self):
        plan = plan_day([stop("a", "A", start=540, minutes=30)], weekday=1)
        assert plan.blocks[0].start_min == 540

    def test_an_empty_day_is_not_an_error(self):
        plan = plan_day([], weekday=1)
        assert plan.blocks == []
        assert plan.warnings == []

    def test_a_block_pinned_before_opening_warns_and_is_not_moved(self):
        plan = plan_day([stop("a", "Arctic Cathedral", start=11 * 60, minutes=60)], weekday=0)
        w = [x for x in plan.warnings if x.code == OPENS_LATER]
        assert w[0].detail == {"name": "Arctic Cathedral", "start": "11:00", "opens": "13:00",
                               "early_min": 120}
        assert plan.blocks[0].start_min == 11 * 60

    def test_closing_is_checked_against_the_end_not_the_start(self):
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


class TestHhmm:
    def test_formats_and_wraps(self):
        assert hhmm(0) == "00:00"
        assert hhmm(9 * 60 + 5) == "09:05"
        assert hhmm(25 * 60) == "01:00"


def test_pieces_split_a_block_at_each_midnight():
    assert pieces(1, 600, 60) == [(1, 600, 660)]
    assert pieces(1, 1350, 460) == [(1, 1350, 1440), (2, 0, 370)]
    assert pieces(0, 1380, 60) == [(0, 1380, 1440)]
    assert pieces(0, 720, 2 * 1440) == [(0, 720, 1440), (1, 0, 1440), (2, 0, 720)]
