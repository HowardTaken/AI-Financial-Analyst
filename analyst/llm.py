"""Thin Gemini wrapper: one client, retry with exponential backoff on transient errors."""

from __future__ import annotations

import logging
import time
from functools import lru_cache

from google import genai
from google.genai import errors, types

from .config import gemini_api_key, gemini_model

log = logging.getLogger(__name__)

RETRYABLE_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(api_key=gemini_api_key())


def generate(contents, config: types.GenerateContentConfig, model: str | None = None) -> types.GenerateContentResponse:
    """generate_content with retries on rate limits and 5xx errors (2s, 4s, 8s backoff)."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _client().models.generate_content(model=model or gemini_model(), contents=contents, config=config)
        except errors.APIError as exc:
            if getattr(exc, "code", None) not in RETRYABLE_CODES or attempt == MAX_ATTEMPTS:
                raise
            delay = 2 ** attempt
            log.warning("Gemini error %s; retry %d/%d in %ds", exc.code, attempt, MAX_ATTEMPTS - 1, delay)
            time.sleep(delay)
    raise AssertionError("unreachable")
