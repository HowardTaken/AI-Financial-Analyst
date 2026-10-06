"""API tests: a real FastAPI app + JobManager wired to a fake analyzer (no network, no API key)."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

from analyst.market_data import DataUnavailableError
from api.app import create_app
from api.jobs import JobManager, SlidingWindowLimiter

from .test_app import build_result


class FakeAnalyzer:
    """Stands in for pipeline.analyze; records calls and can be made slow or failing."""

    def __init__(self, *, error=None, gate: threading.Event | None = None):
        self.error, self.gate, self.calls = error, gate, []

    def __call__(self, ticker, on_event=None, record_prediction=True):
        self.calls.append(ticker)
        on_event({"type": "tool_start", "tool": "get_financial_metrics", "args": {}})
        if self.gate:
            self.gate.wait(timeout=5)
        if self.error:
            raise self.error
        on_event({"type": "tool_end", "tool": "get_financial_metrics", "ok": True, "summary": "ok", "seconds": 0.1})
        return build_result()


def make_client(analyzer=None, **manager_kwargs):
    analyzer = analyzer or FakeAnalyzer()
    manager = JobManager(analyzer, **manager_kwargs)
    return TestClient(create_app(manager, serve_frontend=False)), analyzer, manager


def wait_done(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/analyses/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "data" in fields:
            events.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return events


# ── lifecycle ────────────────────────────────────────────────────────────────

def test_health_reports_configuration(monkeypatch):
    client, *_ = make_client()
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["gemini_configured"] is True


def test_full_lifecycle_returns_structured_result():
    client, analyzer, _ = make_client()
    resp = client.post("/api/analyses", json={"ticker": "test"})
    assert resp.status_code == 202
    job = resp.json()
    assert job["ticker"] == "TEST" and job["cached"] is False

    body = wait_done(client, job["id"])
    assert body["status"] == "done" and body["error"] is None
    assert body["result"]["memo"]["rating"] == "BUY"
    assert body["result"]["metrics"]["ticker"] == "TEST"
    assert analyzer.calls == ["TEST"]


def test_event_stream_replays_in_order_and_ends():
    client, *_ = make_client()
    job_id = client.post("/api/analyses", json={"ticker": "TEST"}).json()["id"]
    wait_done(client, job_id)
    with client.stream("GET", f"/api/analyses/{job_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse("".join(r.iter_text()))
    assert [e[1] for e in events] == ["started", "tool_start", "tool_end", "done"]
    assert [e[0] for e in events] == [0, 1, 2, 3]
    assert all("t" in e[2] for e in events)


def test_event_stream_resumes_after_last_event_id():
    client, *_ = make_client()
    job_id = client.post("/api/analyses", json={"ticker": "TEST"}).json()["id"]
    wait_done(client, job_id)
    with client.stream("GET", f"/api/analyses/{job_id}/events", headers={"Last-Event-ID": "1"}) as r:
        events = parse_sse("".join(r.iter_text()))
    assert [e[1] for e in events] == ["tool_end", "done"]


def test_event_stream_works_while_job_is_still_running():
    gate = threading.Event()
    client, *_ = make_client(FakeAnalyzer(gate=gate))
    job_id = client.post("/api/analyses", json={"ticker": "TEST"}).json()["id"]
    threading.Timer(0.3, gate.set).start()  # release the "agent" shortly after the stream opens
    with client.stream("GET", f"/api/analyses/{job_id}/events") as r:
        events = parse_sse("".join(r.iter_text()))
    assert events[-1][1] == "done"


def test_memo_download():
    client, *_ = make_client()
    job_id = client.post("/api/analyses", json={"ticker": "TEST"}).json()["id"]
    wait_done(client, job_id)
    r = client.get(f"/api/analyses/{job_id}/memo.md")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "# TEST: BUY" in r.text and "not financial advice" in r.text


def test_memo_download_before_finish_is_409():
    gate = threading.Event()
    client, *_ = make_client(FakeAnalyzer(gate=gate))
    job_id = client.post("/api/analyses", json={"ticker": "TEST"}).json()["id"]
    assert client.get(f"/api/analyses/{job_id}/memo.md").status_code == 409
    gate.set()


# ── validation & privacy ─────────────────────────────────────────────────────

@pytest.mark.parametrize("ticker", ["", "AAPL; DROP", "<script>", "WAYTOOLONGTICKER", "A B"])
def test_invalid_tickers_are_rejected_with_422(ticker):
    client, analyzer, _ = make_client()
    assert client.post("/api/analyses", json={"ticker": ticker}).status_code == 422
    assert analyzer.calls == []


def test_unknown_job_is_404_and_there_is_no_listing_endpoint():
    client, *_ = make_client()
    assert client.get("/api/analyses/doesnotexist").status_code == 404
    assert client.get("/api/analyses/doesnotexist/events").status_code == 404
    assert client.get("/api/analyses").status_code in (404, 405)  # no way to enumerate others' results


# ── caching, dedupe, limits ──────────────────────────────────────────────────

def test_finished_analyses_are_cached_and_refresh_bypasses_cache():
    client, analyzer, _ = make_client()
    first = client.post("/api/analyses", json={"ticker": "TEST"}).json()
    wait_done(client, first["id"])
    second = client.post("/api/analyses", json={"ticker": "test"}).json()
    assert second["cached"] is True and second["id"] == first["id"] and analyzer.calls == ["TEST"]
    third = client.post("/api/analyses", json={"ticker": "TEST", "refresh": True}).json()
    assert third["cached"] is False and third["id"] != first["id"]
    wait_done(client, third["id"])
    assert analyzer.calls == ["TEST", "TEST"]


def test_concurrent_identical_requests_share_one_run():
    gate = threading.Event()
    client, analyzer, _ = make_client(FakeAnalyzer(gate=gate))
    a = client.post("/api/analyses", json={"ticker": "TEST"}).json()
    b = client.post("/api/analyses", json={"ticker": "TEST"}).json()
    gate.set()
    assert a["id"] == b["id"] and b["cached"] is True
    wait_done(client, a["id"])
    assert analyzer.calls == ["TEST"]


def test_rate_limit_returns_429_with_retry_after_and_cache_hits_are_free():
    client, *_ = make_client(limiter=SlidingWindowLimiter(2, 3600))
    for t in ("AAA", "BBB"):
        wait_done(client, client.post("/api/analyses", json={"ticker": t}).json()["id"])
    blocked = client.post("/api/analyses", json={"ticker": "CCC"})
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    assert client.post("/api/analyses", json={"ticker": "AAA"}).status_code == 202  # cached: no quota used


def test_sliding_window_limiter_expires_old_hits():
    limiter = SlidingWindowLimiter(2, 100)
    limiter.check("ip", now=0)
    limiter.check("ip", now=10)
    with pytest.raises(Exception, match="Rate limit"):
        limiter.check("ip", now=20)
    limiter.check("ip", now=101)  # first hit has aged out
    limiter.check("other", now=20)  # keys are independent


def test_full_queue_returns_503():
    gate = threading.Event()
    client, *_ = make_client(FakeAnalyzer(gate=gate), max_concurrent=1, max_queued=0)
    assert client.post("/api/analyses", json={"ticker": "AAA"}).status_code == 202
    busy = client.post("/api/analyses", json={"ticker": "BBB"})
    gate.set()
    assert busy.status_code == 503 and "busy" in busy.json()["detail"]


def test_missing_api_key_fails_fast_with_503():
    def no_key():
        raise OSError("GEMINI_API_KEY is not set")

    client, analyzer, _ = make_client(preflight=no_key)
    r = client.post("/api/analyses", json={"ticker": "TEST"})
    assert r.status_code == 503 and "Gemini API key" in r.json()["detail"] and analyzer.calls == []


# ── error handling ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("error,code", [
    (ValueError("bad input"), "invalid_request"),
    (DataUnavailableError("No financial statements found for 'ZZZZ'."), "no_data"),
    (genai_errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}), "llm_quota"),
])
def test_known_failures_become_error_jobs_with_codes(error, code):
    client, *_ = make_client(FakeAnalyzer(error=error))
    body = wait_done(client, client.post("/api/analyses", json={"ticker": "TEST"}).json()["id"])
    assert body["status"] == "error" and body["error_code"] == code and body["result"] is None


def test_unexpected_errors_do_not_leak_internals():
    client, *_ = make_client(FakeAnalyzer(error=RuntimeError("secret path C:/internal/key=abc")))
    job_id = client.post("/api/analyses", json={"ticker": "TEST"}).json()["id"]
    body = wait_done(client, job_id)
    assert body["error_code"] == "internal" and "secret" not in json.dumps(body)
    with client.stream("GET", f"/api/analyses/{job_id}/events") as r:
        events = parse_sse("".join(r.iter_text()))
    assert events[-1][1] == "error" and "secret" not in json.dumps(events)


def test_failed_analyses_are_not_cached():
    analyzer = FakeAnalyzer(error=ValueError("nope"))
    client, _, _ = make_client(analyzer)
    wait_done(client, client.post("/api/analyses", json={"ticker": "TEST"}).json()["id"])
    again = client.post("/api/analyses", json={"ticker": "TEST"}).json()
    assert again["cached"] is False
    wait_done(client, again["id"])
    assert analyzer.calls == ["TEST", "TEST"]


def test_cors_allows_the_configured_dev_origin():
    client, *_ = make_client()
    r = client.options("/api/analyses", headers={"Origin": "http://localhost:5173",
                                                 "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
