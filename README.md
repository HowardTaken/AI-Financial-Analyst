# AI Wall Street Analyst — Professional-Grade Market Intelligence Platform

A full-stack investment research platform that combines live financial data, automated valuation modelling, SEC filing intelligence, earnings call analysis, and peer benchmarking — all synthesised by Google Gemini 2.5 Flash into a definitive **Buy, Hold, or Sell** investment memo.

Built to replicate the research workflow of a Wall Street analyst, end-to-end, in under 60 seconds.

---

## What's New in v2.0

| Feature | Details |
|---|---|
| **Automated DCF Modelling** | Perpetual-growth DCF with 5-year FCF projections, WACC discounting, intrinsic value per share, and margin-of-safety calculation |
| **Earnings Call Sentiment Analysis** | Fetches the most recent earnings call transcript (FMP API or Gemini Search grounding) and extracts structured insights — management tone, forward guidance, strategic priorities, and risks acknowledged |
| **Competitor Benchmarking** | Automatically identifies top-2 industry peers via `yf.Industry` and runs a side-by-side fundamental comparison (P/E, Gross Margin, Revenue Growth, D/E) |
| **Professional Web Dashboard** | Streamlit UI with a 4-tab results layout, DCF hero card, FCF line chart, colour-coded peer table, and persistent search history |
| **10-K vs Earnings Call Cross-Analysis** | Gemini is prompted to compare disclosed risk factors against management's actual tone — surfacing contradictions and new catalysts |

---

## Platform Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   AI Wall Street Analyst                        │
│                                                                 │
│  ┌──────────┐  ┌─────────────┐  ┌────────────┐  ┌──────────┐  │
│  │ Yahoo    │  │ SEC EDGAR   │  │ Earnings   │  │ yfinance │  │
│  │ Finance  │  │ 10-K / 1A   │  │ Transcript │  │ Industry │  │
│  └────┬─────┘  └──────┬──────┘  └─────┬──────┘  └────┬─────┘  │
│       │               │               │               │         │
│       └───────────────┴───────────────┴───────────────┘         │
│                               │                                 │
│                    ┌──────────▼──────────┐                      │
│                    │  Gemini 2.5 Flash   │                      │
│                    │  Wall Street Prompt │                      │
│                    └──────────┬──────────┘                      │
│                               │                                 │
│              Buy / Hold / Sell + 400-word Thesis                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 📊 Automated DCF Valuation Model
- Pulls 3–4 years of Free Cash Flow history from Yahoo Finance
- Calculates average YoY FCF growth rate (capped at 10% to avoid overfitting)
- Projects FCF 5 years forward and discounts to present value at WACC (10%)
- Adds a terminal value using the perpetual growth method (2% terminal rate)
- Outputs: intrinsic value per share, margin of safety, and an UNDERVALUED / OVERVALUED verdict

### 🎙 Earnings Call Analysis
- **Primary source:** Financial Modeling Prep (FMP) API for verbatim transcripts
- **Automatic fallback:** Gemini 2.5 Flash with Google Search grounding when FMP is unavailable (no extra key needed)
- Structured into 5 insight cards: *Opening Remarks, Forward Guidance, Strategic Priorities, Risks & Headwinds, Analyst Q&A*
- Gemini cross-references 10-K risk disclosures against management tone to flag contradictions

### 🏆 Competitor Benchmarking
- Automatically identifies the target company's sector and industry via `yfinance`
- Fetches the top 2 peers by market weight from `yf.Industry`
- Runs a full fundamental mini-analysis on each peer
- Renders a colour-coded comparison table: ▲ green = best-in-class, ▼ red = weakest

### 💰 Valuation Dashboard (Streamlit)
- **4-tab layout:** Overview · Valuation Model · Earnings Insights · Peer Comparison
- **DCF Hero Card:** Intrinsic value displayed in large bold type (green = undervalued, red = overvalued) against current price
- **FCF Line Chart:** `st.line_chart` plots projected FCF and present value across Y+1 to Y+5
- **Persistent history:** Previous analyses saved to `history.json` and restored on refresh; one-click reload from sidebar

---

## Project Structure

```
AI-Financial-Analyst/
├── app.py                 # Streamlit web dashboard (primary UI)
├── main.py                # Terminal loop (alternative CLI entry point)
├── data_fetcher.py        # yfinance financial data + competitor discovery
├── calculator.py          # Fundamental metrics + DCF valuation model
├── sec_scraper.py         # SEC EDGAR 10-K scraper (Item 1A Risk Factors)
├── transcript_scraper.py  # Earnings call transcript (FMP API + Gemini Search fallback)
├── agent.py               # Gemini prompt builder + LLM orchestration
├── .env                   # API keys (not committed)
├── .gitignore
└── README.md
```

---

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/HowardTaken/AI-Financial-Analyst.git
cd AI-Financial-Analyst
```

### 2. Create and Activate a Virtual Environment

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install yfinance pandas streamlit google-genai python-dotenv beautifulsoup4 requests
```

### 4. Configure API Keys

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_key_here
FMP_API_KEY=your_fmp_key_here        # Optional — app falls back to Gemini Search
```

- **Gemini API key** (required): [aistudio.google.com](https://aistudio.google.com) — free tier available
- **FMP API key** (optional): [financialmodelingprep.com](https://financialmodelingprep.com) — enables verbatim earnings transcripts; Starter plan required for transcript endpoint. Without it, Gemini Search grounding is used automatically.

---

## Running the App

### Web Dashboard (recommended)

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501), enter a ticker in the sidebar, and click **Run Analysis**.

### Terminal CLI

```bash
python main.py
```

---

## Analysis Pipeline

Each run executes 7 steps automatically:

| Step | Action |
|---|---|
| 1 | Fetch 4 years of financials from Yahoo Finance |
| 2 | Calculate P/E, Gross Margin, D/E, Revenue Growth |
| 3 | Run DCF model → intrinsic value + margin of safety |
| 4 | Scrape SEC EDGAR 10-K → Item 1A Risk Factors |
| 5 | Fetch most recent earnings call transcript |
| 6 | Run competitor mini-analysis (top 2 peers by market weight) |
| 7 | Send all data to Gemini 2.5 Flash → Buy / Hold / Sell memo |

Steps 3, 5, and 6 are non-fatal — if data is unavailable the pipeline continues and the memo is generated with the remaining sources.

---

## Example Output

```
╔══════════════════════════════════════╗
║  NVDA  ·  FY 2025     ● BUY         ║
╠══════════════════════════════════════╣
║  Price: $135.40   DCF Target: $182.11   MoS: +26.2% UNDERVALUED
║  P/E: 52.3x   Gross Margin: 75.0%   Rev Growth: +114.2%
╚══════════════════════════════════════╝

RATING: STRONG BUY

QUANTITATIVE CASE
NVIDIA's fundamentals are best-in-class. 114% YoY revenue growth, 75% gross
margins, and a DCF intrinsic value of $182 versus the current $135 price
implies a 26% margin of safety...

10-K vs EARNINGS CALL
The 10-K flags export controls and customer concentration as key risks. CEO
Jensen Huang's tone on the Q1 2025 call was markedly more confident, citing
Blackwell demand "exceeding supply" — a direct contradiction of the
demand-uncertainty narrative in the filing...
```

---

## Disclaimer

This tool is for **educational and research purposes only**. It does not constitute financial advice. Always conduct your own due diligence before making investment decisions.
