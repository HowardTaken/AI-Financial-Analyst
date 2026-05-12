import os
from google import genai
from google.genai import types
from config import get_secret

SYSTEM_INSTRUCTION = (
    "You are a senior Wall Street analyst with expertise in DCF valuation, "
    "fundamental analysis, and qualitative risk assessment. "
    "You are now analyzing both the SEC 10-K (Risk Factors) and the most recent "
    "Earnings Call (Management Guidance). "
    "Compare what the company said it was worried about in the 10-K versus how "
    "confident management sounded in the Earnings Call. "
    "Highlight any contradictions or new positive catalysts mentioned by the CEO. "
    "Synthesise all data sources — quantitative metrics, DCF intrinsic value, "
    "SEC risk factors, earnings call, and peer comparison — into a definitive "
    "Buy, Hold, or Sell rating followed by a brutal, evidence-based 400-word "
    "investment thesis. "
    "Structure your output as: "
    "(1) RATING, "
    "(2) QUANTITATIVE CASE (include peer comparison where available), "
    "(3) 10-K vs EARNINGS CALL COMPARISON, "
    "(4) VERDICT."
)

MODEL = "gemini-2.5-flash"


def build_prompt(
    ticker: str,
    metrics: dict,
    risk_text: str,
    dcf: dict = None,
    transcript: str = None,
    competitors: list = None,
) -> str:
    d = metrics["_details"]

    # ── Quantitative metrics ──────────────────────────────────────────────────
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
"""

    # ── DCF valuation ─────────────────────────────────────────────────────────
    if dcf:
        fcf_hist  = "  →  ".join(
            f"${v/1e9:.1f}B" for v in dcf["fcf_history"].values()
        )
        fcf_proj  = "  →  ".join(f"${v/1e9:.1f}B" for v in dcf["projected_fcf"])
        mos       = dcf["margin_of_safety_pct"]
        mos_label = f"{mos:+.1f}%  ({'UNDERVALUED' if mos > 0 else 'OVERVALUED'})"

        prompt += f"""
--- DCF VALUATION MODEL (Perpetual Growth Method) ---
WACC:                 {dcf['wacc_pct']:.1f}%
Terminal Growth Rate: {dcf['terminal_growth_pct']:.1f}%
FCF Growth Rate Used: {dcf['capped_growth_rate_pct']:.1f}%  (3yr avg, capped at 10%)
Historical FCF:       {fcf_hist}
Projected FCF (5yr):  {fcf_proj}
Intrinsic Value/Share: ${dcf['intrinsic_value']:.2f}
Current Price:         ${dcf['current_price']:.2f}
Margin of Safety:      {mos_label}
"""

    # ── SEC risk factors ──────────────────────────────────────────────────────
    prompt += f"""
--- SEC 10-K RISK FACTORS (Item 1A) ---
{risk_text[:5000]}
"""

    # ── Earnings call ─────────────────────────────────────────────────────────
    if transcript:
        prompt += f"""
--- MOST RECENT EARNINGS CALL (Management Guidance) ---
Use this section to assess how confident management sounded, what forward
guidance they gave, and whether their tone contradicts or aligns with the
risks disclosed in the 10-K above. Flag any specific CEO or CFO statements
that either reinforce the 10-K risks or introduce new positive catalysts.

{transcript[:4000]}
"""
    else:
        prompt += """
--- EARNINGS CALL ---
No earnings call transcript was available. Base the 10-K vs Earnings Call
comparison section on the SEC filing alone and note the absence of transcript data.
"""

    # ── Competitor comparison ─────────────────────────────────────────────────
    if competitors:
        prompt += "\n--- PEER COMPARISON (same industry) ---\n"
        prompt += f"{'Metric':<26} {ticker.upper():<12}"
        for c in competitors:
            prompt += f" {c['ticker']:<12}"
        prompt += "\n" + "-" * (26 + 13 * (1 + len(competitors))) + "\n"

        def fmt(val, prefix="", suffix=""):
            return f"{prefix}{val}{suffix}" if val is not None else "N/A"

        rows = [
            ("Current Price",      fmt(metrics["current_price"],        "$"),
             [fmt(c["metrics"].get("current_price"),                     "$") for c in competitors]),
            ("P/E Ratio",          fmt(metrics["pe_ratio"],              suffix="x"),
             [fmt(c["metrics"].get("pe_ratio"),                          suffix="x") for c in competitors]),
            ("Gross Margin",       fmt(metrics["gross_margin_pct"],      suffix="%"),
             [fmt(c["metrics"].get("gross_margin_pct"),                  suffix="%") for c in competitors]),
            ("Revenue Growth YoY", fmt(metrics["yoy_revenue_growth_pct"],suffix="%"),
             [fmt(c["metrics"].get("yoy_revenue_growth_pct"),            suffix="%") for c in competitors]),
            ("Debt / Equity",      fmt(metrics["debt_to_equity"]),
             [fmt(c["metrics"].get("debt_to_equity"))                                for c in competitors]),
        ]
        for label, target_val, comp_vals in rows:
            line = f"{label:<26} {target_val:<12}"
            for cv in comp_vals:
                line += f" {cv:<12}"
            prompt += line + "\n"

    return prompt.strip()


def run_analysis(
    ticker: str,
    metrics: dict,
    risk_text: str,
    dcf: dict = None,
    transcript: str = None,
    competitors: list = None,
) -> str:
    """
    Call Gemini with pre-computed data.  DCF, transcript, and competitors are
    optional — the memo is still generated if any are unavailable.
    Returns the investment memo as a string.
    """
    prompt = build_prompt(ticker, metrics, risk_text, dcf, transcript, competitors)

    api_key = get_secret("GEMINI_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Add your key to the .env file."
        )

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.3,
        ),
    )

    return response.text


if __name__ == "__main__":
    import sys
    from calculator import calculate_metrics, calculate_dcf
    from sec_scraper import scrape_sec_filing
    from transcript_scraper import get_earnings_transcript

    ticker  = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    metrics = calculate_metrics(ticker)
    dcf     = calculate_dcf(ticker)
    risk    = scrape_sec_filing(ticker, section="item1a")
    trans   = get_earnings_transcript(ticker)
    memo    = run_analysis(ticker, metrics, risk, dcf=dcf, transcript=trans)

    print("\n" + "=" * 60)
    print(f"  INVESTMENT MEMO: {ticker.upper()}")
    print("=" * 60)
    print(memo)

    out_path = os.path.join("data", f"{ticker.upper()}_memo.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(memo)
    print(f"\n[agent] Memo saved to {out_path}")
