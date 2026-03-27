"""Shared session state, connection helpers, and utility functions."""

import os
import re
import uuid
from datetime import date

import streamlit as st

import config
import database
from claude_advisor import ClaudeAdvisor

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", config.DB_FILENAME)


def init_session():
    """Initialize session state defaults (call once from app.py)."""
    for key, default in [("advisor", None), ("session_id", str(uuid.uuid4())[:8]), ("chat_history", [])]:
        if key not in st.session_state:
            st.session_state[key] = default


def load_persisted_config():
    """Load income/expense config overrides from the database."""
    import json
    conn = database.get_connection(DB_PATH)
    saved_income = database.get_setting(conn, "income_config")
    if saved_income:
        try:
            config.INCOME.update(json.loads(saved_income))
        except (ValueError, TypeError):
            pass
    saved_expenses = database.get_setting(conn, "fixed_expenses_config")
    if saved_expenses:
        try:
            config.FIXED_MONTHLY_EXPENSES.update(json.loads(saved_expenses))
        except (ValueError, TypeError):
            pass
    # Seed default objectives
    database.seed_default_objectives(conn)
    conn.close()


def monarch_auto_sync():
    """Auto-sync Monarch Money on first app load per session."""
    if "monarch_synced" not in st.session_state:
        st.session_state.monarch_synced = False
    if not st.session_state.monarch_synced:
        conn = database.get_connection(DB_PATH)
        enabled = database.get_setting(conn, "monarch_enabled", "0")
        if enabled == "1":
            try:
                import monarch_sync
                result = monarch_sync.sync_transactions(conn)
                if result["new"] > 0:
                    st.toast(f"Monarch: {result['new']} new transactions synced")
                if result["errors"]:
                    st.toast(f"Monarch: {result['errors'][0]}", icon="⚠️")
            except Exception as e:
                st.toast(f"Monarch sync: {str(e)[:60]}", icon="⚠️")
        conn.close()
        st.session_state.monarch_synced = True


def get_advisor() -> ClaudeAdvisor | None:
    if st.session_state.advisor is not None:
        return st.session_state.advisor
    conn = database.get_connection(DB_PATH)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "") or database.get_setting(conn, "anthropic_api_key")
    conn.close()
    if not api_key:
        return None
    try:
        st.session_state.advisor = ClaudeAdvisor(api_key=api_key)
        return st.session_state.advisor
    except Exception:
        return None


def get_conn():
    return database.get_connection(DB_PATH)


def escape_dollars(text: str) -> str:
    """Escape ALL dollar signs so Streamlit never renders LaTeX."""
    if not text:
        return text
    return text.replace("$", "\\$")


def normalize_date(d: str, year_hint: str = "") -> str:
    """Ensure dates are YYYY-MM-DD format."""
    if not d or d == "unknown":
        return d
    d = d.strip()
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        return d
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", d)
    if m:
        return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2})", d)
    if m:
        yr = int(m.group(3))
        year = 2000 + yr if yr < 50 else 1900 + yr
        return f"{year}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    m = re.match(r"(\d{1,2})/(\d{1,2})$", d)
    if m:
        yr = year_hint or str(date.today().year)
        return f"{yr}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    return d


def normalize_transactions(transactions: list, year_hint: str = "") -> list:
    """Normalize all dates in a transaction list to YYYY-MM-DD."""
    for txn in transactions:
        if "date" in txn:
            txn["date"] = normalize_date(txn["date"], year_hint)
    return transactions
