"""Background jobs (index builds and ranking runs).

A small ThreadPoolExecutor runs jobs; their state lives in the ``jobs`` table
so the UI can poll progress and the state survives a page reload. Each job
receives a ``JobContext`` with ``progress(fraction, message)`` (throttled DB
writes) and ``cancelled()`` (checked by long loops). Jobs that were running
when the server stopped are marked failed at the next start-up.

Threads rather than processes: the heavy work is NumPy/SciPy/PyTorch code that
releases the GIL, and threads can share the in-memory index cache.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app.database.db import Database, new_id, now

log = logging.getLogger("talentsignal.jobs")
PROGRESS_MIN_INTERVAL_S = 0.5


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, db: Database, job_id: str, cancel_event: threading.Event):
        self.db = db
        self.job_id = job_id
        self._cancel = cancel_event
        self._last = 0.0

    def progress(self, fraction: float, message: str) -> None:
        t = time.monotonic()
        if t - self._last >= PROGRESS_MIN_INTERVAL_S or fraction >= 1.0:
            self._last = t
            self.db.update("jobs", self.job_id, progress=round(max(0.0, min(1.0, fraction)), 4), message=message[:200])

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()


class JobManager:
    def __init__(self, db: Database, workers: int = 2):
        self.db = db
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ts-job")
        self.cancel_events: dict[str, threading.Event] = {}
        db.execute("UPDATE jobs SET status='failed', error='Server restarted while the job was running', "
                   "finished_at=? WHERE status IN ('queued','running')", (now(),))

    def submit(self, kind: str, target_id: str, owner: str | None, fn: Callable[[JobContext], None],
               on_error: Callable[[str], None] | None = None,
               on_cancel: Callable[[], None] | None = None) -> str:
        job_id = new_id()
        self.db.insert("jobs", {"id": job_id, "owner": owner, "kind": kind, "target_id": target_id,
                                "status": "queued", "progress": 0.0, "message": "Queued", "created_at": now()})
        ev = threading.Event()
        self.cancel_events[job_id] = ev

        def run() -> None:
            if ev.is_set():
                self._finish(job_id, "cancelled", "Cancelled before start")
                if on_cancel:
                    on_cancel()
                return
            self.db.update("jobs", job_id, status="running", started_at=now(), message="Starting")
            ctx = JobContext(self.db, job_id, ev)
            try:
                fn(ctx)
                self._finish(job_id, "succeeded", "Done", progress=1.0)
            except JobCancelled:
                self._finish(job_id, "cancelled", "Cancelled")
                if on_cancel:
                    on_cancel()
            except Exception as exc:  # noqa: BLE001 - recorded for the user
                log.exception("Job %s (%s) failed", job_id, kind)
                msg = f"{type(exc).__name__}: {exc}"[:500]
                self._finish(job_id, "failed", "Failed", error=msg)
                if on_error:
                    on_error(msg)
            finally:
                self.cancel_events.pop(job_id, None)

        self.pool.submit(run)
        return job_id

    def _finish(self, job_id: str, status: str, message: str, error: str | None = None,
                progress: float | None = None) -> None:
        fields = {"status": status, "message": message, "finished_at": now(), "error": error}
        if progress is not None:
            fields["progress"] = progress
        self.db.update("jobs", job_id, **fields)

    def cancel(self, job_id: str) -> bool:
        ev = self.cancel_events.get(job_id)
        if ev is None:
            return False
        ev.set()
        return True

    def get(self, job_id: str) -> dict | None:
        return self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def shutdown(self) -> None:
        for ev in self.cancel_events.values():
            ev.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
