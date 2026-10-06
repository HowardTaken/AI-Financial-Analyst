"""SEC EDGAR access: ticker -> CIK -> latest 10-K -> clean plain-text Item 1A (Risk Factors)."""

from __future__ import annotations

import bisect
import logging
import re
import threading
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .cache import ttl_cache
from .config import sec_user_agent
from .models import SecFiling

log = logging.getLogger(__name__)

SEC_BASE = "https://www.sec.gov"
NEWLINE = chr(10)
MIN_SECTION_CHARS = 1500  # anything shorter is a table-of-contents hit, not a real section

# Per section: compact heading prefix, compact title, and a regex for the heading of whichever item
# can legitimately follow (1B/1C/2 after risk factors). Only Item 1A is supported: it is the only
# section the agent uses, and the heading rule below is tuned and live-tested for it.
SECTION_SPECS = {
    "item1a": ("ITEM1A", "RISKFACTORS", r"^\s*ITEM\s*(1B|1C|2)\b"),
}

_ASCII_FIXES = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
    "•": "-", "…": "...", "\xa0": " ",
})


class FilingNotFoundError(RuntimeError):
    """No usable 10-K was found (e.g. foreign private issuers file 20-F/40-F instead)."""


# ── HTTP with retries and SEC's 10 requests/second courtesy limit ────────────

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",),
)))
_throttle_lock = threading.Lock()
_last_request = 0.0


def _get(url: str, timeout: int = 30) -> requests.Response:
    global _last_request
    with _throttle_lock:
        wait = 0.12 - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
    resp = _session.get(url, headers={"User-Agent": sec_user_agent()}, timeout=timeout)
    resp.raise_for_status()
    return resp


# ── Lookup ───────────────────────────────────────────────────────────────────

@ttl_cache(24 * 3600)
def _ticker_to_cik() -> dict[str, str]:
    data = _get(f"{SEC_BASE}/files/company_tickers.json").json()
    return {e["ticker"].upper(): str(e["cik_str"]).zfill(10) for e in data.values()}


def get_cik(ticker: str) -> str:
    try:
        return _ticker_to_cik()[ticker.upper()]
    except KeyError:
        raise FilingNotFoundError(f"Ticker '{ticker}' not found in the SEC company list.") from None


def get_latest_10k(cik: str) -> tuple[str, str]:
    """(accession_number, primary_document) of the most recent 10-K."""
    recent = _get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()["filings"]["recent"]
    for form, accession, doc in zip(recent["form"], recent["accessionNumber"], recent["primaryDocument"], strict=True):
        if form == "10-K":
            return accession, doc
    raise FilingNotFoundError(
        f"No 10-K found for CIK {cik} (foreign issuers file 20-F/40-F; new listings may not have one yet)."
    )


# ── Parsing ──────────────────────────────────────────────────────────────────

def _clean_lines(lines: list[str]) -> str:
    cleaned: list[str] = []
    prev_blank = False
    for line in lines:
        line = re.sub(r"[^\x20-\x7E]", "", line.translate(_ASCII_FIXES)).strip()
        if not line:
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False
    return "\n".join(cleaned).strip()


def _is_heading(lines: list[str], i: int, prefix: str, title: str) -> bool:
    """
    True if line `i` begins a real section heading such as "Item 1A. Risk Factors".

    Looks at the line plus the next two non-empty lines with whitespace removed, which survives
    headings split across lines or even mid-word ("ITEM 1A. RIS" / "K FACTORS"). What follows the
    title distinguishes a heading (page number, capitalised body text, or nothing) from an inline
    cross-reference such as 'see Item 1A. Risk Factors" under ...' or "Item 1A. Risk Factors-Global".
    """
    chunk, taken, j = "", 0, i
    while j < len(lines) and taken < 3:
        piece = lines[j].strip()
        if piece:
            chunk += piece
            taken += 1
        j += 1
    compact = re.sub(r"\s+", "", chunk)
    m = re.match(rf"(?i){prefix}[.:\-–—]?{title}[.:]?", compact)
    if not m:
        return False
    rest = compact[m.end():]
    return rest == "" or rest[0].isupper() or rest[0].isdigit()


def extract_section(html: str, section: str) -> str:
    """
    Extract a named section from 10-K HTML as plain text.

    Heading lines are detected structurally (_is_heading). Each following-item heading is paired
    with the nearest real heading before it, and the LONGEST such span wins, so table-of-contents
    entries (tiny spans) lose to the real section. No per-company rules.
    """
    if section not in SECTION_SPECS:
        raise ValueError(f"Unknown section '{section}'. Use one of {sorted(SECTION_SPECS)}.")
    prefix, title, end_regex = SECTION_SPECS[section]
    end_pat = re.compile(end_regex)

    lines = BeautifulSoup(html, "html.parser").get_text(separator=NEWLINE).split(NEWLINE)
    upper = [line.upper() for line in lines]
    starts = [i for i in range(len(lines)) if _is_heading(lines, i, prefix, title)]

    best: tuple[int, int] | None = None
    for end, line in enumerate(upper):
        if not end_pat.search(line):
            continue
        k = bisect.bisect_left(starts, end)  # starts[:k] all precede this end
        if k and (best is None or end - starts[k - 1] > best[1] - best[0]):
            best = (starts[k - 1], end)

    if best is None:
        raise FilingNotFoundError(f"Could not locate '{section}' in the filing.")
    text = _clean_lines(lines[best[0]:best[1]])
    if len(text) < MIN_SECTION_CHARS:
        raise FilingNotFoundError(f"Located '{section}' but it is only {len(text)} chars; likely a parsing miss.")
    return text


def truncate_at_boundary(text: str, limit: int) -> tuple[str, bool]:
    """Cut `text` to at most `limit` chars on a paragraph/sentence boundary. Returns (text, was_truncated)."""
    if len(text) <= limit:
        return text, False
    window = text[:limit]
    cut = max(window.rfind("\n\n"), window.rfind(". "))
    return (window[:cut + 1] if cut > limit * 0.6 else window).strip(), True


@ttl_cache(24 * 3600)
def get_filing_section(ticker: str, section: str = "item1a") -> SecFiling:
    """Full pipeline for one ticker: CIK -> latest 10-K -> section text. Cached for a day."""
    cik = get_cik(ticker)
    accession, primary_doc = get_latest_10k(cik)
    url = f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary_doc}"
    log.info("Downloading %s 10-K %s", ticker, accession)
    html = _get(url, timeout=60).text
    return SecFiling(ticker=ticker.upper(), accession=accession, section=section,
                     text=extract_section(html, section))
