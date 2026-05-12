"""
transcript_scraper.py
---------------------
Fetches the most recent earnings call highlights for a given ticker using
Gemini 2.5 Flash with Google Search grounding.

No third-party transcript API key is required — the same GEMINI_API_KEY
used throughout the app is sufficient.
"""

from google import genai
from google.genai import types
from config import get_secret


def get_earnings_transcript(ticker: str) -> str:
    """
    Uses Gemini 2.5 Flash with Google Search grounding to retrieve and
    summarise the most recent earnings call for `ticker`.

    Returns a structured text block covering:
      1. Opening remarks & headline results
      2. Forward guidance
      3. Strategic priorities
      4. Risks & headwinds acknowledged by management
      5. Notable analyst Q&A exchanges

    Raises EnvironmentError if GEMINI_API_KEY is not configured.
    """
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Add it to your .env file (local) "
            "or the Streamlit Cloud Secrets dashboard."
        )

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


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"Fetching earnings transcript for {ticker.upper()}...\n")
    text = get_earnings_transcript(ticker)
    print(text[:3000])
    print(f"\n... ({len(text):,} total chars)")
