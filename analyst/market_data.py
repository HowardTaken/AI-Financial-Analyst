"""Yahoo Finance access: statements, market inputs and peer discovery. Everything stays in memory."""

from __future__ import annotations

import logging
import re

import yfinance as yf

from .cache import ttl_cache
from .models import FinancialData, Peer, Statement
from .valuation import DEFAULT_RISK_FREE

log = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")


class DataUnavailableError(RuntimeError):
    """Raised when Yahoo returns nothing usable for a ticker."""


def normalize_ticker(ticker: str) -> str:
    """Uppercase and validate a ticker; rejects anything that is not a plausible symbol."""
    t = (ticker or "").strip().upper()
    if not _TICKER_RE.match(t):
        raise ValueError(f"'{ticker}' is not a valid ticker symbol.")
    return t


def _df_to_statement(df) -> Statement:
    """DataFrame (rows=line items, cols=period timestamps) -> {period: {item: float|None}}."""
    if df is None or df.empty:
        return {}
    return {
        str(col)[:10]: {str(idx): (float(val) if val == val else None) for idx, val in df[col].items()}
        for col in df.columns
    }


@ttl_cache(6 * 3600)
def get_risk_free_rate() -> float:
    """10-year Treasury yield from Yahoo (^TNX); falls back to a constant if unavailable."""
    try:
        close = yf.Ticker("^TNX").history(period="5d")["Close"].dropna()
        rate = float(close.iloc[-1]) / 100
        if 0.0 < rate < 0.15:
            return rate
    except Exception as exc:
        log.warning("Risk-free rate lookup failed (%s); using %.2f%%", exc, DEFAULT_RISK_FREE * 100)
    return DEFAULT_RISK_FREE


@ttl_cache(15 * 60)
def fetch_financials(ticker: str) -> FinancialData:
    """
    Fetch statements plus market inputs for `ticker`. Cached for 15 minutes; treat the returned
    object as read-only.
    """
    ticker = normalize_ticker(ticker)
    stock = yf.Ticker(ticker)
    income = _df_to_statement(stock.financials)
    balance = _df_to_statement(stock.balance_sheet)
    cash_flow = _df_to_statement(stock.cashflow)
    if not income:
        raise DataUnavailableError(f"No financial statements found for '{ticker}'. Check the symbol.")

    try:
        info = stock.info or {}
    except Exception as exc:  # Yahoo's info endpoint is flaky; statements alone are still useful
        log.warning("yfinance info failed for %s: %s", ticker, exc)
        info = {}

    return FinancialData(
        ticker=ticker,
        current_price=info.get("currentPrice") or info.get("regularMarketPrice"),
        income_statement=income,
        balance_sheet=balance,
        cash_flow=cash_flow,
        beta=info.get("beta"),
        trailing_eps=info.get("trailingEps"),
        shares_outstanding=info.get("sharesOutstanding"),
        market_cap=info.get("marketCap"),
        sector=info.get("sector") or "Unknown",
        industry=info.get("industry") or "Unknown",
        industry_key=info.get("industryKey"),
        risk_free_rate=get_risk_free_rate(),
    )


@ttl_cache(6 * 3600)
def find_peers(industry_key: str | None, exclude: str, limit: int = 4) -> list[Peer]:
    """Top companies in the same Yahoo industry by market weight, excluding `exclude`."""
    if not industry_key:
        raise DataUnavailableError("Yahoo returned no industry key, so peers cannot be identified.")
    top = yf.Industry(industry_key).top_companies
    peers: list[Peer] = []
    for symbol, row in top.iterrows():
        if str(symbol).upper() == exclude.upper():
            continue
        peers.append(Peer(
            ticker=str(symbol),
            name=str(row.get("name", symbol)),
            market_weight=float(row.get("market weight", 0) or 0),
        ))
        if len(peers) == limit:
            break
    return peers
