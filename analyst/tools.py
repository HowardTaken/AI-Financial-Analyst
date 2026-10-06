"""
Agent tools: the functions the LLM can call, their JSON-schema declarations, and a safe dispatcher.

Each tool returns (result_dict, one_line_summary). Results are JSON-serialisable and are what the
model sees. Tools also record their raw output on the shared AnalysisContext so the UI can render
tabs after the run without re-fetching anything.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from typing import Any

from google.genai import types
from pydantic import ValidationError

from . import market_data, sec, transcripts, valuation
from .models import AnalysisContext, Memo, Peer

log = logging.getLogger(__name__)

RISK_TEXT_LIMIT = 30_000   # chars of Item 1A handed to the model (~7.5k tokens)
PEER_METRIC_KEYS = ("current_price", "pe_ratio", "gross_margin_pct", "yoy_revenue_growth_pct",
                    "debt_to_equity", "price_to_book", "roe_pct")

ToolResult = tuple[dict[str, Any], str]

_TICKER_PARAM = {
    "type": "string",
    "description": "Ticker symbol. Omit to use the company being analysed.",
}

DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "get_financial_metrics",
        "description": (
            "Fetch fundamentals from Yahoo Finance and compute price, P/E (TTM when available), "
            "debt/equity, gross margin, YoY revenue growth, price/book and ROE, plus sector and "
            "industry. Always call this first for the target. Can also be used on any other ticker "
            "(e.g. a competitor you want to inspect)."
        ),
        "parameters_json_schema": {"type": "object", "properties": {"ticker": _TICKER_PARAM}},
    },
    {
        "name": "run_dcf_valuation",
        "description": (
            "Run a discounted-cash-flow valuation (unlevered FCF, CAPM-based WACC, growth fading to "
            "terminal, net-debt bridge). Returns intrinsic value per share, upside vs price, terminal-"
            "value share, warnings and a WACC x terminal-growth sensitivity grid. Returns "
            "available=false with a reason for banks/insurers or negative FCF. Optional overrides let "
            "you run scenarios."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "ticker": _TICKER_PARAM,
                "wacc_pct": {"type": "number", "description": "Override discount rate, in percent (e.g. 9.5)."},
                "terminal_growth_pct": {"type": "number", "description": "Terminal growth in percent (default 2.0)."},
                "growth_cap_pct": {"type": "number", "description": "Cap on starting FCF growth in percent (default 10)."},
                "deduct_sbc": {"type": "boolean", "description": "Treat stock-based compensation as a cash cost."},
            },
        },
    },
    {
        "name": "get_risk_factors",
        "description": "Download the company's latest 10-K from SEC EDGAR and return Item 1A (Risk Factors).",
        "parameters_json_schema": {"type": "object", "properties": {"ticker": _TICKER_PARAM}},
    },
    {
        "name": "get_earnings_call_summary",
        "description": (
            "Summarise the most recent earnings call (guidance, strategy, risks, Q&A) via Google "
            "Search. Returns grounded=false when no web sources back the summary; treat that as unverified."
        ),
        "parameters_json_schema": {"type": "object", "properties": {"ticker": _TICKER_PARAM}},
    },
    {
        "name": "get_peer_comparison",
        "description": (
            "Compare the target with peers and return each peer's metrics and market cap plus peer "
            "medians. By default peers are the largest companies in the same Yahoo Finance industry, "
            "which are OFTEN POOR MATCHES (small caps, different business models). Check the market "
            "caps and names; if they are not real competitors, call this again with `tickers` set to "
            "real direct competitors you choose."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "tickers": {"type": "array", "items": {"type": "string"},
                            "description": "Competitor tickers to use instead of Yahoo's industry list (max 6)."},
                "max_peers": {"type": "integer", "description": "Peers to take from Yahoo's list (default 4, max 6)."},
            },
        },
    },
    {
        "name": "submit_memo",
        "description": (
            "Submit the final investment memo. Call exactly once, after gathering evidence. "
            "Returns an error if the memo is invalid so you can fix and resubmit."
        ),
        "parameters_json_schema": Memo.model_json_schema(),
    },
]


class ToolBox:
    """Binds the tool functions to one analysis context."""

    def __init__(self, ctx: AnalysisContext):
        self.ctx = ctx
        self._tools: dict[str, Callable[..., ToolResult]] = {
            "get_financial_metrics": self.get_financial_metrics,
            "run_dcf_valuation": self.run_dcf_valuation,
            "get_risk_factors": self.get_risk_factors,
            "get_earnings_call_summary": self.get_earnings_call_summary,
            "get_peer_comparison": self.get_peer_comparison,
            "submit_memo": self.submit_memo,
        }

    def declarations(self) -> list[types.FunctionDeclaration]:
        return [types.FunctionDeclaration(**d) for d in DECLARATIONS]

    def execute(self, name: str, args: dict[str, Any] | None) -> tuple[dict[str, Any], str, bool]:
        """Run a tool; never raises. Returns (result, summary, ok). Errors go back to the model."""
        fn = self._tools.get(name)
        if fn is None:
            return {"error": f"Unknown tool '{name}'."}, f"unknown tool {name}", False
        try:
            result, summary = fn(**(args or {}))
            return result, summary, "error" not in result
        except TypeError as exc:  # bad/unknown argument names from the model
            return {"error": f"Invalid arguments for {name}: {exc}"}, "invalid arguments", False
        except Exception as exc:
            log.warning("Tool %s failed: %s", name, exc, exc_info=log.isEnabledFor(logging.DEBUG))
            return {"error": f"{type(exc).__name__}: {exc}"}, f"failed: {type(exc).__name__}", False

    # ── helpers ──────────────────────────────────────────────────────────────
    def _symbol(self, ticker: str | None) -> tuple[str, bool]:
        symbol = market_data.normalize_ticker(ticker) if ticker else self.ctx.ticker
        return symbol, symbol == self.ctx.ticker

    # ── tools ────────────────────────────────────────────────────────────────
    def get_financial_metrics(self, ticker: str | None = None) -> ToolResult:
        symbol, is_target = self._symbol(ticker)
        data = market_data.fetch_financials(symbol)
        metrics = valuation.calculate_metrics(data)
        with self.ctx.lock:
            if is_target:
                self.ctx.data, self.ctx.metrics = data, metrics
            else:
                self.ctx.other_metrics[symbol] = metrics
        result = asdict(metrics) | {
            "sector": data.sector, "industry": data.industry,
            "beta": data.beta, "market_cap": data.market_cap,
        }
        pe = f"{metrics.pe_ratio}x" if metrics.pe_ratio is not None else "n/a"
        return result, f"{symbol}: price {metrics.current_price}, P/E {pe}, {data.industry}"

    def run_dcf_valuation(
        self,
        ticker: str | None = None,
        wacc_pct: float | None = None,
        terminal_growth_pct: float | None = None,
        growth_cap_pct: float | None = None,
        deduct_sbc: bool = False,
    ) -> ToolResult:
        symbol, is_target = self._symbol(ticker)
        data = market_data.fetch_financials(symbol)
        kwargs: dict[str, Any] = {"deduct_sbc": bool(deduct_sbc)}
        if wacc_pct is not None:
            kwargs["wacc"] = wacc_pct / 100
        if terminal_growth_pct is not None:
            kwargs["terminal_growth"] = terminal_growth_pct / 100
        if growth_cap_pct is not None:
            kwargs["growth_cap"] = growth_cap_pct / 100
        dcf = valuation.calculate_dcf(data, **kwargs)
        with self.ctx.lock:
            # The first DCF on the target is the base case shown in the UI; later calls are scenarios.
            if is_target and self.ctx.dcf is None:
                self.ctx.dcf = dcf
        if not dcf.available:
            return asdict(dcf), f"{symbol}: DCF not applicable ({dcf.reason[:70]})"
        return asdict(dcf), (
            f"{symbol}: intrinsic ${dcf.intrinsic_value:,.2f} vs ${dcf.current_price:,.2f} "
            f"({dcf.upside_pct:+.1f}% upside, WACC {dcf.wacc_pct:.1f}%)"
        )

    def get_risk_factors(self, ticker: str | None = None) -> ToolResult:
        symbol, is_target = self._symbol(ticker)
        filing = sec.get_filing_section(symbol, "item1a")
        if is_target:
            with self.ctx.lock:
                self.ctx.filing = filing
        text, truncated = sec.truncate_at_boundary(filing.text, RISK_TEXT_LIMIT)
        return (
            {"accession": filing.accession, "total_chars": len(filing.text),
             "truncated": truncated, "text": text},
            f"{symbol}: 10-K {filing.accession}, {len(filing.text):,} chars"
            + (" (truncated for the model)" if truncated else ""),
        )

    def get_earnings_call_summary(self, ticker: str | None = None) -> ToolResult:
        symbol, is_target = self._symbol(ticker)
        summary = transcripts.get_earnings_summary(symbol)
        if is_target:
            with self.ctx.lock:
                self.ctx.earnings = summary
        note = ("Backed by cited web sources." if summary.is_grounded
                else "No grounding sources were returned; treat this summary as unverified.")
        return (
            {"text": summary.text, "grounded": summary.is_grounded, "sources": summary.sources, "note": note},
            f"{symbol}: {len(summary.text):,} chars, {len(summary.sources)} sources",
        )

    def get_peer_comparison(
        self, tickers: list[str] | None = None, max_peers: int = 4, ticker: str | None = None
    ) -> ToolResult:
        # `ticker` is accepted (and ignored) because models habitually pass it; peers are always for the target.
        data = self.ctx.data or market_data.fetch_financials(self.ctx.ticker)
        if tickers:
            chosen = list(dict.fromkeys(market_data.normalize_ticker(t) for t in tickers))
            peers = [Peer(ticker=t, name=t) for t in chosen if t != self.ctx.ticker][:6]
            selection = "chosen by the analyst"
        else:
            limit = max(1, min(int(max_peers), 6))
            peers = market_data.find_peers(data.industry_key, self.ctx.ticker, limit)
            selection = f"top companies in Yahoo's '{data.industry}' industry"
        if not peers:
            return {"error": "No peers to compare. Pass `tickers` with real competitors."}, "no peers"

        def load(peer: Peer) -> Peer:
            peer = replace(peer)  # don't mutate cached objects
            try:
                peer_data = market_data.fetch_financials(peer.ticker)
                peer.metrics = valuation.calculate_metrics(peer_data)
                peer.market_cap = peer_data.market_cap
            except Exception as exc:
                peer.error = f"{type(exc).__name__}: {exc}"
            return peer

        with ThreadPoolExecutor(max_workers=len(peers)) as pool:
            peers = list(pool.map(load, peers))
        with self.ctx.lock:
            self.ctx.peers = peers  # the latest comparison is the one shown in the UI

        ok = [p for p in peers if p.metrics]
        result = {
            "target_market_cap": data.market_cap,
            "selection": selection,
            "peers": [
                {"ticker": p.ticker, "name": p.name, "market_cap": p.market_cap,
                 "metrics": {k: getattr(p.metrics, k) for k in PEER_METRIC_KEYS}} if p.metrics
                else {"ticker": p.ticker, "name": p.name, "error": p.error}
                for p in peers
            ],
            "peer_median": valuation.peer_medians([p.metrics for p in ok]),
        }
        return result, f"{len(ok)}/{len(peers)} peers ({selection}): " + ", ".join(p.ticker for p in ok)

    def submit_memo(self, **fields: Any) -> ToolResult:
        try:
            memo = Memo.model_validate(fields)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            return {"error": f"Memo rejected: {problems}. Fix these fields and call submit_memo again."}, "memo rejected"
        with self.ctx.lock:
            self.ctx.memo = memo
        return {"status": "accepted"}, f"{memo.rating} ({memo.confidence} confidence)"


def run_calls_parallel(
    toolbox: ToolBox,
    calls: list[tuple[str, dict[str, Any]]],
    on_done: Callable[[int, dict[str, Any], str, bool, float], None],
) -> list[dict[str, Any]]:
    """Execute independent tool calls concurrently; returns results in call order."""

    def timed(item: tuple[str, dict[str, Any]]):
        started = time.monotonic()
        result, summary, ok = toolbox.execute(*item)
        return result, summary, ok, time.monotonic() - started

    results: list[dict[str, Any]] = [{}] * len(calls)
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {pool.submit(timed, c): i for i, c in enumerate(calls)}
        for future in as_completed(futures):
            i = futures[future]
            result, summary, ok, seconds = future.result()
            results[i] = result
            on_done(i, result, summary, ok, seconds)
    return results
