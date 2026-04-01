"""Centralized category filtering — single source of truth.

All category type logic (fix/flex/exclude) is driven by the `category_config`
database table. No hardcoded category sets anywhere in the codebase.
"""

import database


def get_fixed_categories(conn) -> set:
    """Returns set of category names tagged as 'fix' in DB."""
    return set(database.get_categories_by_type(conn, "fix"))


def get_excluded_categories(conn) -> set:
    """Returns set of category names tagged as 'exclude' in DB."""
    return set(database.get_categories_by_type(conn, "exclude"))


def get_flex_categories(conn) -> set:
    """Returns set of category names tagged as 'flex' in DB."""
    return set(database.get_categories_by_type(conn, "flex"))


def get_filtered_breakdown(conn, month_key: str) -> list[dict]:
    """Get monthly category breakdown — only fix + flex categories (excludes 'exclude' type).

    Returns list of dicts with keys: category, total, txn_count.
    """
    raw = database.get_monthly_category_breakdown(conn, month_key)
    excluded = get_excluded_categories(conn)
    return [c for c in raw if c["category"] not in excluded]


def get_flex_breakdown(conn, month_key: str) -> list[dict]:
    """Get monthly category breakdown — only flex categories.

    Returns list of dicts with keys: category, total, txn_count.
    """
    raw = database.get_monthly_category_breakdown(conn, month_key)
    flex = get_flex_categories(conn)
    return [c for c in raw if c["category"] in flex]


def get_fixed_breakdown(conn, month_key: str) -> list[dict]:
    """Get monthly category breakdown — only fix categories.

    Returns list of dicts with keys: category, total, txn_count.
    """
    raw = database.get_monthly_category_breakdown(conn, month_key)
    fixed = get_fixed_categories(conn)
    return [c for c in raw if c["category"] in fixed]
