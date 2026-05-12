import json
import os


def load_ticker_data(ticker: str) -> dict:
    path = os.path.join("data", f"{ticker.upper()}.json")
    with open(path) as f:
        return json.load(f)


def get_field(section: dict, year: str, field: str):
    """Return a numeric value from a section/year, or None if missing."""
    val = section.get(year, {}).get(field)
    return float(val) if val is not None else None


def calculate_metrics(ticker: str) -> dict:
    data = load_ticker_data(ticker)

    income = data["income_statement"]
    balance = data["balance_sheet"]
    price = data["current_price"]

    years = sorted(income.keys(), reverse=True)  # most recent first
    if len(years) < 2:
        raise ValueError("Need at least 2 years of data for YoY growth.")

    current_year = years[0]
    prior_year = years[1]

    # --- P/E Ratio ---
    diluted_eps = get_field(income, current_year, "Diluted EPS")
    pe_ratio = round(price / diluted_eps, 2) if price and diluted_eps else None

    # --- Debt-to-Equity ---
    total_debt = get_field(balance, current_year, "Total Debt")
    equity = get_field(balance, current_year, "Stockholders Equity")
    debt_to_equity = round(total_debt / equity, 4) if total_debt and equity else None

    # --- Gross Margin ---
    gross_profit = get_field(income, current_year, "Gross Profit")
    total_revenue = get_field(income, current_year, "Total Revenue")
    gross_margin = round((gross_profit / total_revenue) * 100, 2) if gross_profit and total_revenue else None

    # --- YoY Revenue Growth ---
    revenue_current = get_field(income, current_year, "Total Revenue")
    revenue_prior = get_field(income, prior_year, "Total Revenue")
    yoy_revenue_growth = (
        round(((revenue_current - revenue_prior) / revenue_prior) * 100, 2)
        if revenue_current and revenue_prior else None
    )

    metrics = {
        "ticker": ticker.upper(),
        "fiscal_year": current_year,
        "current_price": price,
        "pe_ratio": pe_ratio,
        "debt_to_equity": debt_to_equity,
        "gross_margin_pct": gross_margin,
        "yoy_revenue_growth_pct": yoy_revenue_growth,
        "_details": {
            "diluted_eps": diluted_eps,
            "total_debt": total_debt,
            "stockholders_equity": equity,
            "gross_profit": gross_profit,
            "total_revenue_current": revenue_current,
            "total_revenue_prior": revenue_prior,
            "prior_year": prior_year,
        }
    }

    return metrics


def calculate_dcf(ticker: str,
                  wacc: float = 0.10,
                  terminal_growth: float = 0.02,
                  growth_cap: float = 0.10,
                  projection_years: int = 5) -> dict:
    """
    Discounted Cash Flow model using the Perpetual Growth (Gordon Growth) method.

    Steps:
      1. Pull the last 3 years of Free Cash Flow from saved JSON.
      2. Calculate the average YoY FCF growth rate, capped at growth_cap.
      3. Project FCF for projection_years using that capped rate.
      4. Compute Terminal Value = FCF_final * (1 + g) / (WACC - g).
      5. Discount all future cash flows + TV back to present at WACC.
      6. Divide by shares outstanding → Intrinsic Value per share.
      7. Margin of Safety = (Intrinsic Value - Price) / Intrinsic Value.

    Returns a dict with all intermediate workings for full transparency.
    """
    data   = load_ticker_data(ticker)
    cf     = data["cash_flow"]
    bal    = data["balance_sheet"]
    price  = data["current_price"]

    # ── 1. Collect last 3 years of FCF (most-recent first) ───────────────────
    years = sorted(cf.keys(), reverse=True)
    fcf_series = []
    for yr in years[:3]:
        val = get_field(cf, yr, "Free Cash Flow")
        if val is not None:
            fcf_series.append((yr, val))

    if len(fcf_series) < 2:
        raise ValueError("Not enough Free Cash Flow data (need at least 2 years).")

    # ── 2. Average YoY growth rate ────────────────────────────────────────────
    growth_rates = []
    for i in range(len(fcf_series) - 1):
        newer_val = fcf_series[i][1]
        older_val = fcf_series[i + 1][1]
        if older_val and older_val > 0:
            growth_rates.append((newer_val - older_val) / older_val)

    if not growth_rates:
        raise ValueError("Cannot calculate FCF growth rate (negative or zero base year).")

    avg_growth   = sum(growth_rates) / len(growth_rates)
    capped_growth = max(-0.50, min(avg_growth, growth_cap))  # floor at -50%, cap at growth_cap

    # ── 3. Project FCF for next N years ──────────────────────────────────────
    base_fcf = fcf_series[0][1]
    projected_fcf = []
    for yr in range(1, projection_years + 1):
        projected_fcf.append(base_fcf * (1 + capped_growth) ** yr)

    # ── 4. Terminal Value (Perpetual Growth Method) ───────────────────────────
    terminal_value = projected_fcf[-1] * (1 + terminal_growth) / (wacc - terminal_growth)

    # ── 5. Discount everything back to present ────────────────────────────────
    pv_fcfs = [fcf / (1 + wacc) ** (i + 1) for i, fcf in enumerate(projected_fcf)]
    pv_terminal = terminal_value / (1 + wacc) ** projection_years
    total_pv = sum(pv_fcfs) + pv_terminal

    # ── 6. Intrinsic Value per share ──────────────────────────────────────────
    bal_year = sorted(bal.keys(), reverse=True)[0]
    shares = get_field(bal, bal_year, "Ordinary Shares Number")
    if not shares or shares <= 0:
        raise ValueError("Shares outstanding not available.")

    intrinsic_value = total_pv / shares

    # ── 7. Margin of Safety ───────────────────────────────────────────────────
    margin_of_safety = round(((intrinsic_value - price) / intrinsic_value) * 100, 2) \
                       if intrinsic_value > 0 else None

    return {
        "ticker":             ticker.upper(),
        "wacc_pct":           wacc * 100,
        "terminal_growth_pct": terminal_growth * 100,
        "fcf_history":        {yr: round(val) for yr, val in fcf_series},
        "avg_growth_rate_pct":  round(avg_growth * 100, 2),
        "capped_growth_rate_pct": round(capped_growth * 100, 2),
        "projected_fcf":      [round(v) for v in projected_fcf],
        "pv_projected_fcf":   [round(v) for v in pv_fcfs],
        "terminal_value":     round(terminal_value),
        "pv_terminal_value":  round(pv_terminal),
        "total_present_value": round(total_pv),
        "shares_outstanding": round(shares),
        "intrinsic_value":    round(intrinsic_value, 2),
        "current_price":      price,
        "margin_of_safety_pct": margin_of_safety,
    }


if __name__ == "__main__":
    import pprint
    print("\n--- DCF Model ---")
    dcf = calculate_dcf("AAPL")
    pprint.pprint(dcf)
    print()

    metrics = calculate_metrics("AAPL")

    print(f"\n{'='*40}")
    print(f"  Fundamental Metrics: {metrics['ticker']}")
    print(f"  Fiscal Year: {metrics['fiscal_year']}")
    print(f"{'='*40}")
    print(f"  Current Price:        ${metrics['current_price']:.2f}")
    print(f"  P/E Ratio:            {metrics['pe_ratio']}")
    print(f"  Debt-to-Equity:       {metrics['debt_to_equity']}")
    print(f"  Gross Margin:         {metrics['gross_margin_pct']}%")
    print(f"  YoY Revenue Growth:   {metrics['yoy_revenue_growth_pct']}%")
    print(f"{'='*40}")
    print(f"\nSupporting figures:")
    d = metrics["_details"]
    print(f"  Diluted EPS:          ${d['diluted_eps']:.2f}")
    print(f"  Total Debt:           ${d['total_debt']:,.0f}")
    print(f"  Stockholders Equity:  ${d['stockholders_equity']:,.0f}")
    print(f"  Gross Profit:         ${d['gross_profit']:,.0f}")
    print(f"  Revenue ({metrics['fiscal_year'][:4]}):      ${d['total_revenue_current']:,.0f}")
    print(f"  Revenue ({d['prior_year'][:4]}):      ${d['total_revenue_prior']:,.0f}")
