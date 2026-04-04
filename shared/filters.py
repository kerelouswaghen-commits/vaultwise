"""Centralized category filtering — single source of truth.

Category type logic uses BOTH:
- config.FIXED_MONTHLY_EXPENSES (curated fixed bills — highest priority)
- category_config DB table (fix/flex/exclude)
- config.EXCLUDED_CATEGORIES (transfers, CC payments)

If a category is in config.FIXED_MONTHLY_EXPENSES, it's ALWAYS fixed —
regardless of what the DB says. This prevents DB misclassification bugs.
"""

import config as _cfg
import database


def _get_config_fixed() -> set:
    """Categories that should ALWAYS be treated as fixed.

    Sources:
    1. config.FIXED_MONTHLY_EXPENSES keys (curated list)
    2. config.MONARCH_FIXED_MAP keys (Monarch categories mapped to fixed)
    3. config.CATEGORY_MERGES sources (categories merged into fixed ones)
    """
    result = set(getattr(_cfg, 'FIXED_MONTHLY_EXPENSES', {}).keys())
    # Monarch categories mapped to fixed bills
    result |= set(getattr(_cfg, 'MONARCH_FIXED_MAP', {}).keys())
    # Categories merged into other categories (e.g. "Education" merged into "Daycare")
    for _merge_sources in getattr(_cfg, 'CATEGORY_MERGES', {}).values():
        result |= set(_merge_sources)
    return result


def get_fixed_categories(conn) -> set:
    """Returns set of fixed category names: config + DB 'fix' type."""
    db_fixed = set(database.get_categories_by_type(conn, "fix"))
    return db_fixed | _get_config_fixed()


def get_excluded_categories(conn) -> set:
    """Returns set of category names tagged as 'exclude' in DB."""
    return set(database.get_categories_by_type(conn, "exclude"))


def get_flex_categories(conn) -> set:
    """Returns set of flex categories — everything that's NOT fixed and NOT excluded."""
    explicit_flex = set(database.get_categories_by_type(conn, "flex"))
    all_configured = {r["name"] for r in database.get_all_category_config(conn)}
    all_txn_cats = {r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM transactions"
    ).fetchall()}
    unconfigured = all_txn_cats - all_configured
    # Start with explicit flex + unconfigured
    flex = explicit_flex | unconfigured
    # Remove anything that's actually fixed (config is source of truth)
    flex -= _get_config_fixed()
    # Remove anything excluded
    flex -= get_excluded_categories(conn)
    return flex


def get_filtered_breakdown(conn, month_key: str) -> list[dict]:
    """Get monthly category breakdown — only fix + flex categories (excludes 'exclude' type).

    Auto-registers any unknown transaction categories as flex so they don't
    silently fall through the cracks.

    Returns list of dicts with keys: category, total, txn_count.
    """
    raw = database.get_monthly_category_breakdown(conn, month_key)
    excluded = get_excluded_categories(conn)
    # Auto-register orphan categories as flex
    all_configured = {r["name"] for r in database.get_all_category_config(conn)}
    for c in raw:
        if c["category"] not in all_configured:
            database.ensure_category_config(conn, c["category"], "flex")
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
