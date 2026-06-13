from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JOBS_FILE = Path(".homecloud/jobs.json")
MAX_JOBS = 50

LogFn = Callable[[str, str], None]

# Terminal states a job can no longer be cancelled from.
_TERMINAL = ("completed", "failed", "cancelled")


class JobCancelled(Exception):
    """Raised inside a job's worker when cancellation has been requested."""


class JobStore:
    """In-memory job tracker with lightweight persistence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not JOBS_FILE.exists():
            return
        try:
            data = json.loads(JOBS_FILE.read_text())
            for job in data.get("jobs", [])[-MAX_JOBS:]:
                self._jobs[job["id"]] = job
        except (json.JSONDecodeError, KeyError):
            pass

    def _persist(self) -> None:
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        jobs = sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)[:MAX_JOBS]
        JOBS_FILE.write_text(json.dumps({"jobs": jobs}, indent=2))

    def create(self, job_type: str, *, label: str, meta: dict | None = None) -> dict:
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "type": job_type,
            "label": label,
            "status": "pending",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "meta": meta or {},
            "logs": [],
            "result": None,
            "error": None,
            "cancel_requested": False,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._persist()
        return job

    def start(self, job_id: str) -> None:
        self._update(job_id, status="running")

    def log(self, job_id: str, message: str, level: str = "info") -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "level": level,
            "message": message,
        }
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["logs"].append(entry)
            job["updated_at"] = entry["ts"]
            self._persist()

    def complete(self, job_id: str, result: dict) -> None:
        self._update(job_id, status="completed", result=result)

    def fail(self, job_id: str, error: str) -> None:
        self.log(job_id, error, level="error")
        self._update(job_id, status="failed", error=error)

    def request_cancel(self, job_id: str) -> bool:
        """Flag *job_id* for cooperative cancellation.

        Returns True if the request was recorded (job exists and is not yet in a
        terminal state); False otherwise.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] in _TERMINAL:
                return False
            job["cancel_requested"] = True
            job["updated_at"] = datetime.now(UTC).isoformat()
            self._persist()
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job["cancel_requested"])

    def cancelled(self, job_id: str, message: str = "Job cancelled") -> None:
        self.log(job_id, message, level="warn")
        self._update(job_id, status="cancelled")

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self, *, limit: int = 20) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)
            return [dict(j) for j in jobs[:limit]]

    def logger(self, job_id: str) -> LogFn:
        def _log(level: str, message: str) -> None:
            self.log(job_id, message, level)

        return _log

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(fields)
            job["updated_at"] = datetime.now(UTC).isoformat()
            self._persist()


job_store = JobStore()
