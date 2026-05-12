import os
import json
import re
import pandas as pd
import streamlit as st

import config  # noqa: F401 — triggers load_dotenv() for local runs on import
from data_fetcher import fetch_financials, get_competitors
from calculator import calculate_metrics, calculate_dcf
from sec_scraper import scrape_sec_filing
from transcript_scraper import get_earnings_transcript
from agent import run_analysis

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Wall Street Analyst",
    page_icon="📊",
    layout="wide",
)

# ── History persistence helpers ───────────────────────────────────────────────
HISTORY_FILE = "history.json"

def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []

def save_history(history: list) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

# ── Session state defaults ────────────────────────────────────────────────────
for key, default in {
    "ticker":         None,
    "metrics":        None,
    "dcf":            None,
    "transcript":     None,
    "competitors":    None,
    "memo":           None,
    "history":        None,
    "history_loaded": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

if not st.session_state.history_loaded:
    st.session_state.history = load_history()
    st.session_state.history_loaded = True

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }

    [data-testid="stSidebar"] {
        background-color: #161b27;
        border-right: 1px solid #2a2f3e;
    }

    [data-testid="stMetric"] {
        background-color: #161b27;
        border: 1px solid #2a2f3e;
        border-radius: 10px;
        padding: 16px 20px;
    }
    [data-testid="stMetricLabel"] { color: #8b949e; font-size: 0.78rem; }
    [data-testid="stMetricValue"] { color: #e6edf3; font-size: 1.4rem; font-weight: 700; }

    /* Rating badges */
    .badge-buy  { background:#1a472a; color:#3fb950; border:1px solid #3fb950;
                  border-radius:8px; padding:6px 18px; font-weight:700;
                  font-size:1.1rem; display:inline-block; margin-bottom:16px; }
    .badge-hold { background:#3d2e00; color:#d29922; border:1px solid #d29922;
                  border-radius:8px; padding:6px 18px; font-weight:700;
                  font-size:1.1rem; display:inline-block; margin-bottom:16px; }
    .badge-sell { background:#4a1e1e; color:#f85149; border:1px solid #f85149;
                  border-radius:8px; padding:6px 18px; font-weight:700;
                  font-size:1.1rem; display:inline-block; margin-bottom:16px; }

    /* Section labels */
    .section-label {
        color: #8b949e;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 10px;
    }

    hr { border-color: #2a2f3e; }

    /* Investment memo */
    .memo-card {
        background-color: #161b27;
        border: 1px solid #2a2f3e;
        border-radius: 12px;
        padding: 28px 32px;
        line-height: 1.8;
        color: #cdd9e5;
        font-size: 0.97rem;
    }

    /* ── DCF Hero card ── */
    .hero-card {
        background: linear-gradient(135deg, #161b27 0%, #1a2035 100%);
        border: 1px solid #2a2f3e;
        border-radius: 16px;
        padding: 36px 40px;
        text-align: center;
        margin-bottom: 8px;
    }
    .hero-label {
        color: #8b949e;
        font-size: 0.8rem;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 10px;
    }
    .hero-price-green { font-size: 3.4rem; font-weight: 800;
                        letter-spacing: -0.02em; color: #3fb950; }
    .hero-price-red   { font-size: 3.4rem; font-weight: 800;
                        letter-spacing: -0.02em; color: #f85149; }
    .hero-vs    { color: #8b949e; font-size: 0.95rem; margin: 10px 0; }
    .hero-curr  { color: #e6edf3; font-size: 2rem; font-weight: 600; }
    .hero-pill-green {
        display: inline-block; margin-top: 18px;
        background: #1a472a; color: #3fb950;
        border: 1px solid #3fb950; border-radius: 20px;
        padding: 5px 24px; font-size: 1rem; font-weight: 700;
    }
    .hero-pill-red {
        display: inline-block; margin-top: 18px;
        background: #4a1e1e; color: #f85149;
        border: 1px solid #f85149; border-radius: 20px;
        padding: 5px 24px; font-size: 1rem; font-weight: 700;
    }

    /* ── Earnings insight cards ── */
    .insight-card {
        background: #161b27;
        border: 1px solid #2a2f3e;
        border-left: 3px solid #58a6ff;
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 12px;
        color: #cdd9e5;
        font-size: 0.91rem;
        line-height: 1.65;
    }
    .insight-heading {
        color: #58a6ff;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        margin-bottom: 6px;
    }

    /* ── Peer comparison table ── */
    .peer-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.88rem;
        margin-top: 4px;
    }
    .peer-table th {
        background: #1c2235;
        color: #8b949e;
        font-weight: 600;
        font-size: 0.75rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 10px 16px;
        text-align: center;
        border-bottom: 1px solid #2a2f3e;
    }
    .peer-table th.target-col {
        background: #1a2540;
        color: #58a6ff;
        border-bottom: 2px solid #58a6ff;
    }
    .peer-table td {
        padding: 10px 16px;
        text-align: center;
        border-bottom: 1px solid #1c2235;
        color: #cdd9e5;
    }
    .peer-table td.target-col { background: rgba(88,166,255,0.05); }
    .peer-table td.row-label  {
        text-align: left;
        color: #8b949e;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .peer-table tr:last-child td { border-bottom: none; }
    .cell-best  { color: #3fb950; font-weight: 700; }
    .cell-worst { color: #f85149; }
    .cell-na    { color: #555e6e; }

    /* Tab font size */
    button[data-baseweb="tab"] p { font-size: 0.88rem !important; }

    /* Empty-state box */
    .empty-state {
        background: #161b27;
        border: 1px dashed #2a2f3e;
        border-radius: 12px;
        padding: 48px;
        text-align: center;
        color: #555e6e;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)


# ── Helper functions ──────────────────────────────────────────────────────────

def extract_rating(memo: str) -> str:
    """Pull BUY / HOLD / SELL from the first matching line of the memo."""
    for line in memo.upper().splitlines():
        if "SELL" in line:
            return "SELL"
        if "BUY" in line:
            return "BUY"
        if "HOLD" in line:
            return "HOLD"
    return "HOLD"


def rating_badge(rating: str) -> str:
    cls = {"BUY": "badge-buy", "SELL": "badge-sell", "HOLD": "badge-hold"}.get(
        rating, "badge-hold"
    )
    return f'<span class="{cls}">&#9899;&nbsp;{rating}</span>'


def _fmt_num(val, spec: str = "", prefix: str = "", suffix: str = "", na: str = "N/A") -> str:
    """
    Safely format a numeric value.
    Returns `na` (default 'N/A') when val is None so format specifiers
    like :.2f never receive a NoneType and crash the UI.

    Examples
    --------
    _fmt_num(123.4,  ".2f",  prefix="$")   -> "$123.40"
    _fmt_num(None,   ".2f",  prefix="$")   -> "N/A"
    _fmt_num(0.75,   ".1f",  suffix="%")   -> "0.8%"
    _fmt_num(None,   "",     suffix="x")   -> "N/A"
    """
    if val is None:
        return na
    return f"{prefix}{val:{spec}}{suffix}" if spec else f"{prefix}{val}{suffix}"


def parse_transcript_bullets(transcript: str) -> list:
    """
    Parse transcript into structured sections.
    Handles Gemini Search format (numbered 1-5 sections) and raw FMP text.
    Returns list of {"heading": str, "body": str}.
    """
    SECTION_LABELS = {
        "1": "Opening Remarks & Results",
        "2": "Forward Guidance",
        "3": "Strategic Priorities",
        "4": "Risks & Headwinds Acknowledged",
        "5": "Analyst Q&A Highlights",
    }

    # Gemini Search transcripts use numbered sections at line start
    numbered = re.findall(
        r"(?m)^(\d+)\.\s+(.+?)(?=\n\d+\.\s|\Z)",
        transcript,
        flags=re.DOTALL,
    )
    if len(numbered) >= 3:
        results = []
        for num, body in numbered:
            heading = SECTION_LABELS.get(num, f"Section {num}")
            body = re.sub(r"\n{3,}", "\n\n", body.strip())
            results.append({"heading": heading, "body": body})
        return results

    # Fallback: pull the first 5 meaningful paragraphs from raw FMP text
    paragraphs = [
        p.strip() for p in re.split(r"\n{2,}", transcript) if len(p.strip()) > 100
    ]
    if paragraphs:
        generic = [
            "Management Commentary",
            "Key Financial Results",
            "Forward Outlook",
            "Strategic Initiatives",
            "Additional Remarks",
        ]
        return [
            {
                "heading": generic[i] if i < len(generic) else f"Section {i + 1}",
                "body": p[:700] + ("…" if len(p) > 700 else ""),
            }
            for i, p in enumerate(paragraphs[:5])
        ]

    return [{"heading": "Earnings Call Summary", "body": transcript[:1500]}]


def _peer_table_html(
    target_ticker: str,
    target_m: dict,
    competitors: list,
) -> str:
    """
    Build a fully styled HTML comparison table.
    Green = best-in-row, Red = worst-in-row (per metric).
    """
    valid = [c for c in competitors if "metrics" in c]
    all_tickers = [target_ticker] + [c["ticker"] for c in valid]
    all_metrics = [target_m] + [c["metrics"] for c in valid]

    def _v(m, key):
        val = m.get(key)
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    ROWS = [
        ("Current Price",   "current_price",          "$",  True,  2),
        ("P/E Ratio",       "pe_ratio",                "x",  False, 1),
        ("Gross Margin",    "gross_margin_pct",        "%",  True,  1),
        ("Rev Growth YoY",  "yoy_revenue_growth_pct",  "%",  True,  1),
        ("Debt / Equity",   "debt_to_equity",          "",   False, 2),
    ]

    # Header row
    header = "<tr>"
    header += "<th style='text-align:left;'>Metric</th>"
    for i, t in enumerate(all_tickers):
        cls = "target-col" if i == 0 else ""
        header += f"<th class='{cls}'>{t}</th>"
    header += "</tr>"

    body_rows = ""
    for label, key, suffix, higher_is_better, decimals in ROWS:
        vals = [_v(m, key) for m in all_metrics]
        floats = [v for v in vals if v is not None]

        best  = max(floats) if floats else None
        worst = min(floats) if floats else None
        if not higher_is_better and floats:
            best, worst = worst, best  # invert: lower is better

        row = f"<tr><td class='row-label'>{label}</td>"
        for i, (t, v) in enumerate(zip(all_tickers, vals)):
            td_class = "target-col" if i == 0 else ""
            if v is None:
                row += f"<td class='{td_class} cell-na'>—</td>"
            else:
                prefix = "$" if suffix == "" and key == "current_price" else ""
                if suffix == "$":
                    display = f"${v:,.{decimals}f}"
                else:
                    display = f"{v:+.{decimals}f}{suffix}" if suffix == "%" else f"{v:.{decimals}f}{suffix}"

                if best is not None and v == best:
                    cell_cls = f"{td_class} cell-best".strip()
                    display = "▲ " + display
                elif worst is not None and v == worst and len(floats) > 1:
                    cell_cls = f"{td_class} cell-worst".strip()
                    display = "▼ " + display
                else:
                    cell_cls = td_class

                row += f"<td class='{cell_cls}'>{display}</td>"
        row += "</tr>"
        body_rows += row

    return f"""
    <table class='peer-table'>
        <thead>{header}</thead>
        <tbody>{body_rows}</tbody>
    </table>
    """


# ── Main render function ──────────────────────────────────────────────────────

def render_results(
    ticker: str,
    metrics: dict,
    memo: str,
    dcf: dict = None,
    transcript: str = None,
    competitors: list = None,
):
    """Render the full results panel, tabbed into four sections."""
    rating = extract_rating(memo)

    # ── Page header ───────────────────────────────────────────────────────────
    col_title, col_badge = st.columns([4, 1])
    with col_title:
        st.markdown(
            f"## {ticker} &nbsp;·&nbsp; "
            f"<span style='color:#8b949e;font-size:1rem;font-weight:400;'>"
            f"FY {metrics['fiscal_year']}</span>",
            unsafe_allow_html=True,
        )
    with col_badge:
        st.markdown(
            f"<div style='text-align:right;margin-top:10px;'>{rating_badge(rating)}</div>",
            unsafe_allow_html=True,
        )

    # ── Top-line metric bar ────────────────────────────────────────────────────
    st.markdown("<p class='section-label'>Fundamental Metrics</p>", unsafe_allow_html=True)
    m = metrics
    c1, c2, c3, c4, c5 = st.columns(5)
    rev_delta = (
        f"{m['yoy_revenue_growth_pct']:+.2f}% YoY"
        if m["yoy_revenue_growth_pct"] is not None else None
    )
    c1.metric("Current Price",  _fmt_num(m["current_price"],          ".2f",  prefix="$"))
    c2.metric("P/E Ratio",      _fmt_num(m["pe_ratio"],               ".2f",  suffix="x"))
    c3.metric("Gross Margin",   _fmt_num(m["gross_margin_pct"],       ".2f",  suffix="%"))
    c4.metric("Debt / Equity",  _fmt_num(m["debt_to_equity"],         ".4f"))
    c5.metric("Revenue Growth", _fmt_num(m["yoy_revenue_growth_pct"], ".2f",  suffix="%"),
              delta=rev_delta, delta_color="normal")
    st.caption(
        f"Fiscal year ending {m['fiscal_year']}  ·  Source: Yahoo Finance / SEC EDGAR"
    )

    st.divider()

    # ── Four tabs ─────────────────────────────────────────────────────────────
    tab_overview, tab_valuation, tab_earnings, tab_peers = st.tabs([
        "📋  Overview",
        "💰  Valuation Model",
        "🎙  Earnings Insights",
        "🏆  Peer Comparison",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # TAB 1 — Overview: supporting figures + full memo
    # ════════════════════════════════════════════════════════════════════════
    with tab_overview:
        with st.expander("📂 Supporting Figures", expanded=False):
            d = m["_details"]
            st.table({
                "Item": [
                    "Diluted EPS",
                    f"Total Revenue ({m['fiscal_year'][:4]})",
                    f"Total Revenue ({d['prior_year'][:4]})",
                    "Gross Profit",
                    "Total Debt",
                    "Stockholders Equity",
                ],
                "Value": [
                    _fmt_num(d["diluted_eps"],            ".2f",  prefix="$"),
                    _fmt_num(d["total_revenue_current"],  ",.0f", prefix="$"),
                    _fmt_num(d["total_revenue_prior"],    ",.0f", prefix="$"),
                    _fmt_num(d["gross_profit"],           ",.0f", prefix="$"),
                    _fmt_num(d["total_debt"],             ",.0f", prefix="$"),
                    _fmt_num(d["stockholders_equity"],    ",.0f", prefix="$"),
                ],
            })

        st.markdown("<p class='section-label'>Investment Memo</p>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='memo-card'>{rating_badge(rating)}<br>{memo}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)
        st.download_button(
            label="⬇️  Download Memo as .txt",
            data=memo,
            file_name=f"{ticker}_investment_memo.txt",
            mime="text/plain",
            use_container_width=True,
        )

    # ════════════════════════════════════════════════════════════════════════
    # TAB 2 — Valuation Model: DCF hero + FCF chart + assumptions table
    # ════════════════════════════════════════════════════════════════════════
    with tab_valuation:
        if not dcf or not dcf.get("dcf_available", False):
            reason = (dcf or {}).get(
                "reason",
                "DCF Valuation Not Applicable (Insufficient FCF Data / Financial Institution).",
            )
            st.warning(f"⚠️ {reason}")
        else:
            mos      = dcf["margin_of_safety_pct"]  # may be None if IV ≤ 0
            iv       = dcf["intrinsic_value"]
            price    = dcf["current_price"]
            is_under = (mos is not None) and (mos > 0)
            price_cls = "hero-price-green" if is_under else "hero-price-red"
            pill_cls  = "hero-pill-green"  if is_under else "hero-pill-red"
            mos_label = (
                f"{'▲' if is_under else '▼'} {abs(mos):.1f}%  "
                f"{'UNDERVALUED' if is_under else 'OVERVALUED'}"
                if mos is not None else "Margin of Safety N/A"
            )

            # Hero card
            st.markdown(
                f"""
                <div class='hero-card'>
                    <div class='hero-label'>DCF Intrinsic Value — Price Target</div>
                    <div class='{price_cls}'>{_fmt_num(iv, ",.2f", prefix="$")}</div>
                    <div class='hero-vs'>vs. current market price</div>
                    <div class='hero-curr'>{_fmt_num(price, ",.2f", prefix="$")}</div>
                    <div class='{pill_cls}'>{mos_label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # DCF assumption metrics
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("WACC",             f"{dcf['wacc_pct']:.1f}%",
                      help="Weighted Average Cost of Capital used to discount future cash flows")
            d2.metric("Terminal Growth",  f"{dcf['terminal_growth_pct']:.1f}%",
                      help="Perpetual growth rate applied beyond the 5-year projection window")
            d3.metric("FCF Growth Used",  f"{dcf['capped_growth_rate_pct']:.1f}%",
                      help="3-year average FCF growth, capped at 10% to avoid overfitting")
            d4.metric("Margin of Safety", _fmt_num(mos, "+.1f", suffix="%"),
                      delta=_fmt_num(mos, "+.1f", suffix="%"), delta_color="normal")

            st.markdown("<br>", unsafe_allow_html=True)

            # FCF line chart
            st.markdown(
                "<p class='section-label'>Projected Free Cash Flow — Next 5 Years</p>",
                unsafe_allow_html=True,
            )
            years = [f"Year +{i + 1}" for i in range(len(dcf["projected_fcf"]))]
            fcf_df = pd.DataFrame(
                {
                    "Projected FCF ($B)":  [v / 1e9 for v in dcf["projected_fcf"]],
                    "Present Value ($B)":  [v / 1e9 for v in dcf["pv_projected_fcf"]],
                },
                index=years,
            )
            st.line_chart(fcf_df, use_container_width=True)
            st.caption(
                "Projected FCF grows at the capped historical rate.  "
                "Present Value is Projected FCF discounted at WACC.  "
                "The gap between lines widens as the discount effect compounds."
            )

            # Assumptions table
            with st.expander("📊 Full DCF Assumptions & Annual Projections", expanded=False):
                proj_table = {
                    "Year":           [f"Y+{y}" for y in range(1, len(dcf["projected_fcf"]) + 1)],
                    "Projected FCF":  [f"${v:,.0f}" for v in dcf["projected_fcf"]],
                    "Present Value":  [f"${v:,.0f}" for v in dcf["pv_projected_fcf"]],
                }
                st.table(proj_table)
                st.caption(
                    f"WACC: {dcf['wacc_pct']:.1f}%  ·  "
                    f"Terminal Growth: {dcf['terminal_growth_pct']:.1f}%  ·  "
                    f"PV Terminal Value: ${dcf['pv_terminal_value']:,.0f}  ·  "
                    f"Total PV of all cash flows: ${dcf['total_present_value']:,.0f}  ·  "
                    f"Shares outstanding: {dcf['shares_outstanding']:,.0f}"
                )

    # ════════════════════════════════════════════════════════════════════════
    # TAB 3 — Earnings Insights: structured bullet cards + full transcript
    # ════════════════════════════════════════════════════════════════════════
    with tab_earnings:
        if not transcript:
            st.markdown(
                "<div class='empty-state'>🎙 No earnings call transcript was available "
                "for this ticker. Try setting an FMP_API_KEY in your .env file, or re-run "
                "the analysis — the Gemini Search fallback will attempt to retrieve "
                "the latest call.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<p class='section-label'>Key Takeaways from the Most Recent Earnings Call</p>",
                unsafe_allow_html=True,
            )

            bullets = parse_transcript_bullets(transcript)
            for b in bullets:
                # Convert any markdown-style bullet lines to •
                body_html = re.sub(
                    r"(?m)^[-*]\s+(.+)$",
                    r"• \1",
                    b["body"],
                )
                # Preserve line breaks
                body_html = body_html.replace("\n", "<br>")
                st.markdown(
                    f"""
                    <div class='insight-card'>
                        <div class='insight-heading'>{b['heading']}</div>
                        {body_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            st.markdown("<br>", unsafe_allow_html=True)
            with st.expander("📄 View Full Transcript / Source Text", expanded=False):
                st.markdown(
                    f"<div style='color:#cdd9e5;font-size:0.88rem;"
                    f"line-height:1.7;white-space:pre-wrap;'>{transcript[:6000]}</div>",
                    unsafe_allow_html=True,
                )
                if len(transcript) > 6000:
                    st.caption(f"Showing first 6,000 of {len(transcript):,} total characters.")

    # ════════════════════════════════════════════════════════════════════════
    # TAB 4 — Peer Comparison: styled HTML table + quick metrics
    # ════════════════════════════════════════════════════════════════════════
    with tab_peers:
        valid_comps = [c for c in (competitors or []) if "metrics" in c]

        if not valid_comps:
            st.markdown(
                "<div class='empty-state'>🏆 Peer comparison data is unavailable.  "
                "This can happen when yfinance does not return an industryKey for the ticker, "
                "or when competitor financial data could not be fetched.</div>",
                unsafe_allow_html=True,
            )
        else:
            industry = valid_comps[0].get("industry", "")
            sector   = valid_comps[0].get("sector",   "")

            st.markdown(
                f"<p class='section-label'>"
                f"{ticker} vs. Top Peers &nbsp;·&nbsp; "
                f"<span style='font-weight:400;text-transform:none;letter-spacing:0;'>"
                f"{industry} &nbsp;({sector})</span></p>",
                unsafe_allow_html=True,
            )

            # Styled comparison table
            st.markdown(
                _peer_table_html(ticker, metrics, valid_comps),
                unsafe_allow_html=True,
            )
            st.caption(
                "▲ Green = best-in-class for that metric.  "
                "▼ Red = weakest.  "
                "P/E and D/E: lower is considered better.  "
                "Gross Margin and Revenue Growth: higher is better."
            )

            st.markdown("<br>", unsafe_allow_html=True)

            # Side-by-side metric cards per competitor
            st.markdown(
                "<p class='section-label'>Quick Snapshot</p>",
                unsafe_allow_html=True,
            )
            snap_cols = st.columns(len(valid_comps) + 1)

            def _snap_col(col, tkr, m_dict, is_target=False):
                label_color = "#58a6ff" if is_target else "#8b949e"
                col.markdown(
                    f"<p style='color:{label_color};font-weight:700;"
                    f"font-size:0.85rem;margin-bottom:4px;'>{tkr}</p>",
                    unsafe_allow_html=True,
                )
                col.metric("Price",      _fmt_num(m_dict.get("current_price"),          ".2f",  prefix="$"))
                col.metric("P/E",        _fmt_num(m_dict.get("pe_ratio"),               ".2f",  suffix="x"))
                col.metric("Gross Mgn",  _fmt_num(m_dict.get("gross_margin_pct"),       ".2f",  suffix="%"))
                col.metric("Rev Growth", _fmt_num(m_dict.get("yoy_revenue_growth_pct"), ".2f",  suffix="%"))

            _snap_col(snap_cols[0], ticker, metrics, is_target=True)
            for i, comp in enumerate(valid_comps):
                _snap_col(snap_cols[i + 1], comp["ticker"], comp["metrics"])


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 AI Wall Street Analyst")
    st.markdown(
        "<p style='color:#8b949e;font-size:0.85rem;'>Fundamental + qualitative "
        "analysis powered by SEC EDGAR & Gemini 2.5 Flash.</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    st.markdown("#### Enter Ticker Symbol")
    ticker_input = st.text_input(
        "Ticker",
        placeholder="e.g. AAPL, NVDA, TSLA",
        label_visibility="collapsed",
    )
    run_btn = st.button("🚀 Run Analysis", use_container_width=True, type="primary")

    # ── Search history ────────────────────────────────────────────────────────
    if st.session_state.history:
        st.divider()
        st.markdown(
            "<p style='color:#8b949e;font-size:0.75rem;font-weight:600;"
            "letter-spacing:0.08em;text-transform:uppercase;'>Recent Searches</p>",
            unsafe_allow_html=True,
        )
        RATING_ICON = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}
        for i, entry in enumerate(st.session_state.history):
            t      = entry["ticker"]
            rating = extract_rating(entry["memo"])
            icon   = RATING_ICON.get(rating, "⚪")
            label  = f"{icon}  {t}  {'◀' if t == st.session_state.ticker else ''}"
            if st.button(label, key=f"history_{i}", use_container_width=True):
                st.session_state.ticker      = entry["ticker"]
                st.session_state.metrics     = entry["metrics"]
                st.session_state.dcf         = entry.get("dcf")
                st.session_state.transcript  = entry.get("transcript")
                st.session_state.competitors = entry.get("competitors")
                st.session_state.memo        = entry["memo"]
                st.toast(f"Loaded **{t}** from history", icon="📂")
                st.rerun()

    st.divider()
    st.markdown(
        "<p style='color:#8b949e;font-size:0.78rem;'>"
        "Data sources: Yahoo Finance · SEC EDGAR · Gemini 2.5 Flash</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color:#555;font-size:0.72rem;'>Not financial advice. For research only.</p>",
        unsafe_allow_html=True,
    )


# ── Main area ─────────────────────────────────────────────────────────────────
st.markdown("# AI Wall Street Analyst Platform")
st.markdown(
    "<p style='color:#8b949e;margin-top:-12px;'>"
    "Institutional-grade investment memos, generated in seconds.</p>",
    unsafe_allow_html=True,
)
st.divider()

# ── Pipeline ──────────────────────────────────────────────────────────────────
if run_btn:
    if not ticker_input.strip():
        st.warning("Please enter a ticker symbol before clicking Run Analysis.")
    else:
        ticker = ticker_input.strip().upper()
        with st.spinner(f"Running full analysis on **{ticker}** — this takes 30–60 seconds..."):
            try:
                # Step 1 — financial data
                fetch_financials(ticker)

                # Step 2 — fundamental metrics
                metrics = calculate_metrics(ticker)

                # Step 3 — DCF (always returns a dict; never raises)
                dcf = calculate_dcf(ticker)

                # Step 4 — SEC 10-K risk factors
                risk_text = scrape_sec_filing(ticker, section="item1a")

                # Step 5 — earnings call transcript (non-fatal)
                transcript = None
                try:
                    transcript = get_earnings_transcript(ticker)
                except Exception as tr_err:
                    st.warning(f"Transcript skipped: {tr_err}")

                # Step 6 — competitor mini-analysis (non-fatal)
                competitors = None
                try:
                    comp_info = get_competitors(ticker)
                    sector    = comp_info["sector"]
                    industry  = comp_info["industry"]
                    comp_list = []
                    for c in comp_info["competitors"]:
                        try:
                            fetch_financials(c["ticker"])
                            c_metrics = calculate_metrics(c["ticker"])
                            comp_list.append({
                                "ticker":   c["ticker"],
                                "name":     c["name"],
                                "sector":   sector,
                                "industry": industry,
                                "metrics":  {
                                    "current_price":          c_metrics["current_price"],
                                    "pe_ratio":               c_metrics["pe_ratio"],
                                    "gross_margin_pct":       c_metrics["gross_margin_pct"],
                                    "yoy_revenue_growth_pct": c_metrics["yoy_revenue_growth_pct"],
                                    "debt_to_equity":         c_metrics["debt_to_equity"],
                                },
                            })
                        except Exception as ce:
                            comp_list.append({
                                "ticker": c["ticker"],
                                "name":   c["name"],
                                "error":  str(ce),
                            })
                    competitors = comp_list
                except Exception as comp_err:
                    st.warning(f"Competitor analysis skipped: {comp_err}")

                # Step 7 — LLM memo
                memo = run_analysis(
                    ticker, metrics, risk_text,
                    dcf=dcf, transcript=transcript,
                    competitors=competitors,
                )

                # Persist to session state
                st.session_state.ticker      = ticker
                st.session_state.metrics     = metrics
                st.session_state.dcf         = dcf
                st.session_state.transcript  = transcript
                st.session_state.competitors = competitors
                st.session_state.memo        = memo

                # Append to history (deduplicated, newest first)
                st.session_state.history = [
                    h for h in st.session_state.history if h["ticker"] != ticker
                ]
                st.session_state.history.insert(0, {
                    "ticker":      ticker,
                    "metrics":     metrics,
                    "dcf":         dcf,
                    "transcript":  transcript[:5000] if transcript else None,
                    "competitors": competitors,
                    "memo":        memo,
                })
                save_history(st.session_state.history)

            except Exception as e:
                st.error(f"**Analysis failed for `{ticker}`:** {e}")

# ── Display ───────────────────────────────────────────────────────────────────
if st.session_state.memo is not None:
    render_results(
        st.session_state.ticker,
        st.session_state.metrics,
        st.session_state.memo,
        dcf=st.session_state.dcf,
        transcript=st.session_state.transcript,
        competitors=st.session_state.competitors,
    )
else:
    st.markdown("""
    <div style='text-align:center;padding:80px 20px;'>
        <div style='font-size:3.5rem;'>📈</div>
        <div style='font-size:1.1rem;margin-top:16px;color:#6b7280;'>
            Enter a ticker in the sidebar and click
            <strong style='color:#8b949e;'>Run Analysis</strong> to generate your memo.
        </div>
        <div style='margin-top:12px;font-size:0.85rem;color:#4a5568;'>
            Pulls 5 years of financials &nbsp;·&nbsp; Scrapes latest SEC 10-K
            &nbsp;·&nbsp; Calculates DCF price target &nbsp;·&nbsp; Generates Buy / Hold / Sell thesis
        </div>
    </div>
    """, unsafe_allow_html=True)
