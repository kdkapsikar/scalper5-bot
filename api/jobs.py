"""Background jobs for slow work (a full scan, the full-breadth market mood, a connection test).

The web app starts a job, then polls it for progress, so the page stays responsive while Upstox's rate limits make
a 200+ instrument scan take a minute or two. Jobs run with the caller's keys (their context is copied into the worker)
and are kept in memory for 30 minutes; one job per user and kind runs at a time.
"""
from __future__ import annotations

import contextvars
import secrets
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

KEEP_SECONDS = 1800
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="job")
_JOBS: dict[str, "Job"] = {}
_LOCK = threading.Lock()


@dataclass
class Job:
    id: str
    user_id: int
    kind: str
    status: str = "running"          # running | done | error
    done: int = 0
    total: int = 0
    result: object = None
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0

    def json(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "done": self.done, "total": self.total,
                "result": self.result if self.status == "done" else None, "error": self.error,
                "seconds": round((self.finished or time.time()) - self.started, 1)}


def _cleanup() -> None:
    cutoff = time.time() - KEEP_SECONDS
    for k in [k for k, j in _JOBS.items() if j.status != "running" and j.finished < cutoff]:
        _JOBS.pop(k, None)


def start(user_id: int, kind: str, fn: Callable[[Callable[[int, int], None]], object]) -> Job:
    """Run fn(progress) in the background with the current context (the caller's keys)."""
    with _LOCK:
        _cleanup()
        for j in _JOBS.values():
            if j.user_id == user_id and j.kind == kind and j.status == "running":
                return j
        job = Job(id=secrets.token_urlsafe(12), user_id=user_id, kind=kind)
        _JOBS[job.id] = job

    def progress(done: int, total: int) -> None:
        job.done, job.total = done, total

    def run() -> None:
        try:
            job.result = fn(progress)
            job.status = "done"
        except Exception as e:                    # shown to the user; details stay in the server log
            traceback.print_exc()
            job.error = str(e)[:300] or type(e).__name__
            job.status = "error"
        finally:
            job.finished = time.time()

    _POOL.submit(contextvars.copy_context().run, run)
    return job


def get(job_id: str, user_id: int) -> Job | None:
    j = _JOBS.get(job_id)
    return j if j is not None and j.user_id == user_id else None


def wait(job_id: str, timeout: float = 30.0) -> Job | None:
    """For tests: block until a job finishes."""
    end = time.time() + timeout
    while time.time() < end:
        j = _JOBS.get(job_id)
        if j is None or j.status != "running":
            return j
        time.sleep(0.05)
    return _JOBS.get(job_id)
