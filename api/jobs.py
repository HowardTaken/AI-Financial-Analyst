"""
In-memory job manager: runs analyses on a bounded worker pool and records their event streams.

An analysis takes 1-3 minutes, so the HTTP layer never blocks on it. A request creates a Job, a
worker runs the agent and appends its events to the job, and clients either poll the job or follow
its event stream. Finished jobs are cached per ticker so repeat requests don't spend Gemini quota.

State lives in process memory by design (simple, no database). Run a single worker process.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from google.genai import errors as genai_errors

from analyst.agent import AgentError
from analyst.market_data import DataUnavailableError, normalize_ticker
from analyst.models import AnalysisResult
from analyst.sec import FilingNotFoundError

log = logging.getLogger(__name__)

AnalyzeFn = Callable[..., AnalysisResult]


class QueueFullError(RuntimeError):
    """Too many analyses are already running or waiting."""


class RateLimitedError(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__(f"Rate limit reached. Try again in {retry_after} seconds.")
        self.retry_after = retry_after


@dataclass
class Job:
    id: str
    ticker: str
    created_at: float = field(default_factory=time.time)
    status: str = "queued"          # queued -> running -> done | error
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    finished_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def finished(self) -> bool:
        return self.status in ("done", "error")

    def add_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append({**event, "t": round(time.time() - self.created_at, 2)})

    def events_since(self, index: int) -> list[dict[str, Any]]:
        with self._lock:
            return self.events[index:]

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id, "ticker": self.ticker, "status": self.status,
            "created_at": self.created_at, "finished_at": self.finished_at,
            "error": self.error, "error_code": self.error_code,
            "result": self.result,
        }


class SlidingWindowLimiter:
    """Per-key sliding-window limiter (e.g. N new analyses per hour per client IP)."""

    def __init__(self, max_events: int, window_seconds: int):
        self.max_events, self.window = max_events, window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> None:
        """Record a hit for `key`, or raise RateLimitedError if the window is full."""
        now = time.time() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.max_events:
                raise RateLimitedError(int(hits[0] + self.window - now) + 1)
            hits.append(now)


def classify_error(exc: Exception) -> tuple[str, str]:
    """Map an exception to (error_code, message that is safe to show a client)."""
    if isinstance(exc, ValueError):
        return "invalid_request", str(exc)
    if isinstance(exc, DataUnavailableError):
        return "no_data", str(exc)
    if isinstance(exc, FilingNotFoundError):
        return "no_filing", str(exc)
    if isinstance(exc, genai_errors.APIError):
        if exc.code == 429:
            return "llm_quota", "The Gemini API quota is exhausted. Wait a minute and try again."
        return "llm_error", f"The Gemini API returned an error ({exc.code})."
    if isinstance(exc, AgentError):
        return "agent_failed", str(exc)
    return "internal", "Unexpected server error."


class JobManager:
    def __init__(
        self,
        analyze_fn: AnalyzeFn,
        *,
        max_concurrent: int = 2,
        max_queued: int = 8,
        job_ttl: int = 3600,
        cache_ttl: int = 1800,
        limiter: SlidingWindowLimiter | None = None,
        preflight: Callable[[], None] | None = None,
    ):
        self._analyze = analyze_fn
        self._pool = ThreadPoolExecutor(max_workers=max_concurrent, thread_name_prefix="analysis")
        self._max_active = max_concurrent + max_queued
        self.job_ttl, self.cache_ttl = job_ttl, cache_ttl
        self.limiter = limiter
        self._preflight = preflight
        self._jobs: dict[str, Job] = {}
        self._latest_by_ticker: dict[str, str] = {}
        self._lock = threading.Lock()

    # ── public API ───────────────────────────────────────────────────────────
    def submit(self, ticker: str, *, refresh: bool = False, client: str = "anonymous") -> tuple[Job, bool]:
        """Start (or reuse) an analysis. Returns (job, was_cached)."""
        ticker = normalize_ticker(ticker)
        with self._lock:
            self._purge_locked()
            if not refresh and (cached := self._fresh_cached_locked(ticker)):
                return cached, True
            # An identical analysis already in flight is shared rather than duplicated.
            if (running := self._active_for_locked(ticker)):
                return running, True
            if sum(1 for j in self._jobs.values() if not j.finished) >= self._max_active:
                raise QueueFullError("The analyst is busy right now. Please try again shortly.")
            if self._preflight:
                self._preflight()
            if self.limiter:
                self.limiter.check(client)
            job = Job(id=uuid.uuid4().hex, ticker=ticker)
            self._jobs[job.id] = job
            self._latest_by_ticker[ticker] = job.id
        self._pool.submit(self._run, job)
        return job, False

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ── internals ────────────────────────────────────────────────────────────
    def _run(self, job: Job) -> None:
        job.status = "running"
        job.add_event({"type": "started", "ticker": job.ticker})
        try:
            result = self._analyze(job.ticker, on_event=job.add_event, record_prediction=True)
            job.result = result.to_dict()
            job.status = "done"
            job.add_event({"type": "done"})
        except Exception as exc:
            job.error_code, job.error = classify_error(exc)
            if job.error_code == "internal":
                log.exception("Analysis of %s failed", job.ticker)
            else:
                log.warning("Analysis of %s failed (%s): %s", job.ticker, job.error_code, exc)
            job.status = "error"
            job.add_event({"type": "error", "code": job.error_code, "message": job.error})
        finally:
            job.finished_at = time.time()

    def _fresh_cached_locked(self, ticker: str) -> Job | None:
        job = self._jobs.get(self._latest_by_ticker.get(ticker, ""))
        if job and job.status == "done" and job.finished_at and time.time() - job.finished_at < self.cache_ttl:
            return job
        return None

    def _active_for_locked(self, ticker: str) -> Job | None:
        job = self._jobs.get(self._latest_by_ticker.get(ticker, ""))
        return job if job and not job.finished else None

    def _purge_locked(self) -> None:
        cutoff = time.time() - self.job_ttl
        for job_id in [i for i, j in self._jobs.items() if j.finished and (j.finished_at or 0) < cutoff]:
            job = self._jobs.pop(job_id)
            if self._latest_by_ticker.get(job.ticker) == job_id:
                del self._latest_by_ticker[job.ticker]
