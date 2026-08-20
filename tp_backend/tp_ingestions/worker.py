"""The polling loop: claim a task, run its handler, settle it, settle the run."""

import logging
import os
import signal
import socket
import time
from datetime import UTC, datetime, timedelta

from libs.db import session
from libs.db.enums import ErrorCode
from tp_ingestions import queue
from tp_ingestions.errors import TaskError, Throttled
from tp_ingestions.registry import HANDLERS, load_handlers
from tp_ingestions.retry import retry_after

log = logging.getLogger("worker")

LEASE = timedelta(minutes=10)
POLL_INTERVAL = 2.0
REAP_INTERVAL = 60.0


def worker_name() -> str:
    return f"{socket.gethostname().split('.')[0]}:{os.getpid()}"[:64]


class Worker:
    def __init__(self, name: str | None = None, poll_interval: float = POLL_INTERVAL,
                 lease: timedelta = LEASE, reap_interval: float = REAP_INTERVAL):
        self.name = name or worker_name()
        self.poll_interval = poll_interval
        self.lease = lease
        self.reap_interval = reap_interval
        self._stop = False
        self._last_reap = 0.0
        load_handlers()

    def stop(self, *_) -> None:
        log.info("stopping after the current task")
        self._stop = True

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self.stop)

    def run_forever(self) -> None:
        log.info("worker %s polling every %.1fs (%d handlers)", self.name, self.poll_interval,
                 len(HANDLERS))
        while not self._stop:
            self._maybe_reap()
            if not self.run_once():
                time.sleep(self.poll_interval)

    def drain(self, max_tasks: int = 1000) -> int:
        """Run until the queue has nothing due, then return how many tasks ran."""
        self._maybe_reap()
        ran = 0
        while ran < max_tasks and not self._stop and self.run_once():
            ran += 1
        log.info("drained %d task(s)", ran)
        return ran

    def run_once(self) -> bool:
        """Claim and execute one task. False when nothing was due."""
        # Claimed in its own transaction so the row lock is released immediately; from here on the
        # lease in locked_at is what stops a second worker taking it. The run is marked running
        # here too — doing it alongside the handler would roll back whenever the handler failed.
        with session() as s:
            task = queue.claim(s, self.name)
            if task is not None:
                queue.mark_running(s, task.run_id)
        if task is None:
            return False

        log.info("task %s %s attempt %d", task.task_id, task.kind, task.attempts)
        self._execute(task)
        with session() as s:
            settled = queue.finish_run_if_done(s, task.run_id)
        if settled:
            log.info("run %s -> %s", task.run_id, settled)
        return True

    def _execute(self, task: queue.ClaimedTask) -> None:
        handler = HANDLERS.get(task.kind)
        if handler is None:
            log.warning("task %s no handler for %s — blocking", task.task_id, task.kind)
            with session() as s:
                queue.block(s, task.task_id, f"no handler registered for {task.kind}")
            return

        try:
            # Handler writes and the task's completion commit together, so a crash mid-handler
            # leaves nothing half-applied and the lease hands the task to the next worker.
            with session() as s:
                result = handler(s, task)
                queue.complete(s, task.task_id)
            log.info("task %s done %s", task.task_id, result or "")
        except Throttled as e:
            when = datetime.now(UTC) + e.retry_after
            log.info("task %s waiting %.0fs for budget", task.task_id,
                     e.retry_after.total_seconds())
            with session() as s:
                queue.reschedule(s, task.task_id, str(e), when)
        except TaskError as e:
            self._settle_failure(task, e.code, str(e), e.retry_after)
        except Exception as e:
            log.exception("task %s crashed", task.task_id)
            self._settle_failure(task, ErrorCode.TRANSIENT, f"{type(e).__name__}: {e}", None)

    def _settle_failure(self, task: queue.ClaimedTask, code: ErrorCode, error: str,
                        override: timedelta | None) -> None:
        wait = override if override is not None else retry_after(code, task.attempts)
        exhausted = task.attempts >= task.max_attempts
        with session() as s:
            if wait is None or exhausted:
                reason = "attempts exhausted" if wait is not None else f"{code} is terminal"
                log.warning("task %s failed (%s): %s", task.task_id, reason, error[:200])
                queue.fail(s, task.task_id, code, error)
            else:
                when = datetime.now(UTC) + wait
                log.warning("task %s deferred %.0fs (%s): %s", task.task_id, wait.total_seconds(),
                            code, error[:200])
                queue.defer(s, task.task_id, code, error, when)

    def _maybe_reap(self) -> None:
        now = time.monotonic()
        if now - self._last_reap < self.reap_interval:
            return
        self._last_reap = now
        with session() as s:
            reclaimed = queue.reap_expired(s, self.lease)
        if reclaimed:
            log.warning("reclaimed %d task(s) from expired leases: %s", len(reclaimed), reclaimed)
