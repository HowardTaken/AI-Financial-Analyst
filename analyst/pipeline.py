"""Single entry point used by both the Streamlit app and the CLI."""

from __future__ import annotations

import logging

from . import predictions
from .agent import EventCallback, run_agent
from .models import AnalysisResult

log = logging.getLogger(__name__)


def analyze(ticker: str, on_event: EventCallback | None = None, record_prediction: bool = True) -> AnalysisResult:
    """Run the agent for `ticker`; optionally log the rating for later forward-testing."""
    result = run_agent(ticker, on_event=on_event)
    if record_prediction:
        try:
            predictions.log_prediction(result)
        except OSError as exc:  # read-only filesystem on some hosts; never fail the analysis for this
            log.warning("Could not record prediction: %s", exc)
    return result
