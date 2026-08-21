"""The call budget: pacing, deferral, and the sharing a single external account depends on."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from libs.db import ThrottleCall
from libs.db.enums import ErrorCode
from tp_ingestions import throttle as th
from tp_ingestions.errors import TaskError, Throttled


def rednote(**kw) -> th.Throttler:
    return th.Throttler("rednote", **{"min_gap": 45.0, "jitter": 15.0,
                                      "limits": [(50, 3600), (300, 86400)]} | kw)


def spent(db, domain: str, seconds_ago: float = 0.0) -> None:
    """A call already on the budget, however long ago."""
    db.add(ThrottleCall(domain=domain,
                        called_at=datetime.now(UTC) - timedelta(seconds=seconds_ago)))
    db.commit()


def test_the_first_call_of_the_day_waits_for_nothing(db):
    assert rednote().wait_time() == 0.0


def test_a_second_call_waits_at_least_the_gap(db):
    spent(db, "rednote")

    assert 45.0 <= rednote().wait_time() <= 60.0


def test_the_gap_is_jittered_rather_than_a_fixed_cadence(db):
    """A fixed 45s spacing is a recognisable pattern on a real logged-in account."""
    spent(db, "rednote")
    t = rednote()

    assert len({round(t.wait_time(), 4) for _ in range(30)}) > 1


def test_a_full_window_defers_instead_of_sleeping(db):
    for _ in range(3):
        spent(db, "rednote", 10)

    with pytest.raises(Throttled) as e:
        rednote(limits=[(3, 3600), (300, 86400)]).take()
    assert e.value.retry_after > timedelta(minutes=50)


def test_the_longest_window_running_out_is_a_quota_error(db):
    """Nothing to do but wait for tomorrow, so it is a failure with a 6h policy, not a reschedule."""
    for _ in range(2):
        spent(db, "rednote", 10)

    with pytest.raises(TaskError) as e:
        rednote(limits=[(50, 3600), (2, 86400)]).take()
    assert e.value.code == ErrorCode.QUOTA


def test_a_short_wait_is_slept_inline_then_spent(db, monkeypatch):
    slept = []
    monkeypatch.setattr(th.time, "sleep", slept.append)
    spent(db, "rednote", 1)

    rednote(min_gap=2.0, jitter=0.0).take()

    assert slept and 0 < slept[0] <= 2.0
    assert len(db.scalars(select(ThrottleCall)).all()) == 2


def test_a_long_wait_is_handed_back_to_the_queue(db, monkeypatch):
    monkeypatch.setattr(th.time, "sleep", lambda s: pytest.fail("slept holding a task lease"))
    spent(db, "rednote")

    with pytest.raises(Throttled):
        rednote(min_gap=600.0, jitter=0.0).take()


def test_a_deferred_call_is_not_spent(db):
    """Otherwise a queue of throttled tasks would burn the budget without making a single request."""
    spent(db, "rednote")

    with pytest.raises(Throttled):
        rednote().take()
    assert len(db.scalars(select(ThrottleCall)).all()) == 1


def test_calls_outside_the_longest_window_stop_counting(db):
    spent(db, "rednote", 7200)

    assert rednote(limits=[(1, 3600)]).wait_time() == 0.0


def test_one_domain_running_out_leaves_another_free(db):
    """queue.claim has no kind filter, so a saturated RedNote budget must not stall Gemini."""
    spent(db, "rednote", 10)
    gemini = th.Throttler("gemini", min_gap=0.0, jitter=0.0, limits=[(15, 60), (1000, 86400)])

    with pytest.raises(TaskError):
        rednote(limits=[(1, 3600), (1, 86400)]).take()
    assert gemini.wait_time() == 0.0


def test_the_budget_is_shared_by_every_worker(db):
    """The point of Postgres over a file: one external account, one budget, however many workers."""
    th.Throttler("rednote", min_gap=45.0, jitter=0.0, limits=[(50, 3600)]).take()

    second_worker = th.Throttler("rednote", min_gap=45.0, jitter=0.0, limits=[(50, 3600)])
    assert second_worker.wait_time() > 40


def test_a_spend_survives_the_caller_rolling_back(db):
    """A rolled-back task must not refund a call the remote already served."""
    rednote(min_gap=0.0).take()
    db.rollback()

    assert len(db.scalars(select(ThrottleCall)).all()) == 1


def test_history_beyond_the_longest_window_is_pruned(db):
    spent(db, "rednote", 90000)
    rednote(min_gap=0.0, limits=[(50, 3600), (300, 86400)]).record()

    db.expire_all()
    assert len(db.scalars(select(ThrottleCall)).all()) == 1
