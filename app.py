"""Streamlit front end. All analysis logic lives in the `analyst` package; this file only renders."""

from __future__ import annotations

import logging
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
from google.genai import errors as genai_errors

from analyst import history
from analyst.agent import AgentError
from analyst.formatting import fmt_num, peer_table_html, result_to_markdown
from analyst.market_data import DataUnavailableError
from analyst.models import AnalysisResult
from analyst.pipeline import analyze
from analyst.transcripts import parse_sections
from analyst.valuation import peer_medians

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

st.set_page_config(page_title="AI Market Analyst", page_icon="📊", layout="wide")
st.markdown(f"<style>{(Path(__file__).parent / 'assets' / 'style.css').read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = history.load()
st.session_state.setdefault("current", st.session_state.history[0] if st.session_state.history else None)

RATING_ICON = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}


def rating_badge(rating: str) -> str:
    return f"<span class='badge badge-{rating.lower()}'>{escape(rating)}</span>"


# ── Rendering ─────────────────────────────────────────────────────────────────

def render_header(r: AnalysisResult) -> None:
    left, right = st.columns([4, 1])
    fiscal = f"FY {r.metrics.fiscal_year}" if r.metrics else ""
    left.markdown(
        f"## {escape(r.ticker)} &nbsp;·&nbsp; <span style='color:#8b949e;font-size:1rem;font-weight:400;'>"
        f"{escape(fiscal)}</span>", unsafe_allow_html=True)
    right.markdown(
        f"<div style='text-align:right;margin-top:10px;'>{rating_badge(r.memo.rating)}<br>"
        f"<span style='color:#8b949e;font-size:0.8rem;'>{escape(r.memo.confidence.title())} confidence</span></div>",
        unsafe_allow_html=True)

    m = r.metrics
    if m:
        st.markdown("<p class='section-label'>Fundamental Metrics</p>", unsafe_allow_html=True)
        cols = st.columns(5)
        cols[0].metric("Price", fmt_num(m.current_price, ",.2f", prefix="$"))
        cols[1].metric(f"P/E ({m.eps_basis})", fmt_num(m.pe_ratio, ".1f", suffix="x"))
        cols[2].metric("Gross margin", fmt_num(m.gross_margin_pct, ".1f", suffix="%"))
        cols[3].metric("Debt / equity", fmt_num(m.debt_to_equity, ".2f"))
        cols[4].metric("Revenue growth", fmt_num(m.yoy_revenue_growth_pct, ".1f", suffix="%"),
                       delta=f"{m.yoy_revenue_growth_pct:+.1f}% YoY" if m.yoy_revenue_growth_pct is not None else None)
        st.caption(f"Fiscal year ending {m.fiscal_year} · Yahoo Finance · agent run took {r.elapsed_seconds:.0f}s")


def render_overview(r: AnalysisResult) -> None:
    for w in r.warnings:
        st.warning(w, icon="⚠️")
    st.markdown("<p class='section-label'>Investment Memo</p>", unsafe_allow_html=True)
    st.markdown(f"### {r.memo.headline}")
    if r.memo.price_target is not None:
        st.metric("12-month price target", fmt_num(r.memo.price_target, ",.2f", prefix="$"))
    st.markdown("**Quantitative case**")
    st.markdown(r.memo.quantitative_case)
    st.markdown("**10-K vs. earnings call**")
    st.markdown(r.memo.filing_vs_call)
    left, right = st.columns(2)
    with left:
        st.markdown("**Key risks**")
        st.markdown("\n".join(f"- {x}" for x in r.memo.key_risks) or "_None listed_")
    with right:
        st.markdown("**Catalysts**")
        st.markdown("\n".join(f"- {x}" for x in r.memo.catalysts) or "_None listed_")
    st.markdown("**Verdict**")
    st.markdown(r.memo.verdict)
    if r.memo.data_gaps:
        st.info("**Data gaps:** " + "; ".join(r.memo.data_gaps))
    st.download_button("⬇️ Download memo (.md)", result_to_markdown(r), f"{r.ticker}_memo.md",
                       "text/markdown", use_container_width=True)


def render_valuation(r: AnalysisResult) -> None:
    dcf = r.dcf
    if dcf is None:
        st.markdown("<div class='empty-state'>The agent did not run a DCF for this company.</div>",
                    unsafe_allow_html=True)
        return
    if not dcf.available:
        st.warning(f"DCF not applicable: {dcf.reason}")
        if r.metrics and (r.metrics.price_to_book or r.metrics.roe_pct):
            c1, c2 = st.columns(2)
            c1.metric("Price / book", fmt_num(r.metrics.price_to_book, ".2f", suffix="x"))
            c2.metric("ROE", fmt_num(r.metrics.roe_pct, ".1f", suffix="%"))
        return

    up = (dcf.upside_pct or 0) > 0
    direction = "up" if up else "down"
    st.markdown(
        f"""<div class='hero-card'>
            <div class='hero-label'>DCF intrinsic value per share (base case)</div>
            <div class='hero-price {direction}'>{fmt_num(dcf.intrinsic_value, ",.2f", prefix="$")}</div>
            <div class='hero-vs'>vs. current market price</div>
            <div class='hero-curr'>{fmt_num(dcf.current_price, ",.2f", prefix="$")}</div>
            <div class='hero-pill {direction}'>{'▲' if up else '▼'} {abs(dcf.upside_pct or 0):.1f}% implied
            {'upside' if up else 'downside'}</div></div>""",
        unsafe_allow_html=True)
    st.caption("A mechanical model that extrapolates historical free cash flow. It tends to be harsh on "
               "fast-growing, high-multiple companies; read the sensitivity table before trusting the gap.")

    c = st.columns(5)
    c[0].metric("WACC", f"{dcf.wacc_pct:.1f}%", help="CAPM cost of equity blended with after-tax cost of debt")
    c[1].metric("Terminal growth", f"{dcf.terminal_growth_pct:.1f}%")
    c[2].metric("Year-1 FCF growth", f"{dcf.starting_growth_pct:.1f}%",
                help=f"Historical {dcf.raw_growth_pct:.1f}%, capped; fades to terminal growth by year 5")
    c[3].metric("Terminal value share", f"{dcf.terminal_value_share_pct:.0f}%")
    c[4].metric("Margin of safety", fmt_num(dcf.margin_of_safety_pct, "+.1f", suffix="%"),
                help="(Intrinsic value − price) ÷ intrinsic value. Not the same as upside.")
    for w in dcf.warnings:
        st.caption(f"⚠️ {w}")

    st.markdown("<p class='section-label'>Sensitivity: intrinsic value per share</p>", unsafe_allow_html=True)
    s = dcf.sensitivity
    grid = pd.DataFrame(
        [[("n/a" if v is None else f"${v:,.0f}") for v in row] for row in s["values"]],
        index=[f"WACC {w:.1f}%" for w in s["wacc_pct"]],
        columns=[f"g {g:.1f}%" for g in s["terminal_growth_pct"]],
    )
    st.dataframe(grid, use_container_width=True)

    st.markdown("<p class='section-label'>Projected free cash flow ($B)</p>", unsafe_allow_html=True)
    st.line_chart(pd.DataFrame(
        {"Projected FCF": [v / 1e9 for v in dcf.projected_fcf],
         "Present value": [v / 1e9 for v in dcf.pv_projected_fcf]},
        index=[f"Year +{i + 1}" for i in range(len(dcf.projected_fcf))]), use_container_width=True)
    with st.expander("Equity bridge"):
        st.table({
            "Item": ["PV of 5-year cash flows", "PV of terminal value", "Enterprise value", "Net debt",
                     "Equity value", "Shares outstanding"],
            "Value": [f"${sum(dcf.pv_projected_fcf):,.0f}", f"${dcf.pv_terminal_value:,.0f}",
                      f"${dcf.enterprise_value:,.0f}", f"${dcf.net_debt:,.0f}", f"${dcf.equity_value:,.0f}",
                      f"{dcf.shares_outstanding:,.0f}"],
        })


def render_earnings(r: AnalysisResult) -> None:
    e = r.earnings
    if e is None:
        st.markdown("<div class='empty-state'>No earnings-call summary was retrieved for this run.</div>",
                    unsafe_allow_html=True)
        return
    if e.is_grounded:
        st.success(f"Summary backed by {len(e.sources)} cited web source(s).")
    else:
        st.warning("No grounding sources were returned. Treat this summary as unverified.")
    st.caption("This is an AI-generated summary assembled from web search results, not a verbatim transcript.")
    for sec in parse_sections(e.text):
        st.markdown(f"<div class='insight-card'><div class='insight-heading'>{escape(sec['heading'])}</div></div>",
                    unsafe_allow_html=True)
        st.markdown(sec["body"])
    if e.sources:
        with st.expander("Sources"):
            for src in e.sources:
                st.markdown(f"- [{src['title']}]({src['uri']})")


def render_peers(r: AnalysisResult) -> None:
    ok = [p for p in r.peers if p.metrics]
    if not (ok and r.metrics):
        st.markdown("<div class='empty-state'>No peer data was retrieved for this run.</div>",
                    unsafe_allow_html=True)
        return
    st.markdown(peer_table_html(r.metrics, r.peers, peer_medians([p.metrics for p in ok])),
                unsafe_allow_html=True)
    st.caption("▲ best / ▼ worst per row (lower is better for P/E, D/E, P/B). Peers are the largest "
               "companies in the same Yahoo Finance industry; they are not hand-picked.")
    failed = [p for p in r.peers if not p.metrics]
    if failed:
        st.caption("Skipped: " + ", ".join(f"{p.ticker} ({p.error})" for p in failed))


def render_trace(r: AnalysisResult) -> None:
    st.markdown("<p class='section-label'>What the agent did</p>", unsafe_allow_html=True)
    for s in r.trace:
        mark = "" if s.ok else " <span class='trace-fail'>(failed)</span>"
        args = ", ".join(f"{k}={v}" for k, v in s.args.items() if k != "text")[:120]
        st.markdown(
            f"<div class='trace-row'><span class='trace-tool'>{escape(s.tool)}</span>"
            f"{escape('(' + args + ')') if s.tool != 'submit_memo' else ''}{mark}"
            f" · {s.seconds:.1f}s<br><span style='color:#8b949e;'>{escape(s.summary)}</span></div>",
            unsafe_allow_html=True)
    st.caption("Independent tool calls are issued together and run in parallel; the model decides the order.")


def render_results(r: AnalysisResult) -> None:
    render_header(r)
    st.divider()
    tabs = st.tabs(["📋 Memo", "💰 Valuation", "🎙 Earnings Call", "🏆 Peers", "🤖 Agent Activity"])
    for tab, fn in zip(tabs, (render_overview, render_valuation, render_earnings, render_peers, render_trace), strict=True):
        with tab:
            fn(r)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 AI Market Analyst")
    st.markdown("<p style='color:#8b949e;font-size:0.85rem;'>A tool-calling Gemini agent that researches a "
                "company and writes a Buy / Hold / Sell memo.</p>", unsafe_allow_html=True)
    st.divider()
    ticker_input = st.text_input("Ticker", placeholder="e.g. AAPL, NVDA, JPM", label_visibility="collapsed")
    run_btn = st.button("🚀 Run analysis", use_container_width=True, type="primary")

    if st.session_state.history:
        st.divider()
        st.markdown("<p class='section-label'>Recent</p>", unsafe_allow_html=True)
        for i, entry in enumerate(st.session_state.history):
            active = "◀" if st.session_state.current and entry.ticker == st.session_state.current.ticker else ""
            if st.button(f"{RATING_ICON[entry.memo.rating]} {entry.ticker} {active}", key=f"hist_{i}",
                         use_container_width=True):
                st.session_state.current = entry
                st.rerun()
    st.divider()
    st.caption("Data: Yahoo Finance · SEC EDGAR · Gemini. Educational research only, not financial advice.")


# ── Main ──────────────────────────────────────────────────────────────────────
st.markdown("# AI Market Analyst")
st.divider()

if run_btn:
    if not ticker_input.strip():
        st.warning("Enter a ticker symbol first.")
    else:
        try:
            with st.status(f"Agent researching {ticker_input.strip().upper()}…", expanded=True) as status:
                def on_event(event: dict) -> None:
                    kind = event["type"]
                    if kind == "tool_start":
                        st.write(f"🔧 calling `{event['tool']}`")
                    elif kind == "tool_end":
                        st.write(f"{'✅' if event['ok'] else '❌'} `{event['tool']}`: {event['summary']}")
                    elif kind == "reasoning":
                        st.write(f"💭 {event['text'][:300]}")

                result = analyze(ticker_input, on_event=on_event)
                status.update(label=f"Done in {result.elapsed_seconds:.0f}s", state="complete", expanded=False)
            st.session_state.current = result
            st.session_state.history = history.add(st.session_state.history, result)
            history.save(st.session_state.history)
        except genai_errors.APIError as exc:
            hint = " You have likely hit the Gemini quota; wait a minute and retry." if exc.code == 429 else ""
            st.error(f"The Gemini API returned an error ({exc.code}).{hint}")
        except (ValueError, DataUnavailableError, AgentError) as exc:
            st.error(f"Analysis failed: {exc}")
        except Exception as exc:  # unexpected: show it, keep the app alive, log the traceback
            logging.getLogger("app").exception("Unhandled error during analysis")
            st.error(f"Unexpected error: {type(exc).__name__}: {exc}")

if st.session_state.current:
    render_results(st.session_state.current)
else:
    st.markdown("<div class='empty-state'>Enter a ticker in the sidebar and click <b>Run analysis</b>.<br>"
                "The agent decides which data to pull, runs a DCF, reads the latest 10-K and earnings call, "
                "compares peers, and writes the memo.</div>", unsafe_allow_html=True)
