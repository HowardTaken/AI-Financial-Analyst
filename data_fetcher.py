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

    print(f"[data_fetcher] Saved {ticker.upper()} data to {out_path}")
    return data


if __name__ == "__main__":
    result = fetch_financials("AAPL")

    print(f"Ticker:        {result['ticker']}")
    print(f"Current Price: ${result['current_price']}")
    print(f"Income Stmt columns:  {list(result['income_statement'].keys())}")
    print(f"Balance Sheet columns:{list(result['balance_sheet'].keys())}")
    print(f"Cash Flow columns:    {list(result['cash_flow'].keys())}")
