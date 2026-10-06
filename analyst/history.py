"""Search history. Lives in the Streamlit session; optionally persisted to disk for local use."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .config import PROJECT_ROOT, persist_history
from .models import AnalysisResult

log = logging.getLogger(__name__)

HISTORY_FILE = PROJECT_ROOT / "history.json"
FORMAT_VERSION = 2
MAX_ENTRIES = 25


def load(path: Path = HISTORY_FILE) -> list[AnalysisResult]:
    """Load persisted history (empty unless persistence is enabled). Incompatible/corrupt files are ignored."""
    if not persist_history() or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != FORMAT_VERSION:
            return []
        return [AnalysisResult.from_dict(e) for e in payload["entries"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Ignoring unreadable history file: %s", exc)
        return []


def save(history: list[AnalysisResult], path: Path = HISTORY_FILE) -> None:
    """Atomically persist history (no-op unless persistence is enabled)."""
    if not persist_history():
        return
    payload = {"version": FORMAT_VERSION, "entries": [r.to_dict() for r in history[:MAX_ENTRIES]]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def add(history: list[AnalysisResult], result: AnalysisResult) -> list[AnalysisResult]:
    """New history with `result` first and any earlier run of the same ticker removed."""
    return [result] + [h for h in history if h.ticker != result.ticker][:MAX_ENTRIES - 1]
