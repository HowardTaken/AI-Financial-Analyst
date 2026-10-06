"""
Central configuration and secret management.

Secret resolution order:
  1. st.secrets  (Streamlit Cloud, or a local .streamlit/secrets.toml)
  2. os.environ  (populated from .env by python-dotenv when running locally)
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(_env_file)
    except ImportError:
        pass  # python-dotenv is optional (not needed on Streamlit Cloud)


def get_secret(key: str, default: str = "") -> str:
    """Return a secret by name regardless of runtime environment."""
    try:
        import streamlit as st

        value = st.secrets.get(key)
        if value:
            return str(value)
    except Exception:  # non-Streamlit runtime or no secrets file
        pass
    return os.getenv(key, default)


def gemini_model() -> str:
    return get_secret("ANALYST_MODEL", "gemini-2.5-flash")


def gemini_api_key() -> str:
    key = get_secret("GEMINI_API_KEY")
    if not key or key == "your_api_key_here":
        raise OSError(
            "GEMINI_API_KEY is not set. Add it to .env (local) or the "
            "Streamlit Cloud Secrets dashboard."
        )
    return key


def sec_user_agent() -> str:
    """SEC EDGAR requires a descriptive User-Agent with a real contact address."""
    return get_secret("SEC_USER_AGENT", "AI-Market-Analyst research-project contact@example.com")


def persist_history() -> bool:
    """History is kept per-session unless explicitly persisted (never on a shared deploy)."""
    return get_secret("ANALYST_PERSIST_HISTORY", "0").lower() in ("1", "true", "yes")
