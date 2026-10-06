from datetime import UTC, date, datetime

import pandas as pd
import pytest

from analyst import evaluate
from analyst.backtest import Observation, price_on_or_after, spearman, summarize, truncate_as_of

from .conftest import make_data


def test_truncate_as_of_drops_statements_not_yet_public():
    # Periods: 2025-09-30, 2024-09-30, 2023-09-30, 2022-09-30. With a 90-day lag, at 2025-01-15 the
    # FY2024 report (2024-09-30 + 90d = 2024-12-29) is public but FY2025 is not.
    d = truncate_as_of(make_data(), date(2025, 1, 15), price=42.0)
    assert sorted(d.income_statement) == ["2022-09-30", "2023-09-30", "2024-09-30"]
    assert sorted(d.balance_sheet) == sorted(d.income_statement)
    assert sorted(d.cash_flow) == ["2023-09-30", "2024-09-30"]  # fixture has 3 FCF years; FY2025 dropped
    assert d.current_price == 42.0


def test_truncate_as_of_respects_reporting_lag():
    # Day after period end: statement is NOT yet public.
    d = truncate_as_of(make_data(), date(2024, 10, 1), price=1.0)
    assert "2024-09-30" not in d.income_statement
    d = truncate_as_of(make_data(), date(2025, 1, 1), price=1.0)
    assert "2024-09-30" in d.income_statement


def test_truncate_as_of_removes_current_market_inputs():
    d = truncate_as_of(make_data(beta=2.0, market_cap=1e12), date(2025, 1, 15), price=1.0)
    assert d.beta is None and d.market_cap is None and d.trailing_eps is None


def test_truncate_does_not_mutate_original():
    original = make_data()
    truncate_as_of(original, date(2023, 1, 1), price=1.0)
    assert len(original.income_statement) == 4


def test_price_on_or_after_skips_weekends_and_handles_end_of_series():
    s = pd.Series([10.0, 11.0, 12.0], index=pd.to_datetime(["2025-01-03", "2025-01-06", "2025-01-07"]))
    assert price_on_or_after(s, date(2025, 1, 4)) == 11.0  # Saturday -> next trading day
    assert price_on_or_after(s, date(2025, 2, 1)) is None


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None   # no variance
    assert spearman([1, 2], [1, 2]) is None         # too few points


def obs(upside, fwd, bench=10.0):
    return Observation("T", date(2025, 1, 1), upside, fwd, bench)


def test_summarize_perfect_signal():
    rows = [obs(u, 10 + u) for u in (-30, -10, 0, 10, 30, 50)]
    s = summarize(rows)
    assert s["n"] == 6 and s["information_coefficient"] == pytest.approx(1.0)
    assert s["spread_top_minus_bottom_pct"] > 0
    assert s["n_positive_upside"] == 3 and s["hit_rate_positive_upside_beats_spy"] == 1.0


def test_summarize_empty():
    assert summarize([]) == {"n": 0}


def test_evaluate_scores_directional_ratings_only(monkeypatch):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    returns = {"AAA": 30.0, "BBB": 30.0, "CCC": -5.0, "SPY": 10.0}
    monkeypatch.setattr(evaluate, "_total_return", lambda t, a, b: returns[t])
    preds = [
        {"ticker": "AAA", "rating": "BUY", "confidence": "HIGH", "timestamp": "2026-01-01T00:00:00+00:00"},
        {"ticker": "BBB", "rating": "SELL", "confidence": "LOW", "timestamp": "2026-01-01T00:00:00+00:00"},
        {"ticker": "CCC", "rating": "HOLD", "confidence": "LOW", "timestamp": "2026-01-01T00:00:00+00:00"},
        {"ticker": "AAA", "rating": "BUY", "confidence": "LOW", "timestamp": "2026-05-25T00:00:00+00:00"},  # too new
        {"ticker": "AAA", "rating": "BUY", "timestamp": "garbage"},
    ]
    rows = evaluate.score(preds, min_days=30, now=now)
    assert [r["ticker"] for r in rows] == ["AAA", "BBB", "CCC"]
    text = evaluate.report(rows)
    assert "1/2 (50%)" in text  # BUY beat SPY (right), SELL on a 30% winner (wrong); HOLD unscored


def test_evaluate_report_when_nothing_is_old_enough():
    assert "No ratings are old enough" in evaluate.report([])
