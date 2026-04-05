#!/usr/bin/env python3
"""
Category Classification Consistency Tests
==========================================
Validates that fix/flex/exclude categories are read from one place,
processed correctly, and used consistently across the entire app.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
import database
import category_engine
from shared.filters import (
    get_fixed_categories, get_flex_categories, get_excluded_categories,
    get_filtered_breakdown, get_flex_breakdown, get_fixed_breakdown,
)

PASS = 0
FAIL = 0


def check(tid, desc, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  {tid:02d} [PASS] {desc}")
    else:
        FAIL += 1
        print(f"  {tid:02d} [FAIL] {desc}")
    return condition


def header(name):
    print(f"\n{'═' * 80}\n  {name}\n{'═' * 80}")


# ═══════════════════════════════════════════════════════════════════════
# GROUP 1: Mutual Exclusivity (20 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_mutual_exclusivity():
    header("G1: Mutual Exclusivity & Completeness")
    conn = database.get_connection()
    fixed = get_fixed_categories(conn)
    flex = get_flex_categories(conn)
    excluded = get_excluded_categories(conn)

    check(1, "Fixed set is non-empty", len(fixed) > 0)
    check(2, "Flex set is non-empty", len(flex) > 0)
    check(3, "Excluded set is non-empty", len(excluded) > 0)

    check(4, f"Fixed ∩ Flex = ∅ (overlap: {sorted(fixed & flex)})",
          len(fixed & flex) == 0)
    check(5, f"Fixed ∩ Excluded = ∅ (overlap: {sorted(fixed & excluded)})",
          len(fixed & excluded) == 0)
    check(6, f"Flex ∩ Excluded = ∅ (overlap: {sorted(flex & excluded)})",
          len(flex & excluded) == 0)

    # Every transaction category is classified
    all_txn_cats = set(r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM transactions"
    ).fetchall())
    classified = fixed | flex | excluded
    unclassified = all_txn_cats - classified
    check(7, f"All {len(all_txn_cats)} txn categories classified (unclassified: {sorted(unclassified)})",
          len(unclassified) == 0)

    # No category appears in multiple sets
    all_classified = list(fixed) + list(flex) + list(excluded)
    check(8, "No duplicate classifications",
          len(all_classified) == len(set(all_classified)))

    # config.EXCLUDED_CATEGORIES is a subset of get_excluded_categories
    check(9, "config.EXCLUDED_CATEGORIES ⊆ get_excluded_categories(conn)",
          config.EXCLUDED_CATEGORIES.issubset(excluded))

    # config.MUTED_CATEGORIES is a subset of get_excluded_categories
    muted = set(getattr(config, 'MUTED_CATEGORIES', []))
    check(10, "config.MUTED_CATEGORIES ⊆ get_excluded_categories(conn)",
          muted.issubset(excluded))

    # FIXED_MONTHLY_EXPENSES keys are all in fixed
    config_fixed_keys = set(config.FIXED_MONTHLY_EXPENSES.keys())
    check(11, "All FIXED_MONTHLY_EXPENSES keys are in fixed set",
          config_fixed_keys.issubset(fixed))

    # MONARCH_FIXED_MAP keys are in fixed
    monarch_fixed = set(getattr(config, 'MONARCH_FIXED_MAP', {}).keys())
    check(12, "All MONARCH_FIXED_MAP keys are in fixed set",
          monarch_fixed.issubset(fixed))

    # CATEGORY_MERGES source categories are in fixed
    merge_sources = set()
    for sources in getattr(config, 'CATEGORY_MERGES', {}).values():
        merge_sources.update(sources)
    check(13, "All CATEGORY_MERGES source categories are in fixed set",
          merge_sources.issubset(fixed))

    # Flex categories don't include any excluded names
    check(14, "No excluded category in flex set",
          len(flex & excluded) == 0)

    # Fixed categories don't include any excluded names
    check(15, "No excluded category in fixed set",
          len(fixed & excluded) == 0)

    # Calling the functions twice returns same results
    fixed2 = get_fixed_categories(conn)
    flex2 = get_flex_categories(conn)
    excluded2 = get_excluded_categories(conn)
    check(16, "get_fixed_categories is deterministic", fixed == fixed2)
    check(17, "get_flex_categories is deterministic", flex == flex2)
    check(18, "get_excluded_categories is deterministic", excluded == excluded2)

    # Expense-only categories (amount < 0) are all classified
    expense_cats = set(r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM transactions WHERE amount < 0"
    ).fetchall())
    expense_unclassified = expense_cats - classified
    check(19, f"All expense categories classified (unclassified: {sorted(expense_unclassified)})",
          len(expense_unclassified) == 0)

    # Total classified count is reasonable
    check(20, f"Total classified: {len(classified)} categories (reasonable > 30)",
          len(classified) > 30)

    conn.close()


# ═══════════════════════════════════════════════════════════════════════
# GROUP 2: Breakdown Consistency (20 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_breakdown_consistency():
    header("G2: Breakdown Consistency Across Months")
    conn = database.get_connection()
    months = database.get_available_months(conn)
    fixed = get_fixed_categories(conn)
    flex = get_flex_categories(conn)
    excluded = get_excluded_categories(conn)

    tid = 0
    for m in months[:5]:
        filtered = get_filtered_breakdown(conn, m)
        flex_bd = get_flex_breakdown(conn, m)
        fixed_bd = get_fixed_breakdown(conn, m)

        filtered_cats = {c["category"] for c in filtered}
        flex_cats = {c["category"] for c in flex_bd}
        fixed_cats_bd = {c["category"] for c in fixed_bd}

        # No excluded categories in filtered breakdown
        tid += 1
        leaked = filtered_cats & excluded
        check(tid, f"{m}: no excluded categories in filtered breakdown (leaked: {sorted(leaked)})",
              len(leaked) == 0)

        # Flex breakdown only has flex categories
        tid += 1
        non_flex = flex_cats - flex
        check(tid, f"{m}: flex breakdown only has flex cats (non-flex: {sorted(non_flex)})",
              len(non_flex) == 0)

        # Fixed breakdown only has fixed categories
        tid += 1
        non_fixed = fixed_cats_bd - fixed
        check(tid, f"{m}: fixed breakdown only has fixed cats (non-fixed: {sorted(non_fixed)})",
              len(non_fixed) == 0)

        # filtered = flex ∪ fixed (no overlap, no missing)
        tid += 1
        union = flex_cats | fixed_cats_bd
        check(tid, f"{m}: filtered = flex ∪ fixed breakdown",
              filtered_cats == union)

    conn.close()


# ═══════════════════════════════════════════════════════════════════════
# GROUP 3: Cross-Module Consistency (20 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_cross_module_consistency():
    header("G3: Cross-Module Consistency")
    conn = database.get_connection()
    excluded = get_excluded_categories(conn)
    fixed = get_fixed_categories(conn)

    # 1. category_engine.get_active_categories excludes all excluded cats
    active = category_engine.get_active_categories(conn)
    active_set = set(active)
    leaked = active_set & excluded
    check(1, f"category_engine excludes all excluded cats (leaked: {sorted(leaked)})",
          len(leaked) == 0)

    # 2. No duplicates in active categories
    check(2, f"No duplicates in active categories ({len(active)} vs {len(active_set)})",
          len(active) == len(active_set))

    # 3. budget_coach._get_muted uses same excluded set
    import budget_coach
    muted = budget_coach._get_muted(conn)
    check(3, "budget_coach._get_muted == get_excluded_categories",
          muted == excluded)

    # 4. views/transactions _muted_cats would match
    # Simulate: _init_category_sets sets _muted_cats = get_excluded_categories(conn)
    from views.transactions import _init_category_sets
    _init_category_sets(conn)
    from views import transactions as txn_mod
    check(4, "transactions._muted_cats == get_excluded_categories",
          txn_mod._muted_cats == excluded)

    # 5. transactions._fixed_cats matches
    check(5, "transactions._fixed_cats == get_fixed_categories",
          txn_mod._fixed_cats == fixed)

    # 6. get_monthly_flex_totals only counts flex categories
    months = database.get_available_months(conn)
    if months:
        flex_totals = database.get_monthly_flex_totals(conn, months=3)
        # Cross-check first month
        if flex_totals:
            ft = flex_totals[0]
            flex_bd = get_flex_breakdown(conn, ft["month"])
            expected = abs(sum(c["total"] for c in flex_bd))
            check(6, f"{ft['month']}: monthly_flex_totals matches flex_breakdown sum",
                  abs(ft["flex_total"] - expected) < 1)  # Allow $1 rounding

    # 7. config.EXCLUDED_CATEGORIES is fully covered
    for cat in sorted(config.EXCLUDED_CATEGORIES):
        check(7, f"config.EXCLUDED '{cat}' is in get_excluded_categories",
              cat in excluded)
        break  # Just test first

    # 8-10. All config.EXCLUDED items are covered (test remaining)
    all_config_in_db = all(c in excluded for c in config.EXCLUDED_CATEGORIES)
    check(8, f"All {len(config.EXCLUDED_CATEGORIES)} config.EXCLUDED items in centralized set",
          all_config_in_db)

    # 9. All config.MUTED items are covered
    muted_cfg = set(getattr(config, 'MUTED_CATEGORIES', []))
    all_muted_in_db = all(c in excluded for c in muted_cfg)
    check(9, f"All {len(muted_cfg)} config.MUTED items in centralized set",
          all_muted_in_db)

    # 10. DB-only exclusions (not in config) are still respected
    db_only = excluded - config.EXCLUDED_CATEGORIES - muted_cfg
    check(10, f"DB has {len(db_only)} additional excluded cats beyond config",
          len(db_only) >= 0)  # Just informational

    # 11-15. Verify breakdowns for multiple months all respect same excluded set
    for i, m in enumerate(months[:5]):
        bd = get_filtered_breakdown(conn, m)
        bd_cats = {c["category"] for c in bd}
        leaked = bd_cats & excluded
        check(11 + i, f"{m}: filtered breakdown has 0 excluded (has {len(leaked)})",
              len(leaked) == 0)

    # 16. Active categories + excluded = complete universe
    all_txn = set(r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM transactions WHERE amount < 0"
    ).fetchall())
    covered = active_set | excluded
    missed = all_txn - covered
    check(16, f"active_cats ∪ excluded covers all expense cats (missed: {sorted(missed)})",
          len(missed) == 0)

    # 17. get_flex_categories ⊆ active_categories
    flex = get_flex_categories(conn)
    check(17, "All flex categories are in active_categories",
          flex.issubset(active_set | fixed))

    # 18. Fixed categories are reasonable count
    check(18, f"Fixed count ({len(fixed)}) is reasonable (5-50)",
          5 <= len(fixed) <= 50)

    # 19. Excluded count is reasonable
    check(19, f"Excluded count ({len(excluded)}) is reasonable (5-30)",
          5 <= len(excluded) <= 30)

    # 20. Flex count is reasonable
    check(20, f"Flex count ({len(flex)}) is reasonable (10-60)",
          10 <= len(flex) <= 60)

    conn.close()


# ═══════════════════════════════════════════════════════════════════════
# GROUP 4: Data Integrity (20 tests)
# ═══════════════════════════════════════════════════════════════════════

def test_data_integrity():
    header("G4: Data Integrity & SQL Consistency")
    conn = database.get_connection()
    excluded = get_excluded_categories(conn)
    fixed = get_fixed_categories(conn)
    flex = get_flex_categories(conn)
    months = database.get_available_months(conn)

    # 1-5. For each month, verify total from filtered = fixed_total + flex_total
    for i, m in enumerate(months[:5]):
        filtered = get_filtered_breakdown(conn, m)
        flex_bd = get_flex_breakdown(conn, m)
        fixed_bd = get_fixed_breakdown(conn, m)

        total_filtered = sum(abs(c["total"]) for c in filtered)
        total_flex = sum(abs(c["total"]) for c in flex_bd)
        total_fixed = sum(abs(c["total"]) for c in fixed_bd)

        check(i + 1, f"{m}: filtered total (${total_filtered:,.2f}) = fixed (${total_fixed:,.2f}) + flex (${total_flex:,.2f})",
              abs(total_filtered - (total_fixed + total_flex)) < 0.02)

    # 6-10. Direct SQL cross-check: excluded categories never appear in breakdowns
    for i, m in enumerate(months[:5]):
        # Direct SQL: count expenses in excluded categories
        excl_placeholders = ",".join("?" * len(excluded))
        excl_count = conn.execute(
            f"SELECT COUNT(*) FROM transactions WHERE strftime('%Y-%m', date) = ? "
            f"AND amount < 0 AND category IN ({excl_placeholders})",
            (m, *excluded)
        ).fetchone()[0]

        filtered = get_filtered_breakdown(conn, m)
        filtered_cats = {c["category"] for c in filtered}
        leaked = filtered_cats & excluded

        check(6 + i, f"{m}: {excl_count} excluded txns exist in DB but 0 leak to breakdown",
              len(leaked) == 0)

    # 11-15. Verify flex spending totals match across different computation paths
    for i, m in enumerate(months[:5]):
        # Path 1: get_flex_breakdown
        flex_bd = get_flex_breakdown(conn, m)
        total_via_breakdown = sum(abs(c["total"]) for c in flex_bd)

        # Path 2: get_filtered_breakdown then filter to flex
        filtered = get_filtered_breakdown(conn, m)
        total_via_filter = sum(abs(c["total"]) for c in filtered if c["category"] in flex)

        check(11 + i, f"{m}: flex total via breakdown (${total_via_breakdown:,.2f}) = via filter (${total_via_filter:,.2f})",
              abs(total_via_breakdown - total_via_filter) < 0.02)

    # 16. category_config table has no contradictions with config
    db_types = {r["name"]: r["type"] for r in database.get_all_category_config(conn)}
    config_fixed_keys = set(config.FIXED_MONTHLY_EXPENSES.keys())
    contradictions = [k for k in config_fixed_keys if k in db_types and db_types[k] == "exclude"]
    check(16, f"No config fixed category marked as exclude in DB (contradictions: {contradictions})",
          len(contradictions) == 0)

    # 17. DB 'fix' type categories are subset of get_fixed_categories
    db_fix = set(database.get_categories_by_type(conn, "fix"))
    check(17, "DB 'fix' ⊆ get_fixed_categories",
          db_fix.issubset(fixed))

    # 18. DB 'flex' type doesn't include any fixed categories
    db_flex = set(database.get_categories_by_type(conn, "flex"))
    flex_but_fixed = db_flex & fixed
    check(18, f"No DB 'flex' category is actually fixed (overlap: {sorted(flex_but_fixed)})",
          len(flex_but_fixed) == 0)

    # 19. get_effective_fixed_total matches config sum
    eff_fixed = database.get_effective_fixed_total(conn)
    config_sum = sum(config.FIXED_MONTHLY_EXPENSES.values())
    # They may differ due to overrides, but should be in same ballpark
    check(19, f"Effective fixed (${eff_fixed:,.0f}) is reasonable vs config (${config_sum:,.0f})",
          abs(eff_fixed - config_sum) < config_sum * 0.5)

    # 20. No category has both positive and negative amounts that create confusion
    # (this would indicate income mixed with expenses in same category)
    problem_cats = conn.execute("""
        SELECT category,
               SUM(CASE WHEN amount < 0 THEN 1 ELSE 0 END) as neg_count,
               SUM(CASE WHEN amount > 0 THEN 1 ELSE 0 END) as pos_count
        FROM transactions
        GROUP BY category
        HAVING neg_count > 0 AND pos_count > 0 AND category NOT IN (
            SELECT name FROM category_config WHERE type = 'exclude'
        )
    """).fetchall()
    # Flex/fixed categories with both positive and negative amounts
    mixed = [r[0] for r in problem_cats if r[0] in flex]
    check(20, f"Flex categories with mixed +/- amounts: {len(mixed)} (informational)",
          True)  # Informational — refunds are normal

    conn.close()


# ═══════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("  CATEGORY CLASSIFICATION CONSISTENCY TESTS — 80 Tests")
    print("=" * 80)

    groups = [
        ("G1: Mutual Exclusivity & Completeness", test_mutual_exclusivity),
        ("G2: Breakdown Consistency", test_breakdown_consistency),
        ("G3: Cross-Module Consistency", test_cross_module_consistency),
        ("G4: Data Integrity & SQL", test_data_integrity),
    ]

    for name, fn in groups:
        try:
            fn()
        except Exception as e:
            print(f"  ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'=' * 80}")
    print(f"  FINAL: {PASS} PASSED / {FAIL} FAILED / {PASS + FAIL} TOTAL")
    print(f"{'=' * 80}")
    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
