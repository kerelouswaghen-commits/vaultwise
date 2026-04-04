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
    import types as _types, sys as _sys  # noqa: E401
    _content = ""
    try:
        import streamlit as st
        _content = st.secrets.get("config_private_py", "")
    except Exception:
        pass  # No secrets file at all — fall through to defaults

    if _content:
        try:
            _mod = _types.ModuleType("config_private")
            _mod.__file__ = "<config_private_from_secrets>"
            exec(compile(_content, "<config_private>", "exec"), _mod.__dict__)  # noqa: S102
            _sys.modules["config_private"] = _mod
        except Exception as _e:
            # Log the error but don't crash — fall through to defaults
            import logging as _logging
            _logging.error(f"config_private exec failed: {_e}")
            _content = ""  # force fallback
    if not _content:
        # No secret found — create minimal module with defaults
        _mod = _types.ModuleType("config_private")
        _mod.__file__ = "<config_private_defaults>"
        _mod.INCOME = {"combined_monthly_take_home": 0}
        _mod.FIXED_MONTHLY_EXPENSES = {}
        _mod.MONTHLY_EXPENSES = 0
        _mod.CC_MONTHLY_AVERAGE = 0
        _mod.OBJECTIVES = []
        _mod.ACCOUNTS = {}
        _mod.FAMILY = {}
        _mod.TELEGRAM_USERS = {}
        _mod.SAVINGS_LEVERS = []
        _mod.TOTAL_POTENTIAL_MONTHLY_SAVINGS = 0
        _sys.modules["config_private"] = _mod

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
if not hasattr(_this, "MONARCH_FIXED_MAP"):
    MONARCH_FIXED_MAP = {}
if not hasattr(_this, "INCOME_LABELS"):
    INCOME_LABELS = {}
if not hasattr(_this, "FIXED_BILL_GROUPS"):
    FIXED_BILL_GROUPS = {}
if not hasattr(_this, "MUTED_CATEGORIES"):
    MUTED_CATEGORIES = []
if not hasattr(_this, "CATEGORY_MERGES"):
    CATEGORY_MERGES = {}
if not hasattr(_this, "HIDE_ZERO_CATEGORIES"):
    HIDE_ZERO_CATEGORIES = True
if not hasattr(_this, "MERCHANT_CATEGORY_OVERRIDES"):
    MERCHANT_CATEGORY_OVERRIDES = {}
if not hasattr(_this, "APP_SUBTITLE"):
    APP_SUBTITLE = ""
if not hasattr(_this, "AUTO_RECATEGORIZE_DAYS"):
    AUTO_RECATEGORIZE_DAYS = 0
if not hasattr(_this, "EXPENSE_GROWTH_RATE"):
    EXPENSE_GROWTH_RATE = 0.03  # 3% annual inflation default
if not hasattr(_this, "FAMILY_ZELLE_NAMES"):
    FAMILY_ZELLE_NAMES = []
if not hasattr(_this, "FAMILY_MEMBER_NAMES"):
    FAMILY_MEMBER_NAMES = []
if not hasattr(_this, "EXTRACTION_CONTEXT"):
    EXTRACTION_CONTEXT = ""
if not hasattr(_this, "SAVINGS_LEVER_CONTEXT"):
    SAVINGS_LEVER_CONTEXT = ""
if not hasattr(_this, "FIXED_MONTHLY_EXPENSES"):
    FIXED_MONTHLY_EXPENSES = {}
if not hasattr(_this, "OBJECTIVES"):
    OBJECTIVES = []
if not hasattr(_this, "ACCOUNTS"):
    ACCOUNTS = {}
if not hasattr(_this, "FAMILY"):
    FAMILY = {}
if not hasattr(_this, "TELEGRAM_USERS"):
    TELEGRAM_USERS = {}
if not hasattr(_this, "SAVINGS_LEVERS"):
    SAVINGS_LEVERS = []
if not hasattr(_this, "TOTAL_POTENTIAL_MONTHLY_SAVINGS"):
    TOTAL_POTENTIAL_MONTHLY_SAVINGS = 0

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
    "Financial Transfers",
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
