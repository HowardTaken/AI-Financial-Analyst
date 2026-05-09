import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

from calculator import calculate_metrics
from sec_scraper import scrape_sec_filing

load_dotenv()

SYSTEM_INSTRUCTION = (
    "You are a Wall Street quantitative analyst. "
    "Review the provided financial metrics and SEC risk factors. "
    "Output a definitive Buy, Hold, or Sell rating with a concise, brutal 300-word justification."
)

MODEL = "gemini-2.5-flash"


def build_prompt(ticker: str, metrics: dict, risk_text: str) -> str:
    d = metrics["_details"]
    prompt = f"""
STOCK: {metrics['ticker']}
FISCAL YEAR: {metrics['fiscal_year']}

--- QUANTITATIVE METRICS ---
Current Price:        ${metrics['current_price']:.2f}
P/E Ratio:            {metrics['pe_ratio']}
Debt-to-Equity:       {metrics['debt_to_equity']}
Gross Margin:         {metrics['gross_margin_pct']}%
YoY Revenue Growth:   {metrics['yoy_revenue_growth_pct']}%

Supporting Figures:
  Diluted EPS:          ${d['diluted_eps']:.2f}
  Total Debt:           ${d['total_debt']:,.0f}
  Stockholders Equity:  ${d['stockholders_equity']:,.0f}
  Revenue ({metrics['fiscal_year'][:4]}):      ${d['total_revenue_current']:,.0f}
  Revenue ({d['prior_year'][:4]}):      ${d['total_revenue_prior']:,.0f}

--- SEC 10-K RISK FACTORS (Item 1A) ---
{risk_text[:6000]}
"""
    return prompt.strip()


def run_analysis(ticker: str) -> str:
    """
    Full pipeline: fetch metrics + SEC text → call Gemini → return memo text.
    """
    print(f"[agent] Calculating metrics for {ticker.upper()}...")
    metrics = calculate_metrics(ticker)

    print(f"[agent] Loading SEC risk factors for {ticker.upper()}...")
    risk_text_path = os.path.join("data", f"{ticker.upper()}_item1a.txt")
    if os.path.exists(risk_text_path):
        with open(risk_text_path, encoding="utf-8") as f:
            risk_text = f.read()
    else:
        print("  File not found — scraping now...")
        risk_text = scrape_sec_filing(ticker, section="item1a")

    prompt = build_prompt(ticker, metrics, risk_text)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Add your key to the .env file."
        )

    print(f"[agent] Sending to {MODEL}...")
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.3,
        ),
    )

    memo = response.text
    return memo


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    memo = run_analysis(ticker)

    print("\n" + "=" * 60)
    print(f"  INVESTMENT MEMO: {ticker.upper()}")
    print("=" * 60)
    print(memo)

    out_path = os.path.join("data", f"{ticker.upper()}_memo.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(memo)
    print(f"\n[agent] Memo saved to {out_path}")
