"""
Forward test of the agent's actual ratings.

Every rating the agent issues is appended to data/predictions.jsonl (see predictions.py). This script
scores them against what the stock did since, relative to SPY, once enough time has passed. Because
the rating was logged before the outcome existed, it cannot suffer look-ahead bias.

Run:  python -m analyst.evaluate [--min-days 30]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import yfinance as yf

from .predictions import load_predictions

# A rating is "right" when: BUY beats SPY, SELL trails SPY. HOLD is not scored (no directional claim).
DIRECTIONAL = {"BUY": 1, "SELL": -1}


def _total_return(ticker: str, start: datetime, end: datetime) -> float | None:
    df = yf.Ticker(ticker).history(start=start.date().isoformat(), end=end.date().isoformat(), auto_adjust=True)
    if len(df) < 2:
        return None
    return float(df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100


def score(predictions: list[dict], min_days: int = 30, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    rows = []
    for p in predictions:
        try:
            made = datetime.fromisoformat(p["timestamp"])
        except (KeyError, ValueError):
            continue
        if (now - made).days < min_days:
            continue
        stock, bench = _total_return(p["ticker"], made, now), _total_return("SPY", made, now)
        if stock is None or bench is None:
            continue
        rows.append({**p, "days": (now - made).days, "return_pct": stock, "excess_pct": stock - bench})
    return rows


def report(rows: list[dict]) -> str:
    if not rows:
        return "No ratings are old enough to score yet. Keep running analyses and check back."
    lines = [f"{'Ticker':<7}{'Rating':<6}{'Conf':<8}{'Days':>5}{'Return':>9}{'vs SPY':>9}  Verdict"]
    scored = right = 0
    for r in rows:
        direction = DIRECTIONAL.get(r["rating"])
        verdict = "n/a (HOLD)"
        if direction:
            scored += 1
            ok = direction * r["excess_pct"] > 0
            right += ok
            verdict = "right" if ok else "wrong"
        lines.append(f"{r['ticker']:<7}{r['rating']:<6}{r['confidence']:<8}{r['days']:>5}"
                     f"{r['return_pct']:>8.1f}%{r['excess_pct']:>+8.1f}%  {verdict}")
    if scored:
        lines.append(f"\nDirectional accuracy: {right}/{scored} ({right / scored:.0%}). "
                     "Tiny samples are noise; judge only after dozens of ratings.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score logged ratings against SPY.")
    parser.add_argument("--min-days", type=int, default=30)
    args = parser.parse_args()
    print(report(score(load_predictions(), args.min_days)))


if __name__ == "__main__":
    main()
