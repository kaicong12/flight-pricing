"""Call budget for RedNote. Mandatory, not advisory: calls hit a real logged-in account and the
downside is that account being restricted.

State is a file so the budget survives worker restarts. It is therefore per-host — a second worker
host would get its own budget, so run exactly one RedNote worker until this moves into Postgres.
"""

import json
import os
import random
import time
from pathlib import Path

MIN_GAP = 45.0
JITTER = 15.0
MAX_PER_HOUR = 20
MAX_PER_DAY = 120

STATE = Path(os.environ.get("REDNOTE_THROTTLE_STATE",
                            Path(__file__).resolve().parents[2] / ".rednote_ratelimit.json"))


class BudgetExhausted(RuntimeError):
    """The daily cap is spent. Nothing to do but wait for tomorrow."""


def _history(now: float) -> list[float]:
    try:
        calls = json.loads(STATE.read_text()).get("calls", [])
    except (OSError, ValueError):
        return []
    return [t for t in calls if now - t < 86400]


def wait_time() -> float:
    """Seconds the caller must wait before its next call. Raises when the day's budget is gone."""
    now = time.time()
    day = _history(now)
    if len(day) >= MAX_PER_DAY:
        raise BudgetExhausted(f"{len(day)}/{MAX_PER_DAY} calls used today")

    hour = [t for t in day if now - t < 3600]
    waits = [0.0]
    if len(hour) >= MAX_PER_HOUR:
        waits.append(3601 - (now - min(hour)))
    if day:
        waits.append(MIN_GAP + random.uniform(0, JITTER) - (now - max(day)))
    return max(waits)


def record() -> None:
    """Spend one call from the budget. Call this immediately before the request."""
    now = time.time()
    STATE.write_text(json.dumps({"calls": [*_history(now), now]}))
