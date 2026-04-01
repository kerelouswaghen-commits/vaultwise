"""Centralized category filtering — single source of truth."""

import config
import category_engine
import database


def get_fixed_categories() -> set:
    """Single source of truth for fixed (non-discretionary) transaction categories.

    Used by both the dashboard (home.py) and the Telegram report (reports.py)
    to ensure identical fixed vs flex classification.
    """
    cats = {"Housing & Utilities", "Debt Payments", "Family Support",
            "Transportation", "Phone & Internet", "Car Insurance"}
    cats.update(getattr(config, 'MONARCH_FIXED_MAP', {}).keys())
    return cats


def get_filtered_breakdown(conn, month_key: str) -> list[dict]:
    """Get monthly category breakdown with muted/merged/excluded filtering applied.

    Returns list of dicts with keys: category, total, txn_count.
    Uses the same logic as views/home.py to ensure consistency.
    """
    raw = database.get_monthly_category_breakdown(conn, month_key)
    active = category_engine.get_active_categories(conn)
    cats = [c for c in raw if c["category"] in active
            and c["category"] not in config.EXCLUDED_CATEGORIES]

    muted = set(getattr(config, 'MUTED_CATEGORIES', []))
    merges = getattr(config, 'CATEGORY_MERGES', {})
    merge_sources = set()

    for target, sources in merges.items():
        merge_sources.update(sources)
        target_entry = next((c for c in cats if c["category"] == target), None)
        for src in sources:
            src_entry = next((c for c in cats if c["category"] == src), None)
            if src_entry:
                if target_entry:
                    target_entry["total"] += src_entry["total"]
                    target_entry["txn_count"] += src_entry["txn_count"]
                else:
                    # Target doesn't exist yet — rename the source entry
                    src_entry["category"] = target
                    target_entry = src_entry
                    merge_sources.discard(src)  # keep it since it became the target

    return [c for c in cats
            if c["category"] not in muted
            and c["category"] not in merge_sources]
