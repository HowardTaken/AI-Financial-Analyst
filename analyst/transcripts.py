"""
Earnings-call summaries via Gemini with Google Search grounding.

This is a *summary assembled from web sources*, not a verbatim transcript, so the result carries
the grounding source URLs and the UI/agent are told to treat un-sourced output as unverified.
"""

from __future__ import annotations

import re

from google.genai import types

from . import llm
from .cache import ttl_cache
from .models import EarningsSummary

SECTION_TITLES = [
    "Opening Remarks & Results",
    "Forward Guidance",
    "Strategic Priorities",
    "Risks & Headwinds",
    "Analyst Q&A Highlights",
]


# Search grounding occasionally takes minutes; fail fast so the agent can proceed without it.
SEARCH_TIMEOUT_MS = 90_000


class TranscriptUnavailableError(RuntimeError):
    pass


def _prompt(ticker: str) -> str:
    headings = "\n".join(f"## {i}. {t}" for i, t in enumerate(SECTION_TITLES, 1))
    return (
        f"Find the most recent quarterly earnings call for {ticker}. Summarise what the CEO and CFO "
        "said using ONLY information you find in sources. Start with a line 'CALL DATE: <date>' and "
        "the fiscal quarter. Then use exactly these markdown headings, in order:\n"
        f"{headings}\n\n"
        "Rules: use bullet points; only put text in quotation marks if it is a verbatim quote found in "
        "a source; give figures exactly as reported; if you cannot find a recent call or a section, "
        "write 'NOT FOUND' for it instead of guessing."
    )


@ttl_cache(6 * 3600)
def get_earnings_summary(ticker: str) -> EarningsSummary:
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.2,
        http_options=types.HttpOptions(timeout=SEARCH_TIMEOUT_MS),
    )
    response = llm.generate(_prompt(ticker.upper()), config)
    text = response.text
    if not text or not text.strip():
        raise TranscriptUnavailableError(f"Gemini returned no earnings-call content for {ticker}.")

    sources: list[dict[str, str]] = []
    try:
        meta = response.candidates[0].grounding_metadata
        seen = set()
        for chunk in (meta.grounding_chunks or []) if meta else []:
            web = chunk.web
            if web and web.uri and web.uri not in seen:
                seen.add(web.uri)
                sources.append({"title": web.title or web.domain or web.uri, "uri": web.uri})
    except (AttributeError, IndexError):
        pass
    return EarningsSummary(ticker=ticker.upper(), text=text.strip(), sources=sources)


def parse_sections(text: str) -> list[dict[str, str]]:
    """Split a summary on its '## n. Title' headings. Falls back to one block if none are found."""
    parts = re.split(r"(?m)^##\s*\d*\.?\s*(.+?)\s*$", text)
    # re.split with one group -> [preamble, title1, body1, title2, body2, ...]
    sections = [
        {"heading": parts[i].strip(), "body": parts[i + 1].strip()}
        for i in range(1, len(parts) - 1, 2)
        if parts[i + 1].strip()
    ]
    if sections:
        preamble = parts[0].strip()
        if preamble:
            sections.insert(0, {"heading": "Call Overview", "body": preamble})
        return sections
    return [{"heading": "Earnings Call Summary", "body": text.strip()}]
