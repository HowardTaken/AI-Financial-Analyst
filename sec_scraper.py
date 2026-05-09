import os
import re
import json
import requests
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "AI-Market-Analyst contact@example.com"}
SEC_BASE = "https://www.sec.gov"


def get_cik(ticker: str) -> str:
    """Return zero-padded 10-digit CIK for a ticker."""
    url = f"{SEC_BASE}/files/company_tickers.json"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    for entry in r.json().values():
        if entry["ticker"].upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10)
    raise ValueError(f"Ticker '{ticker}' not found in SEC company list.")


def get_latest_10k(cik: str) -> tuple[str, str]:
    """Return (accession_number, primary_document) for the most recent 10-K."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    filings = r.json()["filings"]["recent"]

    for i, form in enumerate(filings["form"]):
        if form == "10-K":
            return filings["accessionNumber"][i], filings["primaryDocument"][i]

    raise ValueError(f"No 10-K found for CIK {cik}.")


def fetch_filing_text(cik: str, accession: str, primary_doc: str) -> str:
    """Download the primary 10-K document and return raw HTML."""
    acc_nodash = accession.replace("-", "")
    cik_int = int(cik)
    url = f"{SEC_BASE}/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary_doc}"
    print(f"  Fetching filing: {url}")
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


def extract_section(html: str, section: str) -> str:
    """
    Extract a named section from 10-K HTML.
    section: 'item1a' (Risk Factors) or 'item7' (MD&A)
    Returns clean plain text.
    """
    # Match headings with a period after the item number — this reliably
    # distinguishes actual section headings from TOC cross-references, and
    # works across both "Item 1A.  Risk Factors" (AAPL) and "ITEM 1A. RIS"
    # split-line formats (MSFT).
    SECTION_PATTERNS = {
        "item1a": (
            r"^\s*ITEM\s+1A\.",
            r"^\s*ITEM\s+1B\.",
        ),
        "item7": (
            r"^\s*ITEM\s+7\.",
            r"^\s*ITEM\s+7A\.",
        ),
    }

    if section not in SECTION_PATTERNS:
        raise ValueError(f"Unknown section '{section}'. Use 'item1a' or 'item7'.")

    start_pat, end_pat = SECTION_PATTERNS[section]

    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(separator="\n")
    # Normalise to uppercase for pattern matching only; keep original for output
    lines = full_text.split("\n")
    lines_upper = [l.upper() for l in lines]

    # Find the actual section (not a TOC hit) by requiring end to be found
    # at least 50 lines after start.
    start_idx = None
    end_idx = None

    candidates = [i for i, l in enumerate(lines_upper) if re.search(start_pat, l)]

    # For each start candidate, find the FIRST end-pattern match after it.
    # If that first match is >= 50 lines away, it's a real section (not a TOC
    # row). If it's too close, this candidate is a TOC entry — discard it and
    # move to the next candidate. This prevents pairing a TOC start with a
    # body-section end, which would scoop up the entire table of contents.
    for c in candidates:
        for j in range(c + 1, len(lines_upper)):
            if re.search(end_pat, lines_upper[j]):
                if j - c >= 50:
                    start_idx = c
                    end_idx = j
                break  # always stop at the first end match for this candidate
        if start_idx is not None:
            break

    if start_idx is None:
        raise RuntimeError(f"Could not locate '{section}' section in filing.")

    section_lines = lines[start_idx:end_idx]

    # Clean up: remove blank runs and non-printable chars
    cleaned = []
    prev_blank = False
    for line in section_lines:
        line = line.replace("\xa0", " ").strip()
        line = re.sub(r"[^\x20-\x7E\n]", "", line)  # strip non-ASCII
        if not line:
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    return "\n".join(cleaned).strip()


def scrape_sec_filing(ticker: str, section: str = "item1a") -> str:
    """
    Full pipeline: ticker → CIK → latest 10-K → extract section → save .txt
    Returns the extracted text.
    """
    print(f"[sec_scraper] Looking up CIK for {ticker.upper()}...")
    cik = get_cik(ticker)
    print(f"  CIK: {cik}")

    print(f"[sec_scraper] Finding latest 10-K...")
    accession, primary_doc = get_latest_10k(cik)
    print(f"  Accession: {accession}  |  Doc: {primary_doc}")

    html = fetch_filing_text(cik, accession, primary_doc)

    print(f"[sec_scraper] Extracting '{section}'...")
    text = extract_section(html, section)

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", f"{ticker.upper()}_{section}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"Ticker: {ticker.upper()}\n")
        f.write(f"Section: {section}\n")
        f.write(f"Accession: {accession}\n")
        f.write("=" * 60 + "\n\n")
        f.write(text)

    print(f"[sec_scraper] Saved to {out_path}  ({len(text):,} chars)")
    return text


if __name__ == "__main__":
    text = scrape_sec_filing("AAPL", section="item1a")

    print("\n--- Preview (first 1500 chars) ---\n")
    print(text[:1500])
    print("\n...\n")
    print(f"Total extracted: {len(text):,} characters")
