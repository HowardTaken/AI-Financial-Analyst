import os
import sys
from data_fetcher import fetch_financials
from calculator import calculate_metrics
from sec_scraper import scrape_sec_filing
from agent import run_analysis


DIVIDER = "=" * 60
THIN    = "-" * 60


def print_header(title: str):
    print(f"\n{THIN}")
    print(f"  {title}")
    print(THIN)


def print_metrics(metrics: dict):
    print(f"  Ticker:              {metrics['ticker']}")
    print(f"  Fiscal Year:         {metrics['fiscal_year']}")
    print(f"  Current Price:       ${metrics['current_price']:.2f}")
    print(f"  P/E Ratio:           {metrics['pe_ratio']}")
    print(f"  Debt-to-Equity:      {metrics['debt_to_equity']}")
    print(f"  Gross Margin:        {metrics['gross_margin_pct']}%")
    print(f"  YoY Revenue Growth:  {metrics['yoy_revenue_growth_pct']}%")


def render_memo(memo: str):
    """Print the memo with simple terminal formatting."""
    for line in memo.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            print(f"\n  \033[1m{stripped[3:].upper()}\033[0m")
        elif stripped.startswith("# "):
            print(f"\n  \033[1;4m{stripped[2:].upper()}\033[0m")
        elif stripped.startswith("**") and stripped.endswith("**"):
            print(f"  \033[1m{stripped.strip('*')}\033[0m")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            print(f"    • {stripped[2:]}")
        elif stripped == "":
            print()
        else:
            words = stripped.split()
            current = "  "
            for word in words:
                if len(current) + len(word) + 1 > 82:
                    print(current)
                    current = "  " + word
                else:
                    current += (" " if current.strip() else "") + word
            if current.strip():
                print(current)


def analyse(ticker: str):
    print_header(f"Step 1 of 4 -- Fetching Financial Data: {ticker}")
    fetch_financials(ticker)

    print_header("Step 2 of 4 -- Calculating Fundamental Metrics")
    metrics = calculate_metrics(ticker)
    print_metrics(metrics)

    print_header("Step 3 of 4 -- Scraping SEC 10-K (Item 1A Risk Factors)")
    scrape_sec_filing(ticker, section="item1a")

    print_header("Step 4 of 4 -- Generating Investment Memo via Gemini")
    memo = run_analysis(ticker)

    print(f"\n\n{DIVIDER}")
    print(f"  INVESTMENT MEMO: {ticker}")
    print(DIVIDER)
    render_memo(memo)
    print(f"\n{DIVIDER}")

    out_path = os.path.join("data", f"{ticker}_memo.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(memo)
    print(f"\n  Memo saved to {out_path}")


def main():
    print(f"\n{'#' * 60}")
    print("#        AI Market Analyst - Investment Memo           #")
    print(f"{'#' * 60}")
    print("  Type a stock ticker to analyse, or 'exit' to quit.\n")

    while True:
        try:
            ticker = input("  Ticker > ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            sys.exit(0)

        if not ticker:
            continue

        if ticker in ("EXIT", "QUIT"):
            print("\n  Goodbye.\n")
            sys.exit(0)

        print(f"\n{'#' * 60}")
        print(f"#  Analysing: {ticker:<46} #")
        print(f"{'#' * 60}")

        try:
            analyse(ticker)
        except Exception as e:
            print(f"\n  [ERROR] {e}")
            print("  Check the ticker symbol and try again.")

        # Visual separator between searches
        print(f"\n\n{'~' * 60}")
        print("  Ready for next ticker. Type 'exit' to quit.")
        print(f"{'~' * 60}\n")


if __name__ == "__main__":
    main()
