"""Headless UI tests: run app.py with Streamlit's AppTest and a stubbed analysis pipeline."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from analyst import pipeline
from analyst.models import AnalysisResult, EarningsSummary, Memo, Peer
from analyst.valuation import calculate_dcf, calculate_metrics

from .conftest import make_data

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def build_result(*, dcf=True, earnings=True, peers=True, industry="Software - Application", **metric_overrides):
    data = make_data(industry=industry)
    metrics = calculate_metrics(data)
    for k, v in metric_overrides.items():
        setattr(metrics, k, v)
    peer_list = []
    if peers:
        peer_list = [Peer("PEER1", "Peer One", market_cap=5e9, metrics=calculate_metrics(make_data())),
                     Peer("BAD", "Bad Peer", error="DataUnavailableError: nope")]
    return AnalysisResult(
        ticker="TEST",
        memo=Memo(rating="BUY", confidence="MEDIUM", price_target=130.0, headline="A <b>bold</b> headline",
                  quantitative_case="Numbers.", filing_vs_call="Consistent.", key_risks=["Risk"],
                  catalysts=["Catalyst"], verdict="Buy it.", data_gaps=["none"]),
        metrics=metrics,
        dcf=calculate_dcf(data) if dcf else None,
        earnings=EarningsSummary("TEST", "CALL DATE: x\n\n## 1. Opening Remarks & Results\n- good",
                                 [{"title": "Src", "uri": "https://example.com"}]) if earnings else None,
        peers=peer_list,
        trace=[],
        warnings=["Check the DCF"],
        created_at="2026-01-01T00:00:00+00:00",
    )


def run_app(monkeypatch, result=None, error=None):
    def fake_analyze(ticker, on_event=None, record_prediction=True):
        if error:
            raise error
        return result

    monkeypatch.setattr(pipeline, "analyze", fake_analyze)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.text_input[0].set_value("test")
    at.sidebar.button[0].click().run()
    return at


def test_app_renders_empty_state():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception


def test_full_result_renders_without_errors(monkeypatch):
    at = run_app(monkeypatch, build_result())
    assert not at.exception
    assert len(at.tabs) == 5
    assert any("Check the DCF" in w.value for w in at.warning)


@pytest.mark.parametrize("kwargs", [
    {"dcf": False},                                    # agent never ran a DCF
    {"earnings": False},
    {"peers": False},
    {"industry": "Banks - Diversified"},               # DCF not applicable
    {"pe_ratio": None, "debt_to_equity": None, "gross_margin_pct": None,
     "yoy_revenue_growth_pct": None, "price_to_book": None, "roe_pct": None},   # every metric missing
])
def test_sparse_results_never_crash_the_ui(monkeypatch, kwargs):
    at = run_app(monkeypatch, build_result(**kwargs))
    assert not at.exception, [e.value for e in at.exception]


def test_expected_errors_are_shown_not_raised(monkeypatch):
    at = run_app(monkeypatch, error=ValueError("'??' is not a valid ticker symbol."))
    assert not at.exception
    assert any("not a valid ticker" in e.value for e in at.error)


def test_unexpected_errors_are_contained(monkeypatch):
    at = run_app(monkeypatch, error=RuntimeError("kaboom"))
    assert not at.exception
    assert any("kaboom" in e.value for e in at.error)


def test_llm_text_is_never_rendered_with_raw_html_enabled(monkeypatch):
    # LLM-written fields go through st.markdown WITHOUT unsafe_allow_html, so injected tags stay inert.
    at = run_app(monkeypatch, build_result())
    llm_blocks = [m for m in at.markdown if "headline" in m.value or "Consistent." in m.value]
    assert llm_blocks
    assert all(not m.proto.allow_html for m in llm_blocks)
