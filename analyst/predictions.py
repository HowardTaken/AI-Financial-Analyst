"""
Append-only log of every rating the agent issues, so it can be evaluated against what the stock
actually did afterwards (see analyst/evaluate.py). A genuine forward test: no look-ahead possible.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import DATA_DIR
from .models import AnalysisResult

PREDICTIONS_FILE = DATA_DIR / "predictions.jsonl"


def log_prediction(result: AnalysisResult, path: Path = PREDICTIONS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ticker": result.ticker,
        "timestamp": result.created_at,
        "price": result.metrics.current_price if result.metrics else None,
        "rating": result.memo.rating,
        "confidence": result.memo.confidence,
        "price_target": result.memo.price_target,
        "dcf_upside_pct": result.dcf.upside_pct if result.dcf and result.dcf.available else None,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_predictions(path: Path = PREDICTIONS_FILE) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
