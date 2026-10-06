"""
Pure valuation maths: no network, no disk, fully unit-testable.

DCF design (see README "Valuation methodology"):
  * Cash flows are UNLEVERED: reported FCF plus after-tax interest, so that discounting at WACC
    and then subtracting net debt does not double-count debt.
  * WACC comes from CAPM (risk-free + beta * ERP), blended with an after-tax cost of debt at
    market-value weights, and clamped to a sane range. It can be overridden per call.
  * Growth starts at the capped historical FCF CAGR and fades linearly to the terminal rate,
    instead of compounding a high rate for 5 years and then falling off a cliff.
  * Enterprise value -> equity value via net debt; per-share value via diluted share count.
  * Terminal-value share and a WACC x terminal-growth sensitivity grid are always reported.
"""

from __future__ import annotations

import math
import statistics

from .models import DCFResult, FinancialData, Metrics, Statement

DEFAULT_RISK_FREE = 0.0425
EQUITY_RISK_PREMIUM = 0.05
CREDIT_SPREAD = 0.015
DEFAULT_TAX_RATE = 0.21
WACC_BOUNDS = (0.06, 0.14)
BETA_BOUNDS = (0.6, 2.0)
MIN_WACC_SPREAD = 0.01  # WACC must exceed terminal growth by at least 1 point
FINANCIAL_INDUSTRY_MARKERS = ("Banks", "Insurance", "Mortgage Finance")


class DCFNotApplicable(ValueError):
    """Raised internally when a DCF cannot be meaningfully computed; carries a human reason."""


# ── Statement helpers ────────────────────────────────────────────────────────

def get_field(section: Statement, period: str, name: str) -> float | None:
    """Numeric value for a line item, or None if missing / NaN / inf."""
    val = section.get(period, {}).get(name)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def first_field(section: Statement, period: str, *names: str) -> float | None:
    """First non-missing value among alternative line-item names (Yahoo labels vary by company)."""
    for name in names:
        val = get_field(section, period, name)
        if val is not None:
            return val
    return None


def periods_desc(section: Statement) -> list[str]:
    return sorted(section.keys(), reverse=True)


# ── Fundamental metrics ──────────────────────────────────────────────────────

def calculate_metrics(data: FinancialData) -> Metrics:
    inc, bal = data.income_statement, data.balance_sheet
    years = periods_desc(inc)
    if len(years) < 2:
        raise ValueError("Need at least 2 years of income-statement data for YoY growth.")
    current, prior = years[0], years[1]
    bal_period = periods_desc(bal)[0] if bal else current
    price = data.current_price

    revenue_cur = get_field(inc, current, "Total Revenue")
    revenue_prior = get_field(inc, prior, "Total Revenue")
    gross_profit = get_field(inc, current, "Gross Profit")
    net_income = first_field(inc, current, "Net Income", "Net Income Common Stockholders")
    annual_eps = get_field(inc, current, "Diluted EPS")

    # Prefer trailing-twelve-month EPS so a live price isn't divided by stale annual EPS.
    if data.trailing_eps:
        eps, basis = data.trailing_eps, "TTM"
    else:
        eps, basis = annual_eps, "annual"
    pe = round(price / eps, 2) if price and eps and eps > 0 else None

    total_debt = get_field(bal, bal_period, "Total Debt")
    equity = get_field(bal, bal_period, "Stockholders Equity")
    # A debt-free company has D/E of 0, not "missing"; non-positive equity makes D/E meaningless.
    debt_to_equity = (
        round(total_debt / equity, 4) if total_debt is not None and equity and equity > 0 else None
    )

    gross_margin = (
        round(gross_profit / revenue_cur * 100, 2)
        if gross_profit is not None and revenue_cur and revenue_cur > 0 else None
    )
    yoy = (
        round((revenue_cur - revenue_prior) / revenue_prior * 100, 2)
        if revenue_cur is not None and revenue_prior and revenue_prior > 0 else None
    )

    shares = first_field(bal, bal_period, "Ordinary Shares Number") or data.shares_outstanding
    price_to_book = (
        round(price / (equity / shares), 2)
        if price and equity and equity > 0 and shares and shares > 0 else None
    )
    roe = round(net_income / equity * 100, 2) if net_income is not None and equity and equity > 0 else None

    return Metrics(
        ticker=data.ticker.upper(),
        fiscal_year=current,
        prior_year=prior,
        current_price=price,
        pe_ratio=pe,
        eps_basis=basis,
        debt_to_equity=debt_to_equity,
        gross_margin_pct=gross_margin,
        yoy_revenue_growth_pct=yoy,
        price_to_book=price_to_book,
        roe_pct=roe,
        diluted_eps=eps,
        total_debt=total_debt,
        stockholders_equity=equity,
        gross_profit=gross_profit,
        net_income=net_income,
        revenue_current=revenue_cur,
        revenue_prior=revenue_prior,
    )


def peer_medians(metrics: list[Metrics]) -> dict[str, float | None]:
    """Median of each comparable metric across peers (None when no peer has a value)."""
    keys = ("pe_ratio", "gross_margin_pct", "yoy_revenue_growth_pct", "debt_to_equity",
            "price_to_book", "roe_pct")
    out: dict[str, float | None] = {}
    for key in keys:
        vals = [getattr(m, key) for m in metrics if getattr(m, key) is not None]
        out[key] = round(statistics.median(vals), 2) if vals else None
    return out


# ── DCF ──────────────────────────────────────────────────────────────────────

def estimate_wacc(
    data: FinancialData,
    risk_free: float,
    *,
    erp: float = EQUITY_RISK_PREMIUM,
    credit_spread: float = CREDIT_SPREAD,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> tuple[float, float, list[str]]:
    """CAPM-based WACC. Returns (wacc, cost_of_equity, notes)."""
    notes: list[str] = []
    beta = data.beta if data.beta and data.beta > 0 else 1.0
    if not data.beta:
        notes.append("Beta unavailable; assumed 1.0.")
    clamped_beta = min(max(beta, BETA_BOUNDS[0]), BETA_BOUNDS[1])
    if clamped_beta != beta:
        notes.append(f"Beta {beta:.2f} clamped to {clamped_beta:.2f}.")
    cost_equity = risk_free + clamped_beta * erp
    cost_debt_after_tax = (risk_free + credit_spread) * (1 - tax_rate)

    bal = data.balance_sheet
    debt = get_field(bal, periods_desc(bal)[0], "Total Debt") if bal else None
    debt = debt or 0.0
    equity_mv = data.market_cap
    if not equity_mv and data.current_price and data.shares_outstanding:
        equity_mv = data.current_price * data.shares_outstanding
    if equity_mv:
        weight_equity = equity_mv / (equity_mv + debt)
    else:
        weight_equity = 1.0
        notes.append("Market cap unavailable; WACC set to cost of equity.")

    wacc = weight_equity * cost_equity + (1 - weight_equity) * cost_debt_after_tax
    bounded = min(max(wacc, WACC_BOUNDS[0]), WACC_BOUNDS[1])
    if bounded != wacc:
        notes.append(f"WACC {wacc:.1%} clamped to {bounded:.1%}.")
    return bounded, cost_equity, notes


def project_cash_flows(base_fcf: float, start_growth: float, terminal_growth: float, years: int) -> list[float]:
    """Project FCF with growth fading linearly from `start_growth` (year 1) to `terminal_growth` (final year)."""
    flows, fcf = [], base_fcf
    for i in range(years):
        fade = i / (years - 1) if years > 1 else 0.0
        fcf *= 1 + start_growth + (terminal_growth - start_growth) * fade
        flows.append(fcf)
    return flows


def discount(flows: list[float], wacc: float, terminal_growth: float) -> tuple[list[float], float, float]:
    """Return (PV of each flow, terminal value, PV of terminal value)."""
    if wacc - terminal_growth < MIN_WACC_SPREAD:
        raise DCFNotApplicable(
            f"WACC ({wacc:.1%}) must exceed terminal growth ({terminal_growth:.1%}) by at least 1 point."
        )
    pv = [f / (1 + wacc) ** (i + 1) for i, f in enumerate(flows)]
    tv = flows[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    return pv, tv, tv / (1 + wacc) ** len(flows)


def _per_share(base_fcf, start_growth, wacc, terminal_growth, years, net_debt, shares) -> float | None:
    try:
        flows = project_cash_flows(base_fcf, start_growth, terminal_growth, years)
        pv, _, pv_tv = discount(flows, wacc, terminal_growth)
    except DCFNotApplicable:
        return None
    equity = sum(pv) + pv_tv - net_debt
    return round(equity / shares, 2) if equity > 0 else None


def _estimate_growth(values_newest_first: list[float], terminal_growth: float) -> tuple[float, str | None]:
    """Historical FCF growth: CAGR if all points positive, else average of positive-base YoY changes."""
    ordered = list(reversed(values_newest_first))  # oldest -> newest
    if all(v > 0 for v in ordered):
        return (ordered[-1] / ordered[0]) ** (1 / (len(ordered) - 1)) - 1, None
    rates = [(b - a) / a for a, b in zip(ordered, ordered[1:], strict=False) if a > 0]
    if rates:
        return sum(rates) / len(rates), "FCF history includes negative years; growth averaged over positive-base years only."
    return terminal_growth, "FCF history has no positive base year; growth set to the terminal rate."


def calculate_dcf(
    data: FinancialData,
    *,
    wacc: float | None = None,
    terminal_growth: float = 0.02,
    growth_cap: float = 0.10,
    growth_floor: float = -0.10,
    projection_years: int = 5,
    deduct_sbc: bool = False,
) -> DCFResult:
    """
    Discounted cash-flow valuation. Returns DCFResult(available=False, reason=...) when a DCF is not
    meaningful (banks/insurers, negative or missing FCF, bad inputs). Unexpected errors are NOT
    swallowed: they propagate so bugs surface instead of masquerading as "not applicable".
    """
    try:
        return _dcf(data, wacc, terminal_growth, growth_cap, growth_floor, projection_years, deduct_sbc)
    except DCFNotApplicable as exc:
        return DCFResult.unavailable(str(exc), data.ticker.upper())


def _dcf(data, wacc_override, terminal_growth, growth_cap, growth_floor, years, deduct_sbc) -> DCFResult:
    price = data.current_price
    if not price or price <= 0:
        raise DCFNotApplicable("No current share price available.")
    if years < 2:
        raise DCFNotApplicable("Projection horizon must be at least 2 years.")
    if any(marker in (data.industry or "") for marker in FINANCIAL_INDUSTRY_MARKERS):
        raise DCFNotApplicable(
            f"A free-cash-flow DCF is not meaningful for {data.industry}: banks and insurers fund "
            "themselves with deposits/float, so FCF is not a clean measure. Use P/B and ROE instead."
        )

    cf, inc, bal = data.cash_flow, data.income_statement, data.balance_sheet
    warnings: list[str] = []

    # 1. FCF history (newest first, up to 4 years)
    series = [(p, get_field(cf, p, "Free Cash Flow")) for p in periods_desc(cf)[:4]]
    series = [(p, v) for p, v in series if v is not None]
    if len(series) < 2:
        raise DCFNotApplicable("Fewer than 2 years of free-cash-flow data are available.")
    newest_period, newest_fcf = series[0]
    if newest_fcf <= 0:
        raise DCFNotApplicable(
            f"Latest free cash flow is negative (${newest_fcf / 1e9:,.2f}B); a cash-flow DCF is not meaningful."
        )

    # 2. Unlevered base cash flow
    inc_period = newest_period if newest_period in inc else (periods_desc(inc)[0] if inc else newest_period)
    tax = first_field(inc, inc_period, "Tax Rate For Calcs")
    tax = tax if tax is not None and 0 < tax < 0.4 else DEFAULT_TAX_RATE
    interest = abs(first_field(inc, inc_period, "Interest Expense", "Interest Expense Non Operating") or 0.0)
    base_fcf = newest_fcf + interest * (1 - tax)
    sbc = first_field(cf, newest_period, "Stock Based Compensation") or 0.0
    if deduct_sbc:
        base_fcf -= sbc
    elif sbc and sbc / newest_fcf > 0.15:
        warnings.append(
            f"Stock-based compensation is {sbc / newest_fcf:.0%} of FCF and is not deducted; "
            "value may be overstated."
        )
    if base_fcf <= 0:
        raise DCFNotApplicable("Base free cash flow is not positive after adjustments.")

    # 3. Growth: historical CAGR, capped, fading to terminal
    raw_growth, growth_note = _estimate_growth([v for _, v in series], terminal_growth)
    if growth_note:
        warnings.append(growth_note)
    start_growth = min(max(raw_growth, growth_floor), growth_cap)
    if start_growth != raw_growth:
        warnings.append(f"Historical FCF growth {raw_growth:.1%} capped to {start_growth:.1%}.")

    # 4. Discount rate
    risk_free = data.risk_free_rate if data.risk_free_rate else DEFAULT_RISK_FREE
    est_wacc, cost_equity, wacc_notes = estimate_wacc(data, risk_free, tax_rate=tax)
    used_wacc = wacc_override if wacc_override is not None else est_wacc
    warnings.extend(wacc_notes if wacc_override is None else ["WACC overridden by caller."])

    # 5. Project and discount
    flows = project_cash_flows(base_fcf, start_growth, terminal_growth, years)
    pv_flows, tv, pv_tv = discount(flows, used_wacc, terminal_growth)
    enterprise_value = sum(pv_flows) + pv_tv
    tv_share = pv_tv / enterprise_value * 100
    if tv_share > 75:
        warnings.append(f"Terminal value is {tv_share:.0f}% of enterprise value; result is assumption-sensitive.")

    # 6. EV -> equity -> per share
    bal_period = periods_desc(bal)[0] if bal else None
    debt = get_field(bal, bal_period, "Total Debt") if bal_period else None
    cash = (
        first_field(bal, bal_period, "Cash Cash Equivalents And Short Term Investments",
                    "Cash And Cash Equivalents") if bal_period else None
    )
    net_debt = (debt or 0.0) - (cash or 0.0)
    equity_value = enterprise_value - net_debt
    if equity_value <= 0:
        raise DCFNotApplicable("Net debt exceeds the present value of cash flows; equity value is not positive.")
    shares = (first_field(bal, bal_period, "Ordinary Shares Number") if bal_period else None) or data.shares_outstanding
    if not shares or shares <= 0:
        raise DCFNotApplicable("Share count is unavailable.")
    intrinsic = equity_value / shares

    # 7. Sensitivity grid (rows: WACC, cols: terminal growth)
    waccs = [used_wacc + d for d in (-0.02, -0.01, 0.0, 0.01, 0.02)]
    growths = [terminal_growth + d for d in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    grid = [[_per_share(base_fcf, start_growth, w, g, years, net_debt, shares) for g in growths] for w in waccs]

    return DCFResult(
        available=True,
        ticker=data.ticker.upper(),
        wacc_pct=round(used_wacc * 100, 2),
        cost_of_equity_pct=round(cost_equity * 100, 2),
        terminal_growth_pct=round(terminal_growth * 100, 2),
        raw_growth_pct=round(raw_growth * 100, 2),
        starting_growth_pct=round(start_growth * 100, 2),
        fcf_history={p: round(v) for p, v in series},
        base_fcf=round(base_fcf),
        projected_fcf=[round(v) for v in flows],
        pv_projected_fcf=[round(v) for v in pv_flows],
        terminal_value=round(tv),
        pv_terminal_value=round(pv_tv),
        terminal_value_share_pct=round(tv_share, 1),
        enterprise_value=round(enterprise_value),
        net_debt=round(net_debt),
        equity_value=round(equity_value),
        shares_outstanding=round(shares),
        intrinsic_value=round(intrinsic, 2),
        current_price=price,
        upside_pct=round((intrinsic / price - 1) * 100, 2),
        margin_of_safety_pct=round((intrinsic - price) / intrinsic * 100, 2),
        sensitivity={
            "wacc_pct": [round(w * 100, 2) for w in waccs],
            "terminal_growth_pct": [round(g * 100, 2) for g in growths],
            "values": grid,
        },
        warnings=warnings,
    )
