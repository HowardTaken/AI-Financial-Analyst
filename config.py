"""
config.py
---------
Central secret management for both local and Streamlit Cloud environments.

Resolution order for every key:
  1. st.secrets  — Streamlit Cloud (or local secrets.toml if present)
  2. os.environ  — populated by .env via python-dotenv when running locally

load_dotenv() is only called when a .env file is actually present on disk,
so it is silently skipped on Streamlit Cloud where no .env file is deployed.
"""

import os
from pathlib import Path

# ── Local development: load .env only when the file exists ───────────────────
if Path(".env").exists():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # python-dotenv not installed — safe to ignore on cloud


def get_secret(key: str, default: str = "") -> str:
    """
    Retrieve a secret by name, regardless of runtime environment.

    On Streamlit Cloud the value comes from st.secrets (configured in the
    app dashboard).  Locally it comes from the .env file loaded above.
    Falls back to `default` (empty string) if the key is not found anywhere.
    """
    # st.secrets works on Streamlit Cloud and also locally when a
    # .streamlit/secrets.toml file exists.  We wrap in a broad except so
    # that non-Streamlit runtimes (e.g. `python agent.py`) never crash here.
    try:
        import streamlit as st
        value = st.secrets.get(key)
        if value:
            return str(value)
    except Exception:
        pass

    return os.getenv(key, default)
