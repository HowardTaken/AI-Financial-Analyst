"""
FastAPI application.

    POST /api/analyses              start (or reuse a cached) analysis       -> 202 {id, status, cached}
    GET  /api/analyses/{id}         status + result when finished
    GET  /api/analyses/{id}/events  Server-Sent Events: the agent's tool calls, live
    GET  /api/analyses/{id}/memo.md memo as a Markdown download
    GET  /api/health                liveness + whether a Gemini key is configured

Job ids are unguessable UUIDs and there is no "list all analyses" endpoint, so one visitor can never
see another's results. If `frontend/dist` exists (after `npm run build`) it is served at `/`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from analyst import pipeline
from analyst.config import PROJECT_ROOT, gemini_api_key, gemini_model
from analyst.formatting import result_to_markdown
from analyst.market_data import normalize_ticker
from analyst.models import AnalysisResult

from .jobs import JobManager, QueueFullError, RateLimitedError, SlidingWindowLimiter

log = logging.getLogger(__name__)

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
HEARTBEAT_SECONDS = 15
POLL_SECONDS = 0.25


class AnalysisRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)
    refresh: bool = False  # bypass the result cache

    @field_validator("ticker")
    @classmethod
    def _valid_ticker(cls, v: str) -> str:
        return normalize_ticker(v)  # raises ValueError -> 422


def _client_ip(request: Request) -> str:
    """Client identity for rate limiting. Only trust X-Forwarded-For when behind a known proxy."""
    if os.getenv("ANALYST_TRUST_PROXY", "0") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _sse(event: dict, event_id: int) -> str:
    return f"id: {event_id}\nevent: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


def create_app(
    manager: JobManager | None = None,
    *,
    serve_frontend: bool = True,
) -> FastAPI:
    """App factory; tests inject a JobManager wired to a fake analyzer."""
    if manager is None:
        per_hour = int(os.getenv("ANALYST_RATE_LIMIT_PER_HOUR", "10"))
        manager = JobManager(
            pipeline.analyze,
            max_concurrent=int(os.getenv("ANALYST_MAX_CONCURRENT", "2")),
            limiter=SlidingWindowLimiter(per_hour, 3600) if per_hour > 0 else None,
            preflight=gemini_api_key,  # fail fast with a clear error instead of inside a worker
        )

    app = FastAPI(title="AI Market Analyst API", version="1.0.0")
    app.state.manager = manager

    origins = [o.strip() for o in os.getenv("ANALYST_CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/api/health")
    def health() -> dict:
        try:
            gemini_api_key()
            configured = True
        except OSError:
            configured = False
        return {"status": "ok", "model": gemini_model(), "gemini_configured": configured}

    @app.post("/api/analyses", status_code=202)
    def start_analysis(body: AnalysisRequest, request: Request) -> dict:
        try:
            job, cached = manager.submit(body.ticker, refresh=body.refresh, client=_client_ip(request))
        except RateLimitedError as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after)}) from exc
        except QueueFullError as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "30"}) from exc
        except OSError as exc:  # missing GEMINI_API_KEY
            raise HTTPException(503, "The server is not configured with a Gemini API key.") from exc
        return {"id": job.id, "ticker": job.ticker, "status": job.status, "cached": cached}

    def _job_or_404(job_id: str):
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "Analysis not found (it may have expired).")
        return job

    @app.get("/api/analyses/{job_id}")
    def get_analysis(job_id: str) -> dict:
        return _job_or_404(job_id).summary()

    @app.get("/api/analyses/{job_id}/events")
    async def stream_events(job_id: str, request: Request) -> StreamingResponse:
        job = _job_or_404(job_id)
        try:  # EventSource reconnects send Last-Event-ID so no event is replayed or lost
            index = int(request.headers.get("last-event-id", -1)) + 1
        except ValueError:
            index = 0

        async def generate() -> AsyncIterator[str]:
            nonlocal index
            idle = 0.0
            while True:
                fresh = job.events_since(index)
                for event in fresh:
                    yield _sse(event, index)
                    index += 1
                if fresh:
                    idle = 0.0
                elif job.finished:
                    return
                if await request.is_disconnected():
                    return
                await asyncio.sleep(POLL_SECONDS)
                idle += POLL_SECONDS
                if idle >= HEARTBEAT_SECONDS:
                    yield ": keep-alive\n\n"
                    idle = 0.0

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/analyses/{job_id}/memo.md", response_class=PlainTextResponse)
    def download_memo(job_id: str) -> PlainTextResponse:
        job = _job_or_404(job_id)
        if job.result is None:
            raise HTTPException(409, "The analysis has not finished successfully.")
        text = result_to_markdown(AnalysisResult.from_dict(job.result))
        return PlainTextResponse(text, media_type="text/markdown",
                                 headers={"Content-Disposition": f'attachment; filename="{job.ticker}_memo.md"'})

    if serve_frontend and (FRONTEND_DIST / "index.html").exists():
        app.mount("/", StaticFiles(directory=Path(FRONTEND_DIST), html=True), name="frontend")
    return app


app = create_app()
