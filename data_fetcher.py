import json
import os
import yfinance as yf


def fetch_financials(ticker: str) -> dict:
    """
    Fetches income statement, balance sheet, cash flow statement (last 4 years),
    and current stock price for the given ticker. Saves results to data/<ticker>.json.
    Returns the data dict.
    """
    stock = yf.Ticker(ticker)

    def df_to_dict(df):
        if df is None or df.empty:
            return {}
        # Convert column headers (Timestamps) to strings, values to floats
        df.columns = [str(c)[:10] for c in df.columns]
        return {
            col: {str(idx): (float(val) if val == val else None)
                  for idx, val in df[col].items()}
            for col in df.columns
        }

    income_stmt = df_to_dict(stock.financials)
    balance_sheet = df_to_dict(stock.balance_sheet)
    cash_flow = df_to_dict(stock.cashflow)

    price = None
    info = stock.info
    if info:
        price = info.get("currentPrice") or info.get("regularMarketPrice")

    data = {
        "ticker": ticker.upper(),
        "current_price": price,
        "income_statement": income_stmt,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
    }

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", f"{ticker.upper()}.json")
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)

    return data


def get_competitors(ticker: str) -> dict:
    """
    Identifies the sector/industry of a ticker and returns the top 2 other
    companies in the same industry ranked by market weight (market-cap proxy).

    Returns:
        {
          "sector":      str,
          "industry":    str,
          "competitors": [
              {"ticker": str, "name": str, "market_weight": float},
              ...
          ]
        }
    """
    stock = yf.Ticker(ticker)
    info  = stock.info

    industry_key = info.get("industryKey")
    sector       = info.get("sector",   "Unknown")
    industry     = info.get("industry", "Unknown")

    if not industry_key:
        raise ValueError(
            f"Could not determine industry for {ticker.upper()}. "
            "yfinance returned no 'industryKey'."
        )

    top_df = yf.Industry(industry_key).top_companies  # indexed by symbol

    competitors = []
    for symbol, row in top_df.iterrows():
        if str(symbol).upper() == ticker.upper():
            continue
        competitors.append({
            "ticker":        str(symbol),
            "name":          row.get("name", str(symbol)),
            "market_weight": float(row.get("market weight", 0) or 0),
        })
        if len(competitors) == 2:
            break

    return {
        "sector":      sector,
        "industry":    industry,
        "competitors": competitors,
    }


if __name__ == "__main__":
    result = fetch_financials("AAPL")

    print(f"Ticker:        {result['ticker']}")
    print(f"Current Price: ${result['current_price']}")
    print(f"Income Stmt columns:  {list(result['income_statement'].keys())}")
    print(f"Balance Sheet columns:{list(result['balance_sheet'].keys())}")
    print(f"Cash Flow columns:    {list(result['cash_flow'].keys())}")
