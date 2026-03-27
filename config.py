"""
Family financial constants — single source of truth for the entire application.
Public settings live here. Private data (names, income, accounts) lives in
config_private.py which is excluded from git.
"""

from datetime import date

# ---------------------------------------------------------------------------
# Import all private data (names, income, accounts, expenses, objectives)
# This file is NOT committed to git — see config_private.example.py for structure
# ---------------------------------------------------------------------------
from config_private import *  # noqa: F401, F403

# ---------------------------------------------------------------------------
# Computed values from private data
# ---------------------------------------------------------------------------
_CHECKING_SUBTOTAL = sum(FIXED_MONTHLY_EXPENSES.values())  # noqa: F405

# ---------------------------------------------------------------------------
# Daycare rate increase (generic, no personal info)
# ---------------------------------------------------------------------------
ANNUAL_RATE_INCREASE = 0.04  # 4 %

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
