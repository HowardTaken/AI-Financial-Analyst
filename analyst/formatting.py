"""Presentation helpers shared by the web UI and CLI. No Streamlit imports, so they are testable."""

from __future__ import annotations

from html import escape

from .models import AnalysisResult, Memo, Metrics, Peer


def fmt_num(val, spec: str = "", prefix: str = "", suffix: str = "", na: str = "N/A") -> str:
    """Format a number, returning `na` for None so format specs never see a NoneType."""
    if val is None:
        return na
    return f"{prefix}{val:{spec}}{suffix}" if spec else f"{prefix}{val}{suffix}"


def memo_to_markdown(ticker: str, memo: Memo, warnings: list[str] | None = None) -> str:
    """Render a structured memo as Markdown (used for display and download)."""
    lines = [f"# {ticker}: {memo.rating} ({memo.confidence.title()} confidence)", "", f"**{memo.headline}**", ""]
    if memo.price_target is not None:
        lines += [f"**12-month price target:** ${memo.price_target:,.2f}", ""]
    lines += ["## Quantitative case", memo.quantitative_case, "",
              "## 10-K vs. earnings call", memo.filing_vs_call, ""]
    if memo.key_risks:
        lines += ["## Key risks", *[f"- {r}" for r in memo.key_risks], ""]
    if memo.catalysts:
        lines += ["## Catalysts", *[f"- {c}" for c in memo.catalysts], ""]
    lines += ["## Verdict", memo.verdict, ""]
    if memo.data_gaps:
        lines += ["## Data gaps", *[f"- {g}" for g in memo.data_gaps], ""]
    if warnings:
        lines += ["## Automated checks", *[f"- {w}" for w in warnings], ""]
    lines += ["*Educational research only; not financial advice.*"]
    return "\n".join(lines)


def result_to_markdown(result: AnalysisResult) -> str:
    return memo_to_markdown(result.ticker, result.memo, result.warnings)


# (label, Metrics attribute, suffix, higher_is_better, decimals)
PEER_ROWS = [
    ("Price", "current_price", "$", None, 2),
    ("P/E", "pe_ratio", "x", False, 1),
    ("Gross margin", "gross_margin_pct", "%", True, 1),
    ("Revenue growth", "yoy_revenue_growth_pct", "%", True, 1),
    ("Debt / equity", "debt_to_equity", "", False, 2),
    ("Price / book", "price_to_book", "x", False, 1),
    ("ROE", "roe_pct", "%", True, 1),
]


def _cell(value: float, suffix: str, decimals: int) -> str:
    if suffix == "$":
        return f"${value:,.{decimals}f}"
    if suffix == "%":
        return f"{value:+.{decimals}f}%"
    return f"{value:.{decimals}f}{suffix}"


def peer_table_html(target: Metrics, peers: list[Peer], medians: dict[str, float | None]) -> str:
    """HTML comparison table: target, each peer, and the peer median. Green = best, red = worst."""
    ok = [p for p in peers if p.metrics]
    columns = [(target.ticker, target)] + [(p.ticker, p.metrics) for p in ok]

    head = "<th style='text-align:left;'>Metric</th>"
    head += "".join(
        f"<th class='{'target-col' if i == 0 else ''}'>{escape(t)}</th>" for i, (t, _) in enumerate(columns)
    )
    head += "<th>Peer median</th>"

    body = ""
    for label, attr, suffix, higher_better, decimals in PEER_ROWS:
        vals = [getattr(m, attr) for _, m in columns]
        present = [v for v in vals if v is not None]
        best = worst = None
        if higher_better is not None and len(present) > 1:
            best, worst = (max(present), min(present)) if higher_better else (min(present), max(present))
        row = f"<td class='row-label'>{escape(label)}</td>"
        for i, v in enumerate(vals):
            cls = "target-col" if i == 0 else ""
            if v is None:
                row += f"<td class='{cls} cell-na'>n/a</td>"
                continue
            text = _cell(v, suffix, decimals)
            if best is not None and best != worst and v == best:
                cls, text = f"{cls} cell-best", "▲ " + text
            elif best is not None and best != worst and v == worst:
                cls, text = f"{cls} cell-worst", "▼ " + text
            row += f"<td class='{cls.strip()}'>{escape(text)}</td>"
        median = medians.get(attr)
        row += (f"<td>{escape(_cell(median, suffix, decimals))}</td>" if median is not None
                else "<td class='cell-na'>n/a</td>")
        body += f"<tr>{row}</tr>"
    return f"<table class='peer-table'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
