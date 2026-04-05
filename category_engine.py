"""
Dynamic category engine — Claude-driven categorization that adapts to spending patterns.
Replaces the static config.CATEGORIES list with a data-driven approach.

Usage:
    categories = get_active_categories(conn)  # Use everywhere instead of config.CATEGORIES
    generate_categories(conn, advisor)        # Claude proposes new category structure
    apply_recategorization(conn, mapping)     # Apply category changes to transactions
"""

import json
from typing import Optional

import config
import database


def get_active_categories(conn) -> list[str]:
    """
    Return the active category list. If dynamic categories have been defined
    in the category_definitions table, use those. Otherwise fall back to config.CATEGORIES.

    In both cases, also include any category that exists in transaction data
    but is missing from the list — prevents silently dropping real spending
    when Monarch Money introduces new category names.
    """
    from shared.filters import get_excluded_categories
    _excluded = get_excluded_categories(conn)

    definitions = database.get_category_definitions(conn)
    if definitions:
        cats = [d["name"] for d in definitions if d["name"] not in _excluded]
    else:
        cats = [c for c in config.CATEGORIES if c not in _excluded]

    # Include any transaction categories not yet in the list (e.g., new Monarch categories)
    db_cats = conn.execute(
        "SELECT DISTINCT category FROM transactions WHERE amount < 0"
    ).fetchall()
    known = set(cats) | _excluded
    for row in db_cats:
        if row["category"] not in known:
            cats.append(row["category"])

    return cats


def get_category_hierarchy(conn) -> dict:
    """Return categories with their parent relationships (for treemap/sunburst)."""
    definitions = database.get_category_definitions(conn)
    if not definitions:
        return {cat: {"parent": None, "description": ""} for cat in config.CATEGORIES}
    return {
        d["name"]: {"parent": d["parent"], "description": d["description"] or ""}
        for d in definitions
    }


def get_category_stats(conn) -> dict:
    """Get stats about how well categories cover the data."""
    total = conn.execute("SELECT COUNT(*) as c FROM transactions WHERE amount < 0").fetchone()["c"]
    other = conn.execute("SELECT COUNT(*) as c FROM transactions WHERE amount < 0 AND category = 'Other'").fetchone()["c"]
    low_conf = conn.execute("SELECT COUNT(*) as c FROM transactions WHERE amount < 0 AND confidence < 0.7").fetchone()["c"]

    return {
        "total_transactions": total,
        "other_count": other,
        "other_pct": round(other / max(total, 1) * 100, 1),
        "low_confidence_count": low_conf,
        "low_confidence_pct": round(low_conf / max(total, 1) * 100, 1),
        "coverage_pct": round((total - other) / max(total, 1) * 100, 1),
    }


def generate_categories(conn, advisor, user_guidance: str = "") -> dict:
    """
    Claude analyzes all transactions and proposes an optimal category structure.
    Returns a dict with proposed categories, subcategory tags, and a mapping.
    """
    # Get unique merchant → current category mappings with counts
    rows = conn.execute("""
        SELECT description, category, COUNT(*) as txn_count, SUM(amount) as total
        FROM transactions
        WHERE amount < 0
        GROUP BY description, category
        ORDER BY total ASC
        LIMIT 200
    """).fetchall()

    # Only send top 50 merchants (not 200) to keep response size manageable
    merchant_data = [
        {"merchant": r["description"], "category": r["category"],
         "txns": r["txn_count"], "spend": round(abs(r["total"]), 2)}
        for r in rows
    ][:50]

    # Get category size distribution
    cat_sizes = conn.execute("""
        SELECT category, COUNT(*) as txn_count, SUM(amount) as total
        FROM transactions WHERE amount < 0
        GROUP BY category ORDER BY total ASC
    """).fetchall()

    cat_summary = [
        {"category": r["category"], "txns": r["txn_count"],
         "spend": round(abs(r["total"]), 2)}
        for r in cat_sizes
    ]

    guidance_section = ""
    if user_guidance:
        guidance_section = f"""
USER INSTRUCTIONS (follow these closely):
{user_guidance}
"""

    prompt = f"""Analyze this family's spending categories and propose improvements.

CURRENT CATEGORIES ({len(cat_summary)} in use):
{json.dumps(cat_summary)}

TOP 50 MERCHANTS BY SPEND:
{json.dumps(merchant_data)}
{guidance_section}
Propose an optimal category structure. Rules:
- Keep 10-25 categories. Split large ones if needed, merge small ones.
- Include "Other" as catch-all.
- Do NOT include a merchant_mapping in your response (too large).
- Keep the JSON small and clean.
- Follow the user's instructions above if provided.

RESPOND WITH STRICT JSON ONLY (no markdown, no explanation outside JSON):
{{
    "proposed_categories": [
        {{"name": "Category Name", "parent": null, "description": "Brief description", "sort_order": 1}}
    ],
    "subcategory_tags": ["recurring", "essential", "impulse", "bulk", "kids", "personal"],
    "rename_mapping": {{"old_category_name": "new_category_name"}},
    "changes_summary": "What changed and why (2-3 sentences)"
}}"""

    messages = [{"role": "user", "content": prompt}]

    # Retry up to 3 times if JSON parsing fails
    last_error = None
    for attempt in range(3):
        try:
            response = advisor._call(
                system="You are a financial data analyst. Respond with valid JSON only.",
                messages=messages, max_tokens=2048, temperature=0.1,
            )
            return advisor._parse_json(response)
        except (ValueError, json.JSONDecodeError) as e:
            last_error = e

    raise ValueError(
        f"Claude returned invalid JSON after 3 attempts. "
        f"Try again. Error: {str(last_error)[:200]}"
    )


def apply_recategorization(conn, result: dict) -> dict:
    """Apply Claude's category proposals to the database.
    REPLACES all existing definitions (not additive)."""
    applied = {"categories_created": 0, "transactions_updated": 0}

    # Clear old definitions first — this is a full replacement
    conn.execute("DELETE FROM category_definitions")
    conn.commit()

    # Create new category definitions
    proposed = result.get("proposed_categories", [])
    for i, cat in enumerate(proposed):
        database.upsert_category_definition(
            conn, name=cat["name"], parent=cat.get("parent"),
            description=cat.get("description", ""),
            sort_order=cat.get("sort_order", i + 1),
        )
        applied["categories_created"] += 1

    # Apply category renames (old_name → new_name)
    rename_mapping = result.get("rename_mapping", {})
    for old_name, new_name in rename_mapping.items():
        if old_name != new_name:
            cur = conn.execute(
                "UPDATE transactions SET category = ? WHERE category = ?",
                (new_name, old_name),
            )
            applied["transactions_updated"] += cur.rowcount

    conn.commit()

    # Invalidate analytics cache
    import analytics_cache
    analytics_cache.invalidate(conn)

    return applied
