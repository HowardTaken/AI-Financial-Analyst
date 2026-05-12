"""
transcript_scraper.py
---------------------
Fetches the most recent earnings call transcript for a given ticker.

Strategy (in order):
  1. Financial Modeling Prep (FMP) REST API  — if FMP_API_KEY is set in .env
  2. Gemini 2.5 Flash + Google Search grounding — reliable fallback with no
     extra API key required beyond the GEMINI_API_KEY already in use

FMP free-tier note: the earning_call_transcript endpoint requires at least the
Starter plan.  If the key is absent or the call fails, the scraper falls back
to Gemini Search automatically.
"""

import os
import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

FMP_BASE = "https://financialmodelingprep.com/api"


# ── FMP path ──────────────────────────────────────────────────────────────────

def _fmp_get_latest_transcript_meta(ticker: str, api_key: str) -> tuple[int, int]:
    """
    Returns (quarter, year) of the most recent available transcript via FMP.
    Raises ValueError if none are found.
    """
    url = (
        f"{FMP_BASE}/v4/earning_call_transcript"
        f"?symbol={ticker.upper()}&apikey={api_key}"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not data or not isinstance(data, list):
        raise ValueError(f"No transcript metadata found for {ticker} via FMP.")

    # FMP returns newest first
    latest = data[0]
    return int(latest["quarter"]), int(latest["year"])


def fetch_transcript_fmp(ticker: str, api_key: str) -> str:
    """
    Downloads the most recent earnings call transcript from FMP.
    Returns a clean text block.
    """
    quarter, year = _fmp_get_latest_transcript_meta(ticker, api_key)

    url = (
        f"{FMP_BASE}/v3/earning_call_transcript/{ticker.upper()}"
        f"?quarter={quarter}&year={year}&apikey={api_key}"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not data or not isinstance(data, list):
        raise ValueError("Empty transcript body returned by FMP.")

    entry = data[0]
    date    = entry.get("date", "")
    content = entry.get("content", "").strip()

    if not content:
        raise ValueError("FMP returned a transcript with no content.")

    header = (
        f"EARNINGS CALL TRANSCRIPT — {ticker.upper()} "
        f"Q{quarter} {year}  ({date})\n"
        + "=" * 60 + "\n\n"
    )
    return header + content


# ── Gemini Search fallback ────────────────────────────────────────────────────

def fetch_transcript_gemini(ticker: str, api_key: str) -> str:
    """
    Uses Gemini 2.5 Flash with Google Search grounding to find the latest
    earnings call highlights.  No additional API key needed — uses the same
    GEMINI_API_KEY as the rest of the app.
    """
    client = genai.Client(api_key=api_key)

    prompt = (
        f"Find the most recent quarterly earnings call for {ticker.upper()}. "
        f"Provide a detailed summary of exactly what the CEO and CFO said, covering:\n"
        f"1. Opening remarks and headline financial results (revenue, EPS, margins)\n"
        f"2. Forward revenue and earnings guidance for the next quarter and full year\n"
        f"3. Key strategic priorities and major initiatives announced\n"
        f"4. Risks, headwinds, or challenges explicitly acknowledged by management\n"
        f"5. Notable exchanges from the analyst Q&A section\n\n"
        f"Use direct quotes where possible. State the date of the call at the top."
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=1,
        ),
    )

    header = (
        f"EARNINGS CALL HIGHLIGHTS — {ticker.upper()} "
        f"(sourced via Gemini Search)\n"
        + "=" * 60 + "\n\n"
    )
    return header + response.text


# ── Public entry point ────────────────────────────────────────────────────────

def get_earnings_transcript(ticker: str) -> str:
    """
    Main entry point.  Tries FMP first, falls back to Gemini Search.
    Returns a raw text block of earnings call content.
    """
    fmp_key    = os.getenv("FMP_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    # ── Attempt FMP ───────────────────────────────────────────────────────────
    if fmp_key and fmp_key not in ("your_fmp_key_here", ""):
        try:
            return fetch_transcript_fmp(ticker, fmp_key)
        except Exception as e:
            print(f"[transcript] FMP failed ({e}). Falling back to Gemini Search.")

    # ── Fallback: Gemini Search ───────────────────────────────────────────────
    if not gemini_key or gemini_key == "your_api_key_here":
        raise EnvironmentError(
            "No transcript source available. "
            "Set FMP_API_KEY or GEMINI_API_KEY in your .env file."
        )

    return fetch_transcript_gemini(ticker, gemini_key)


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"Fetching earnings transcript for {ticker.upper()}...\n")
    text = get_earnings_transcript(ticker)
    print(text[:3000])
    print(f"\n... ({len(text):,} total chars)")
