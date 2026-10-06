"""Cache, formatting, transcripts parsing, history and predictions."""

import json
import time

import pytest

from analyst import history, predictions
from analyst.cache import ttl_cache
from analyst.formatting import fmt_num, memo_to_markdown, peer_table_html
from analyst.market_data import normalize_ticker
from analyst.models import AnalysisResult, DCFResult, Memo, Metrics, Peer, TraceStep
from analyst.sec import _clean_lines
from analyst.transcripts import parse_sections


def make_memo(**kw):
    base = dict(rating="BUY", confidence="HIGH", price_target=120.0, headline="Strong.",
                quantitative_case="Q", filing_vs_call="F", key_risks=["r1"], catalysts=["c1"],
                verdict="V", data_gaps=["no DCF"])
    return Memo(**{**base, **kw})


def make_result(ticker="ABC", **kw):
    m = Metrics(ticker, "2025-09-30", "2024-09-30", 100.0, pe_ratio=20.0)
    peer = Peer("PEER", "Peer Co", 1.0, market_cap=5e9, metrics=Metrics("PEER", "2025", "2024", 50.0, pe_ratio=10.0))
    return AnalysisResult(ticker, make_memo(), m, DCFResult.unavailable("bank", ticker), None, [peer],
                          trace=[TraceStep(1, "get_financial_metrics", {}, True, 1.2, "ok")],
                          warnings=["w"], created_at="2026-01-01T00:00:00+00:00", **kw)


# ── cache ────────────────────────────────────────────────────────────────────

def test_ttl_cache_hits_expires_and_does_not_cache_errors():
    n = {"calls": 0}

    @ttl_cache(0.05)
    def f(x):
        n["calls"] += 1
        if x == "bad":
            raise RuntimeError
        return x * 2

    assert f(2) == 4 and f(2) == 4 and n["calls"] == 1
    time.sleep(0.07)
    f(2)
    assert n["calls"] == 2
    for _ in range(2):
        with pytest.raises(RuntimeError):
            f("bad")
    assert n["calls"] == 4


# ── tickers / formatting ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [("aapl", "AAPL"), (" brk-b ", "BRK-B"), ("BF.B", "BF.B")])
def test_normalize_ticker_accepts(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "A B", "AAPL;", "<script>", "WAYTOOLONGTICKER", None])
def test_normalize_ticker_rejects(raw):
    with pytest.raises(ValueError):
        normalize_ticker(raw)


def test_fmt_num_handles_none_and_specs():
    assert fmt_num(None, ".2f", prefix="$") == "N/A"
    assert fmt_num(123.456, ".2f", prefix="$") == "$123.46"
    assert fmt_num(0, ".1f", suffix="%") == "0.0%"  # zero is a value, not missing


def test_memo_markdown_contains_all_sections():
    md = memo_to_markdown("ABC", make_memo(), ["careful"])
    for needle in ("# ABC: BUY (High confidence)", "$120.00", "## Quantitative case", "## Key risks",
                   "- r1", "## Catalysts", "## Verdict", "## Data gaps", "careful", "not financial advice"):
        assert needle in md


def test_peer_table_escapes_html_and_marks_best_worst():
    target = Metrics("<b>X</b>", "2025", "2024", 100.0, pe_ratio=30.0, gross_margin_pct=50.0)
    peers = [Peer("P1", metrics=Metrics("P1", "2025", "2024", 10.0, pe_ratio=10.0, gross_margin_pct=20.0)),
             Peer("P2", error="boom")]
    html = peer_table_html(target, peers, {"pe_ratio": 10.0})
    assert "<b>X</b>" not in html and "&lt;b&gt;X&lt;/b&gt;" in html
    assert "▲" in html and "▼" in html
    assert "P2" not in html  # failed peers are not columns


# ── transcript parsing ───────────────────────────────────────────────────────

def test_parse_sections_splits_on_numbered_headings():
    text = "CALL DATE: 2026-01-30\n\n## 1. Opening Remarks & Results\n- rev up\n## 2. Forward Guidance\n- guide"
    secs = parse_sections(text)
    assert [s["heading"] for s in secs] == ["Call Overview", "Opening Remarks & Results", "Forward Guidance"]
    assert secs[1]["body"] == "- rev up"


def test_parse_sections_falls_back_to_single_block():
    assert parse_sections("just prose")[0] == {"heading": "Earnings Call Summary", "body": "just prose"}


def test_clean_lines_collapses_blank_runs():
    assert _clean_lines(["a", "", "", "", "b"]) == "a\n\nb"


# ── history & predictions ────────────────────────────────────────────────────

def test_result_roundtrips_through_json():
    r = make_result()
    again = AnalysisResult.from_dict(json.loads(json.dumps(r.to_dict())))
    assert again.memo == r.memo and again.metrics == r.metrics and again.dcf == r.dcf
    assert again.peers[0].metrics == r.peers[0].metrics and again.trace == r.trace


def test_history_is_session_only_unless_enabled(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    monkeypatch.delenv("ANALYST_PERSIST_HISTORY", raising=False)
    history.save([make_result()], path)
    assert not path.exists()  # nothing written: safe default for shared deployments

    monkeypatch.setenv("ANALYST_PERSIST_HISTORY", "1")
    history.save([make_result()], path)
    assert history.load(path)[0].ticker == "ABC"


def test_history_ignores_corrupt_or_legacy_files(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYST_PERSIST_HISTORY", "1")
    path = tmp_path / "history.json"
    path.write_text("[{\"ticker\": \"OLD\"}]")  # legacy list format
    assert history.load(path) == []
    path.write_text("{not json")
    assert history.load(path) == []


def test_history_add_dedupes_and_caps():
    items = [make_result(f"T{i}") for i in range(30)]
    h = []
    for r in items:
        h = history.add(h, r)
    assert len(h) == history.MAX_ENTRIES and h[0].ticker == "T29"
    h = history.add(h, make_result("T10"))
    assert h[0].ticker == "T10" and [x.ticker for x in h].count("T10") == 1


def test_prediction_log_appends_jsonl(tmp_path):
    path = tmp_path / "p.jsonl"
    predictions.log_prediction(make_result("AAA"), path)
    predictions.log_prediction(make_result("BBB"), path)
    rows = predictions.load_predictions(path)
    assert [r["ticker"] for r in rows] == ["AAA", "BBB"]
    assert rows[0]["rating"] == "BUY" and rows[0]["price"] == 100.0 and rows[0]["dcf_upside_pct"] is None
