"""Background jobs, queued in Postgres and run by worker threads.

The API only ever *enqueues*: it inserts a ``pending`` row and returns its id.
``JobRunner`` threads claim pending rows with ``FOR UPDATE SKIP LOCKED``, run
the handler registered for the job's type, and record the outcome.  Because
the queue lives in the database, a job survives an API restart as long as it
had not started, and the runner can later move to its own container unchanged.

A running job refreshes ``heartbeat_at``.  A job whose heartbeat goes stale —
the process running it died — is marked failed by whichever runner notices,
instead of showing ``running`` forever.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from homecloud.db.models import Job, JobLog
from homecloud.db.session import session_scope

logger = logging.getLogger(__name__)

LogFn = Callable[[str, str], None]

# Terminal states a job can no longer be cancelled from.
_TERMINAL = ("completed", "failed", "cancelled")

HEARTBEAT_INTERVAL = 15.0
# A running job whose heartbeat is older than this belonged to a dead process.
STALE_AFTER = timedelta(seconds=90)
KEEP_JOBS = 500


class JobCancelled(Exception):
    """Raised inside a job's worker when cancellation has been requested."""


def _now() -> datetime:
    return datetime.now(UTC)


def _with_logs(session, jobs: list[Job]) -> list[dict]:
    ids = [j.id for j in jobs]
    logs: dict[str, list[dict]] = {i: [] for i in ids}
    if ids:
        rows = session.scalars(
            select(JobLog).where(JobLog.job_id.in_(ids)).order_by(JobLog.id)
        )
        for row in rows:
            logs[row.job_id].append(row.to_dict())
    return [j.to_dict(logs[j.id]) for j in jobs]


class JobStore:
    """Postgres-backed job queue and log."""

    def __init__(self) -> None:
        # Set on enqueue so idle runner threads in this process pick work up
        # immediately instead of waiting for their next poll.
        self.wake = threading.Event()

    def enqueue(
        self,
        job_type: str,
        *,
        label: str,
        meta: dict | None = None,
        payload: dict | None = None,
    ) -> dict:
        job = Job(
            id=uuid.uuid4().hex[:12],
            type=job_type,
            label=label,
            status="pending",
            meta=meta or {},
            payload=payload or {},
        )
        with session_scope() as session:
            session.add(job)
            session.flush()
            session.refresh(job)
            result = job.to_dict([])
        self.wake.set()
        return result

    def get(self, job_id: str) -> dict | None:
        with session_scope() as session:
            job = session.get(Job, job_id)
            return _with_logs(session, [job])[0] if job else None

    def list(self, *, limit: int = 20) -> list[dict]:
        with session_scope() as session:
            jobs = list(session.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit)))
            return _with_logs(session, jobs)

    def log(self, job_id: str, message: str, level: str = "info") -> None:
        with session_scope() as session:
            session.add(JobLog(job_id=job_id, level=level, message=message))
            session.execute(update(Job).where(Job.id == job_id).values(updated_at=_now()))

    def logger(self, job_id: str) -> LogFn:
        def _log(level: str, message: str) -> None:
            self.log(job_id, message, level)

        return _log

    def request_cancel(self, job_id: str) -> bool:
        """Flag *job_id* for cooperative cancellation.

        A pending job is cancelled outright; a running one stops at its next
        checkpoint.  Returns False when the job is missing or already finished.
        """
        with session_scope() as session:
            job = session.get(Job, job_id, with_for_update=True)
            if job is None or job.status in _TERMINAL:
                return False
            job.cancel_requested = True
            if job.status == "pending":
                job.status = "cancelled"
                job.finished_at = _now()
                session.add(JobLog(job_id=job_id, level="warn", message="Cancelled before start"))
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with session_scope() as session:
            return bool(session.scalar(select(Job.cancel_requested).where(Job.id == job_id)))

    # -- runner side -------------------------------------------------------

    def claim_next(self) -> tuple[str, str, dict] | None:
        """Atomically take the oldest pending job; returns (id, type, payload)."""
        with session_scope() as session:
            job = session.scalars(
                select(Job)
                .where(Job.status == "pending")
                .order_by(Job.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).first()
            if job is None:
                return None
            now = _now()
            job.status = "running"
            job.started_at = now
            job.heartbeat_at = now
            return job.id, job.type, dict(job.payload)

    def finish(
        self,
        job_id: str,
        status: str,
        *,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        with session_scope() as session:
            session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(status=status, result=result, error=error, finished_at=_now())
            )

    def heartbeat(self, job_ids: list[str]) -> None:
        if not job_ids:
            return
        with session_scope() as session:
            session.execute(
                update(Job)
                .where(Job.id.in_(job_ids), Job.status == "running")
                .values(heartbeat_at=_now())
            )

    def fail_stale(self) -> int:
        """Fail running jobs whose process died; returns how many."""
        cutoff = _now() - STALE_AFTER
        message = "Interrupted — the controller stopped while this job was running"
        with session_scope() as session:
            ids = list(
                session.scalars(
                    select(Job.id)
                    .where(Job.status == "running")
                    .where(func.coalesce(Job.heartbeat_at, Job.started_at) < cutoff)
                    .with_for_update(skip_locked=True)
                )
            )
            if not ids:
                return 0
            session.execute(
                update(Job)
                .where(Job.id.in_(ids))
                .values(status="failed", error=message, finished_at=_now())
            )
            session.add_all(JobLog(job_id=i, level="error", message=message) for i in ids)
        for job_id in ids:
            logger.warning("Job %s was interrupted; marked failed", job_id)
        return len(ids)

    def prune(self, keep: int = KEEP_JOBS) -> int:
        """Delete finished jobs beyond the newest *keep*; their logs cascade."""
        with session_scope() as session:
            keep_ids = select(Job.id).order_by(Job.created_at.desc()).limit(keep)
            result = session.execute(
                delete(Job).where(Job.status.in_(_TERMINAL), Job.id.not_in(keep_ids))
            )
            return result.rowcount or 0


job_store = JobStore()


@dataclass(frozen=True)
class JobContext:
    """What a handler gets besides its payload: logging and cancellation."""

    job_id: str
    store: JobStore

    def log(self, level: str, message: str) -> None:
        self.store.log(self.job_id, message, level)

    def cancel_requested(self) -> bool:
        return self.store.is_cancel_requested(self.job_id)


Handler = Callable[[JobContext, dict], Any]


class JobRunner:
    """Worker threads that drain the queue, plus one heartbeat/reaper thread."""

    def __init__(
        self,
        handlers: dict[str, Handler],
        *,
        store: JobStore = job_store,
        workers: int = 4,
        poll_interval: float = 2.0,
    ) -> None:
        self.handlers = handlers
        self.store = store
        self.workers = workers
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._running: set[str] = set()
        self._running_lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self.store.fail_stale()
        self.store.prune()
        for i in range(self.workers):
            self._spawn(self._work, f"job-worker-{i}")
        self._spawn(self._heartbeat, "job-heartbeat")

    def stop(self) -> None:
        """Stop claiming new jobs. Jobs already running are abandoned with the
        process; their heartbeat goes stale and the next runner fails them."""
        self._stop.set()
        self.store.wake.set()

    def _spawn(self, target: Callable[[], None], name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                claimed = self.store.claim_next()
            except Exception:  # noqa: BLE001 — DB blip; keep the worker alive
                logger.exception("Could not claim a job")
                claimed = None
            if claimed is None:
                self.store.wake.wait(self.poll_interval)
                self.store.wake.clear()
                continue
            self._run(*claimed)

    def _run(self, job_id: str, job_type: str, payload: dict) -> None:
        with self._running_lock:
            self._running.add(job_id)
        ctx = JobContext(job_id, self.store)
        try:
            handler = self.handlers.get(job_type)
            if handler is None:
                raise RuntimeError(f"No handler for job type {job_type!r}")
            result = handler(ctx, payload)
            self.store.finish(job_id, "completed", result=result)
        except JobCancelled as exc:
            ctx.log("warn", str(exc) or "Job cancelled")
            self.store.finish(job_id, "cancelled")
        except Exception as exc:  # noqa: BLE001 — every failure lands on the job
            logger.exception("Job %s (%s) failed", job_id, job_type)
            try:
                ctx.log("error", str(exc))
            finally:
                self.store.finish(job_id, "failed", error=str(exc))
        finally:
            with self._running_lock:
                self._running.discard(job_id)

    def _heartbeat(self) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL):
            try:
                with self._running_lock:
                    running = list(self._running)
                self.store.heartbeat(running)
                self.store.fail_stale()
            except Exception:  # noqa: BLE001
                logger.exception("Job heartbeat failed")
