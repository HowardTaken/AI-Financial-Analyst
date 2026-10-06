"""Deterministic checks on the LLM's memo against the numbers the tools actually produced."""

from __future__ import annotations

from .models import AnalysisContext, Memo

DCF_CONFLICT_PCT = 25.0   # rating contradicts DCF by more than this much upside/downside
MAX_WORDS = 700


def check_memo(memo: Memo, ctx: AnalysisContext) -> list[str]:
    """Return human-readable warnings; an empty list means nothing looked off."""
    warnings: list[str] = []
    price = ctx.metrics.current_price if ctx.metrics else None
    dcf = ctx.dcf

    if ctx.metrics is None:
        warnings.append("The memo was submitted without fetching fundamentals; numbers are unverified.")

    if dcf and dcf.available and dcf.upside_pct is not None:
        if memo.rating == "BUY" and dcf.upside_pct < -DCF_CONFLICT_PCT:
            warnings.append(f"Rating is BUY but the base-case DCF implies {dcf.upside_pct:+.0f}% downside.")
        if memo.rating == "SELL" and dcf.upside_pct > DCF_CONFLICT_PCT:
            warnings.append(f"Rating is SELL but the base-case DCF implies {dcf.upside_pct:+.0f}% upside.")

    if memo.price_target is not None and price:
        ratio = memo.price_target / price
        if not 0.4 <= ratio <= 2.5:
            warnings.append(f"Price target ${memo.price_target:,.2f} is {ratio:.1f}x the current price; check it.")
        if memo.rating == "BUY" and ratio < 1:
            warnings.append("Rating is BUY but the price target is below the current price.")
        if memo.rating == "SELL" and ratio > 1:
            warnings.append("Rating is SELL but the price target is above the current price.")

    if ctx.filing is None:
        warnings.append("No 10-K risk factors were retrieved; the filing-vs-call comparison is incomplete.")
    if ctx.earnings is None:
        warnings.append("No earnings-call summary was retrieved.")
    elif not ctx.earnings.is_grounded:
        warnings.append("The earnings-call summary has no cited web sources and should be treated as unverified.")

    if memo.word_count() > MAX_WORDS:
        warnings.append(f"Memo is {memo.word_count()} words, well over the ~400-word target.")
    return warnings
