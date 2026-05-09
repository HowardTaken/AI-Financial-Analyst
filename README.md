# AI-Powered Market Analyst Agent

An autonomous Python agent that performs institutional-grade fundamental and qualitative analysis on any publicly traded stock. It combines live financial data, SEC filing intelligence, and Google's Gemini 2.5 Flash to generate a definitive **Buy, Hold, or Sell** investment memo — in seconds.

---

## Features

- **Automated Financial Data Fetching** — Pulls 5 years of income statements, balance sheets, and cash flow statements via `yfinance`
- **Fundamental Metric Calculation** — Computes P/E Ratio, Debt-to-Equity, Gross Margin, and Year-over-Year Revenue Growth automatically
- **SEC 10-K Scraping** — Fetches the most recent 10-K filing directly from SEC EDGAR and extracts Item 1A (Risk Factors) as clean plain text
- **LLM-Driven Investment Memos** — Feeds all quantitative and qualitative data into Gemini 2.5 Flash with a Wall Street analyst system prompt to generate a concise, brutal 300-word investment thesis
- **Continuous Ticker Loop** — Analyse multiple stocks in a single session without restarting the app
- **Local Output** — Saves all memos to a `data/` folder as `.txt` files for future reference

---

## Project Structure

```
AI-Financial-Analyst/
├── main.py            # Entry point — runs the interactive terminal loop
├── data_fetcher.py    # Downloads financial statements via yfinance
├── calculator.py      # Calculates fundamental metrics from raw data
├── sec_scraper.py     # Scrapes and parses SEC EDGAR 10-K filings
├── agent.py           # Builds the LLM prompt and calls Gemini 2.5 Flash
├── .gitignore
└── README.md
```

---

## Setup Instructions

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
pip install yfinance pandas google-genai python-dotenv beautifulsoup4 requests
```

### 4. Add Your Gemini API Key

Create a `.env` file in the root directory:

```bash
touch .env
```

Add the following line — replacing the placeholder with your actual key:

```
GEMINI_API_KEY=your_api_key_here
```

> You can obtain a free Gemini API key at [aistudio.google.com](https://aistudio.google.com)

---

## How to Use

Run the app from the project root:

```bash
python main.py
```

You will be prompted to enter a stock ticker symbol:

```
############################################################
#        AI Market Analyst - Investment Memo           #
############################################################
  Type a stock ticker to analyse, or 'exit' to quit.

  Ticker > NVDA
```

The agent will then run all four steps automatically:

1. Fetch 5 years of financial data from Yahoo Finance
2. Calculate fundamental metrics (P/E, Gross Margin, D/E, YoY Revenue Growth)
3. Scrape the latest SEC 10-K filing for qualitative risk factors
4. Send everything to Gemini 2.5 Flash and generate the investment memo

The memo is printed to the terminal and saved to `data/<TICKER>_memo.txt`.

To analyse another stock, simply enter the next ticker at the prompt. Type `exit` or `quit` to close the app.

---

## Example Output

```
============================================================
  INVESTMENT MEMO: NVDA
============================================================

RATING: BUY

NVIDIA presents an undeniable quantitative powerhouse... 65.47% YoY revenue
growth... fortress-like 71.07% gross margin... negligible Debt-to-Equity
ratio of 0.0702...

============================================================
```

---

## Disclaimer

This tool is for **educational and research purposes only**. It does not constitute financial advice. Always conduct your own due diligence before making investment decisions.
