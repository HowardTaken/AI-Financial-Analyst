import math

import pytest

from analyst import valuation
from analyst.models import Metrics
from analyst.valuation import calculate_dcf, calculate_metrics, estimate_wacc, project_cash_flows

from .conftest import make_data

# ── Metrics ──────────────────────────────────────────────────────────────────

def test_metrics_basic_ratios(data):
    m = calculate_metrics(data)
    assert m.fiscal_year == "2025-09-30" and m.prior_year == "2024-09-30"
    assert m.gross_margin_pct == pytest.approx(45.0)
    assert m.yoy_revenue_growth_pct == pytest.approx((400 - 380) / 380 * 100, abs=0.01)
    assert m.debt_to_equity == pytest.approx(20 / 50)
    assert m.pe_ratio == pytest.approx(100 / 6.0, abs=0.01)
    assert m.eps_basis == "annual"
    assert m.price_to_book == pytest.approx(100 / (50e9 / 1e9))
    assert m.roe_pct == pytest.approx(90 / 50 * 100)


def test_metrics_prefers_ttm_eps(data):
    data.trailing_eps = 8.0
    m = calculate_metrics(data)
    assert m.eps_basis == "TTM"
    assert m.pe_ratio == pytest.approx(12.5)


def test_zero_debt_is_zero_not_missing():
    # Regression: `if total_debt and equity` used to turn a debt-free company's D/E into None.
    m = calculate_metrics(make_data(debt=0.0))
    assert m.debt_to_equity == 0.0


def test_negative_equity_and_negative_eps_are_not_meaningful():
    d = make_data(equity=-5e9)
    for p in d.income_statement.values():
        p["Diluted EPS"] = -1.0
    m = calculate_metrics(d)
    assert m.debt_to_equity is None and m.price_to_book is None and m.roe_pct is None
    assert m.pe_ratio is None


def test_missing_and_nan_values_become_none(data):
    data.income_statement["2025-09-30"]["Gross Profit"] = float("nan")
    data.income_statement["2025-09-30"]["Total Revenue"] = None
    m = calculate_metrics(data)
    assert m.gross_margin_pct is None and m.yoy_revenue_growth_pct is None


def test_metrics_needs_two_years():
    d = make_data()
    d.income_statement = {"2025-09-30": d.income_statement["2025-09-30"]}
    with pytest.raises(ValueError, match="2 years"):
        calculate_metrics(d)


def test_peer_medians():
    def m(pe, gm):
        return Metrics("X", "2025", "2024", 1.0, pe_ratio=pe, gross_margin_pct=gm)

    out = valuation.peer_medians([m(10, 30), m(20, None), m(40, 50)])
    assert out["pe_ratio"] == 20 and out["gross_margin_pct"] == 40
    assert out["roe_pct"] is None


# ── DCF: hand-calculated reference ───────────────────────────────────────────

def test_project_cash_flows_fades_growth_to_terminal():
    flows = project_cash_flows(100.0, 0.10, 0.02, 5)
    growth = [flows[0] / 100 - 1] + [b / a - 1 for a, b in zip(flows, flows[1:], strict=False)]
    assert growth[0] == pytest.approx(0.10) and growth[-1] == pytest.approx(0.02)
    assert growth == sorted(growth, reverse=True)  # monotonic fade


def test_dcf_matches_hand_calculation():
    # Flat FCF of 100 for all years -> CAGR 0%. Growth fades 0% -> 2% over 5 years.
    d = make_data(fcf=(100.0, 100.0, 100.0), debt=0.0, cash=0.0, shares=1.0, market_cap=None, price=50.0)
    r = calculate_dcf(d, wacc=0.10, terminal_growth=0.02)
    assert r.available

    g = [0.0, 0.005, 0.010, 0.015, 0.020]
    flows, f = [], 100.0
    for gi in g:
        f *= 1 + gi
        flows.append(f)
    pv = sum(x / 1.10 ** (i + 1) for i, x in enumerate(flows))
    tv = flows[-1] * 1.02 / (0.10 - 0.02)
    expected = pv + tv / 1.10 ** 5

    assert r.intrinsic_value == pytest.approx(expected, rel=1e-4)
    assert r.terminal_value_share_pct == pytest.approx(tv / 1.10 ** 5 / expected * 100, abs=0.1)
    assert r.upside_pct == pytest.approx((expected / 50 - 1) * 100, abs=0.01)
    assert r.margin_of_safety_pct == pytest.approx((expected - 50) / expected * 100, abs=0.01)


def test_net_debt_reduces_equity_value():
    base = calculate_dcf(make_data(debt=0.0, cash=0.0), wacc=0.09)
    levered = calculate_dcf(make_data(debt=50e9, cash=10e9), wacc=0.09)
    assert base.equity_value - levered.equity_value == pytest.approx(40e9, rel=1e-6)
    assert levered.net_debt == pytest.approx(40e9)


def test_interest_is_added_back_so_debt_is_not_double_counted():
    without = calculate_dcf(make_data(interest=0.0), wacc=0.09)
    with_interest = calculate_dcf(make_data(interest=5e9), wacc=0.09)
    assert with_interest.base_fcf == pytest.approx(without.base_fcf + 5e9 * (1 - 0.21), rel=1e-6)


def test_sensitivity_grid_is_centered_on_base_case():
    r = calculate_dcf(make_data(), wacc=0.09)
    s = r.sensitivity
    assert s["values"][2][2] == pytest.approx(r.intrinsic_value, abs=0.01)
    # Higher discount rate -> lower value; higher terminal growth -> higher value.
    col = [row[2] for row in s["values"]]
    assert col == sorted(col, reverse=True)
    row = s["values"][2]
    assert row == sorted(row)


def test_growth_is_capped_and_flagged():
    r = calculate_dcf(make_data(fcf=(400e9, 100e9, 25e9)), wacc=0.09, growth_cap=0.10)
    assert r.starting_growth_pct == 10.0
    assert r.raw_growth_pct > 100
    assert any("capped" in w for w in r.warnings)


# ── DCF: not-applicable paths (must return a reason, never raise) ────────────

def test_bank_is_not_applicable():
    r = calculate_dcf(make_data(industry="Banks - Diversified"))
    assert not r.available and "P/B" in r.reason


def test_negative_latest_fcf_is_not_applicable_with_reason():
    r = calculate_dcf(make_data(fcf=(-5e9, 10e9, 8e9)))
    assert not r.available and "negative" in r.reason


def test_missing_fcf_history():
    d = make_data()
    d.cash_flow = {}
    r = calculate_dcf(d)
    assert not r.available and "Fewer than 2" in r.reason


def test_no_price():
    r = calculate_dcf(make_data(price=None))
    assert not r.available and "price" in r.reason


def test_wacc_must_exceed_terminal_growth():
    r = calculate_dcf(make_data(), wacc=0.025, terminal_growth=0.02)
    assert not r.available and "WACC" in r.reason


def test_net_debt_exceeding_value_is_not_applicable():
    r = calculate_dcf(make_data(debt=1e13))
    assert not r.available and "Net debt" in r.reason


def test_non_numeric_statement_values_are_treated_as_missing():
    d = make_data()
    d.cash_flow["2025-09-30"]["Free Cash Flow"] = "not a number"
    d.cash_flow["2024-09-30"]["Free Cash Flow"] = None
    r = calculate_dcf(d)  # only one usable FCF year left
    assert not r.available and "Fewer than 2" in r.reason


def test_unexpected_bugs_are_not_swallowed(monkeypatch):
    # The old code had `except Exception: return NOT_APPLICABLE`, which hid every bug as "bank".
    def broken(*args, **kwargs):
        raise RuntimeError("real bug")

    monkeypatch.setattr(valuation, "project_cash_flows", broken)
    with pytest.raises(RuntimeError, match="real bug"):
        calculate_dcf(make_data())


# ── WACC ─────────────────────────────────────────────────────────────────────

def test_wacc_uses_capm_and_weights():
    d = make_data(beta=1.2, debt=0.0, market_cap=100e9)
    wacc, ke, _ = estimate_wacc(d, risk_free=0.04)
    assert ke == pytest.approx(0.04 + 1.2 * 0.05)
    assert wacc == pytest.approx(ke)  # no debt -> WACC == cost of equity


def test_wacc_is_clamped_with_note():
    wacc, _, notes = estimate_wacc(make_data(beta=3.0, debt=0.0), risk_free=0.05)
    assert wacc == valuation.WACC_BOUNDS[1]
    assert any("clamped" in n for n in notes)
    assert math.isclose(valuation.WACC_BOUNDS[0], 0.06)
