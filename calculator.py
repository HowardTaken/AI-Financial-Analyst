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


if __name__ == "__main__":
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
