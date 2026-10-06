"""
Point-in-time backtest of the QUANTITATIVE signal (the DCF engine).

What this does and does not test
--------------------------------
* It tests whether DCF upside, computed only from statements that were public at the as-of date,
  predicted the stock's return over the following 12 months relative to SPY.
* It does NOT test the LLM. An LLM's training data, Google Search grounding and today's Yahoo
  data all contain the future, so a historical LLM backtest would be contaminated by look-ahead.
  LLM ratings are instead evaluated going forward: every rating is logged (predictions.py) and
  scored later by evaluate.py.

Known biases (also reported in the README): the ticker universe is today's large caps (survivorship
and size bias); yfinance only exposes ~4 annual statements, so only a few as-of dates are possible;
beta and the share count are not point-in-time; the sample is small and the result is noisy.

Run:  python -m analyst.backtest --asof 2024-04-01 --asof 2025-04-01
"""

from __future__ import annotations

import argparse
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from . import market_data
from .models import FinancialData
from .valuation import calculate_dcf

log = logging.getLogger(__name__)

REPORTING_LAG_DAYS = 90        # annual statements are assumed public 90 days after period end
HORIZON_DAYS = 365
BENCHMARK = "SPY"
UNIVERSE = (
    "AAPL MSFT NVDA GOOGL AMZN META AVGO ORCL ADBE CRM CSCO INTC QCOM TXN AMD "
    "KO PEP PG WMT COST MCD NKE SBUX HD LOW TGT DIS NFLX CMCSA VZ T "
    "JNJ PFE MRK ABBV LLY UNH ABT TMO MDT AMGN GILD "
    "XOM CVX COP CAT DE BA HON UPS LMT GE MMM "
    "V MA PYPL ADP LIN NEE DUK SO"
).split()


@dataclass
class Observation:
    ticker: str
    asof: date
    dcf_upside_pct: float
    forward_return_pct: float
    benchmark_return_pct: float

    @property
    def excess_return_pct(self) -> float:
        return self.forward_return_pct - self.benchmark_return_pct


def truncate_as_of(data: FinancialData, asof: date, price: float, lag_days: int = REPORTING_LAG_DAYS) -> FinancialData:
    """Copy of `data` containing only statement periods public at `asof`, priced at `price`."""
    cutoff = asof - timedelta(days=lag_days)

    def keep(statement):
        return {p: v for p, v in statement.items() if date.fromisoformat(p) <= cutoff}

    return replace(
        data,
        current_price=price,
        income_statement=keep(data.income_statement),
        balance_sheet=keep(data.balance_sheet),
        cash_flow=keep(data.cash_flow),
        beta=None,                # today's beta is not point-in-time; fall back to 1.0
        trailing_eps=None,
        market_cap=None,
        risk_free_rate=None,      # fall back to the module default
    )


def price_on_or_after(history: pd.Series, day: date) -> float | None:
    """First close on or after `day` (None if the series ends before it)."""
    window = history[history.index >= pd.Timestamp(day)]
    return float(window.iloc[0]) if len(window) else None


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation (average ranks for ties); None if undefined."""
    if len(xs) < 3:
        return None
    rx, ry = pd.Series(xs).rank(), pd.Series(ys).rank()
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(rx.corr(ry))


def summarize(obs: list[Observation]) -> dict:
    """Aggregate statistics for a set of observations."""
    if not obs:
        return {"n": 0}
    ups = [o.dcf_upside_pct for o in obs]
    ex = [o.excess_return_pct for o in obs]
    ordered = sorted(obs, key=lambda o: o.dcf_upside_pct)
    k = max(1, len(ordered) // 3)
    bottom, top = ordered[:k], ordered[-k:]
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    flagged = [o for o in obs if o.dcf_upside_pct > 0]
    return {
        "n": len(obs),
        "information_coefficient": spearman(ups, ex),
        "hit_rate_positive_upside_beats_spy": (
            mean([1.0 if o.excess_return_pct > 0 else 0.0 for o in flagged]) if flagged else None),
        "n_positive_upside": len(flagged),
        "base_rate_beats_spy": mean([1.0 if e > 0 else 0.0 for e in ex]),
        "top_third_excess_return_pct": mean([o.excess_return_pct for o in top]),
        "bottom_third_excess_return_pct": mean([o.excess_return_pct for o in bottom]),
        "spread_top_minus_bottom_pct": mean([o.excess_return_pct for o in top]) - mean([o.excess_return_pct for o in bottom]),
        "median_upside_pct": sorted(ups)[len(ups) // 2],
    }


def _history(ticker: str) -> pd.Series | None:
    try:
        df = yf.Ticker(ticker).history(period="6y", auto_adjust=True)
        if df.empty:
            return None
        df.index = df.index.tz_localize(None)
        return df["Close"]
    except Exception as exc:
        log.warning("price history failed for %s: %s", ticker, exc)
        return None


def run_backtest(asof_dates: list[date], tickers: list[str] | None = None) -> tuple[list[Observation], list[str]]:
    """Compute observations. Returns (observations, human-readable skip reasons)."""
    tickers = tickers or UNIVERSE
    bench = _history(BENCHMARK)
    if bench is None:
        raise RuntimeError("Could not download benchmark prices.")

    def load(t: str):
        try:
            return t, market_data.fetch_financials(t), _history(t)
        except Exception as exc:
            return t, exc, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        loaded = list(pool.map(load, tickers))

    observations: list[Observation] = []
    skipped: list[str] = []
    for ticker, data, prices in loaded:
        if isinstance(data, Exception) or prices is None:
            skipped.append(f"{ticker}: data unavailable")
            continue
        for asof in asof_dates:
            end = asof + timedelta(days=HORIZON_DAYS)
            p0, p1 = price_on_or_after(prices, asof), price_on_or_after(prices, end)
            b0, b1 = price_on_or_after(bench, asof), price_on_or_after(bench, end)
            if None in (p0, p1, b0, b1):
                skipped.append(f"{ticker}@{asof}: horizon extends past available prices")
                continue
            dcf = calculate_dcf(truncate_as_of(data, asof, p0))
            if not dcf.available or dcf.upside_pct is None or math.isnan(dcf.upside_pct):
                skipped.append(f"{ticker}@{asof}: DCF not applicable ({dcf.reason[:50]})")
                continue
            observations.append(Observation(ticker, asof, dcf.upside_pct,
                                            (p1 / p0 - 1) * 100, (b1 / b0 - 1) * 100))
    return observations, skipped


def format_report(obs: list[Observation], skipped: list[str]) -> str:
    s = summarize(obs)
    if not s["n"]:
        return "No observations."
    f = lambda v, spec=".1f", suf="": "n/a" if v is None else f"{v:{spec}}{suf}"  # noqa: E731
    return "\n".join([
        f"Observations: {s['n']} (skipped {len(skipped)})",
        f"Information coefficient (Spearman, DCF upside vs 12m excess return): {f(s['information_coefficient'], '+.3f')}",
        f"Top third by upside, mean excess return:    {f(s['top_third_excess_return_pct'], '+.1f', '%')}",
        f"Bottom third by upside, mean excess return: {f(s['bottom_third_excess_return_pct'], '+.1f', '%')}",
        f"Spread (top - bottom):                      {f(s['spread_top_minus_bottom_pct'], '+.1f', '%')}",
        f"Positive-upside names beating SPY: {f(s['hit_rate_positive_upside_beats_spy'] and s['hit_rate_positive_upside_beats_spy'] * 100, '.0f', '%')} "
        f"of {s['n_positive_upside']} (base rate, all names: {f(s['base_rate_beats_spy'] * 100, '.0f', '%')})",
        f"Median DCF upside across sample: {f(s['median_upside_pct'], '+.0f', '%')}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Point-in-time backtest of the DCF signal.")
    parser.add_argument("--asof", action="append", required=True, help="As-of date YYYY-MM-DD (repeatable).")
    parser.add_argument("--tickers", nargs="*", help="Override the default universe.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    obs, skipped = run_backtest([date.fromisoformat(d) for d in args.asof], args.tickers)
    print(format_report(obs, skipped))
    if skipped:
        print(f"\nSkipped ({len(skipped)}): " + "; ".join(skipped[:12]) + (" ..." if len(skipped) > 12 else ""))


if __name__ == "__main__":
    main()
