"""Call budgets, one Throttler per domain. Mandatory, not advisory: RedNote calls hit a real
logged-in account and the downside is that account being restricted.

History lives in Postgres so every worker shares one budget, and is written on the throttler's own
connection rather than the handler's — a task that rolls back must not refund a call we really made.
"""

import logging
import random
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from libs.db import ThrottleCall, session
from libs.db.enums import ErrorCode
from tp_ingestions.errors import TaskError, Throttled

log = logging.getLogger("throttle")


class BudgetExhausted(RuntimeError):
    """The longest window is spent. Nothing to do but wait it out."""


class Throttler:
    """A budget for one domain: a jittered minimum gap plus any number of sliding windows."""

    def __init__(self, domain: str, *, min_gap: float, jitter: float,
                 limits: list[tuple[int, int]], max_inline_wait: float = 10.0):
        self.domain = domain
        self.min_gap = min_gap
        self.jitter = jitter
        self.limits = sorted(limits, key=lambda l: l[1])
        self.max_inline_wait = max_inline_wait

    @property
    def _longest(self) -> int:
        return self.limits[-1][1] if self.limits else 86400

    def _history(self, s: Session, now: datetime) -> list[datetime]:
        return list(s.scalars(
            select(ThrottleCall.called_at)
            .where(ThrottleCall.domain == self.domain,
                   ThrottleCall.called_at > now - timedelta(seconds=self._longest))
            .order_by(ThrottleCall.called_at)
        ).all())

    def _wait_for(self, calls: list[datetime], now: datetime) -> float:
        """Seconds to wait given this history. Raises when the longest window is spent."""
        waits = [0.0]
        for count, window in self.limits:
            recent = [t for t in calls if (now - t).total_seconds() < window]
            if len(recent) < count:
                continue
            if window == self._longest:
                raise BudgetExhausted(f"{self.domain}: {len(recent)}/{count} calls in {window}s")
            waits.append(window - (now - recent[0]).total_seconds()
                         + random.uniform(0, self.jitter))

        if calls and self.min_gap:
            since = (now - calls[-1]).total_seconds()
            waits.append(self.min_gap + random.uniform(0, self.jitter) - since)
        return max(waits)

    def _lock(self, s: Session) -> None:
        """Serialise this domain's check-and-spend. Released when the transaction ends."""
        s.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"throttle:{self.domain}"))))

    def wait_time(self) -> float:
        now = datetime.now(UTC)
        with session() as s:
            return self._wait_for(self._history(s, now), now)

    def record(self) -> None:
        """Spend one call, committed immediately so it survives the caller rolling back."""
        with session() as s:
            s.add(ThrottleCall(domain=self.domain))
            # Kept small: nothing outside the longest window can affect any decision.
            s.execute(delete(ThrottleCall).where(
                ThrottleCall.domain == self.domain,
                ThrottleCall.called_at < datetime.now(UTC) - timedelta(seconds=self._longest)))
            s.commit()

    def _try_spend(self) -> float:
        """Spend a call and return 0, or return the seconds to wait without spending."""
        now = datetime.now(UTC)
        with session() as s:
            self._lock(s)
            wait = self._wait_for(self._history(s, now), now)
            if wait <= 0:
                s.add(ThrottleCall(domain=self.domain, called_at=now))
                s.commit()
                return 0.0
        return wait

    def take(self) -> None:
        """The gate: reserve a call, hand a long wait back to the queue, or give up for today.

        Checking and spending happen under one lock, so two workers cannot both pass the gate. That
        makes this a reservation — a caller that then fails has still spent the slot, which is the
        safe direction to be wrong in.
        """
        while True:
            try:
                wait = self._try_spend()
            except BudgetExhausted as e:
                raise TaskError(ErrorCode.QUOTA, str(e)) from e
            if wait <= 0:
                return
            if wait > self.max_inline_wait:
                # Handed back via run_after rather than held: sleeping keeps a task lease and a
                # connection, and the queue has no kind filter, so it would stall other sources.
                raise Throttled(f"{self.domain} throttled for {wait:.0f}s",
                                retry_after=timedelta(seconds=wait))
            if wait >= 0.1:
                log.info("throttle: %s sleeping %.1fs", self.domain, wait)
            time.sleep(wait)
