"""
Family financial constants — single source of truth for the entire application.
Public settings live here. Private data (names, income, accounts) lives in
config_private.py which is excluded from git.

On Streamlit Cloud, config_private.py is generated from st.secrets at startup.
"""

import os
from datetime import date

# ---------------------------------------------------------------------------
# Import all private data (names, income, accounts, expenses, objectives)
# Locally: reads from config_private.py on disk
# Streamlit Cloud: writes config_private.py from secrets, then imports
# ---------------------------------------------------------------------------
_config_dir = os.path.dirname(os.path.abspath(__file__))
_private_path = os.path.join(_config_dir, "config_private.py")

if not os.path.exists(_private_path):
    # On Streamlit Cloud: parse config_private from secrets entirely in-memory
    # (never write to disk — avoids exposing PII as a plaintext file in /tmp)
    try:
        import streamlit as st
        _content = st.secrets.get("config_private_py", "")
        if _content:
            import types, sys  # noqa: E401
            _mod = types.ModuleType("config_private")
            _mod.__file__ = "<config_private_from_secrets>"
            exec(compile(_content, "<config_private>", "exec"), _mod.__dict__)  # noqa: S102
            sys.modules["config_private"] = _mod
    except Exception as e:
        raise RuntimeError(f"Cannot load config_private: {e}")

from config_private import *  # noqa: F401, F403

# ---------------------------------------------------------------------------
# Backwards compatibility — Streamlit Cloud secrets may use old names
# ---------------------------------------------------------------------------
import sys as _sys
_this = _sys.modules[__name__]
if not hasattr(_this, "MONTHLY_EXPENSES") and hasattr(_this, "NON_DAYCARE_MONTHLY"):
    MONTHLY_EXPENSES = NON_DAYCARE_MONTHLY  # noqa: F405
if not hasattr(_this, "CC_MONTHLY_AVERAGE") and hasattr(_this, "CC_MONTHLY_AVERAGE_EXCL_DAYCARE"):
    CC_MONTHLY_AVERAGE = CC_MONTHLY_AVERAGE_EXCL_DAYCARE  # noqa: F405
if not hasattr(_this, "FAMILY_DISPLAY_NAME"):
    FAMILY_DISPLAY_NAME = "Family Budget"

# ---------------------------------------------------------------------------
# Computed values from private data
# ---------------------------------------------------------------------------
_CHECKING_SUBTOTAL = sum(FIXED_MONTHLY_EXPENSES.values())  # noqa: F405

# ---------------------------------------------------------------------------
# Expense categories for Claude to use
# ---------------------------------------------------------------------------
CATEGORIES = [
    "Housing & Utilities",
    "Daycare",
    "Groceries",
    "Costco",
    "Dining Out",
    "Transportation",
    "Gas",
    "Car Insurance",
    "Healthcare & Medical",
    "Kids & Baby",
    "Personal Care",
    "Clothing & Fashion",
    "Amazon",
    "Other Shopping",
    "Subscriptions & Streaming",
    "Phone & Internet",
    "Debt Payments",
    "Giving & Church",
    "Family Support",
    "Travel",
    "Education",
    "Entertainment",
    "Home Improvement",
    "Fees & Interest",
    "Transfers & Payments",
    "Income & Refunds",
    "Other",
]

# Categories to exclude from all analysis, charts, and cards
# These are internal movements, not actual spending
EXCLUDED_CATEGORIES = {
    "Transfers & Payments",
    "Transfers & Savings",
    "Credit Card Payments",
    "Income & Refunds",
    "Debt & Loan Payments",
    "Debt Payments",
}

# ---------------------------------------------------------------------------
# Claude API settings
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS_EXTRACTION = 8192
MAX_TOKENS_ADVISOR = 4096
MAX_TOKENS_FORECAST = 4096
MAX_TOKENS_REPORT = 4096

# ---------------------------------------------------------------------------
# App settings
# ---------------------------------------------------------------------------
APP_TITLE = "Family Budget Tracker"
DB_FILENAME = "expenses.db"
UPLOAD_DIR = "data/uploads"
