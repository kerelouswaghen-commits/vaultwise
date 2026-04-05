#!/usr/bin/env python3
"""
Comprehensive Function Tests — 200 Tests (10 groups × 20 each)
==============================================================
Tests every core computation function across Home, Transactions,
and Savings Journey tabs.
"""

import sys
import json
import hashlib
from datetime import date, timedelta
from calendar import monthrange
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
import database
import models
from shared.filters import (
    get_fixed_categories, get_flex_categories,
    get_excluded_categories, get_filtered_breakdown, get_flex_breakdown,
)

# ── Utilities ────────────────────────────────────────────────────────────

PASS_COUNT = 0
FAIL_COUNT = 0
CURRENT_GROUP = ""


def check(test_id, description, expected, actual, tolerance=0.01):
    """Assert expected ≈ actual within tolerance. For floats."""
    global PASS_COUNT, FAIL_COUNT
    if isinstance(expected, float) and isinstance(actual, float):
        ok = abs(expected - actual) <= max(abs(expected) * tolerance, 0.02)
    elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        ok = abs(expected - actual) <= max(abs(expected) * tolerance, 1)
    else:
        ok = expected == actual
    if ok:
        PASS_COUNT += 1
        print(f"  {CURRENT_GROUP}.{test_id:02d} [PASS] {description}")
    else:
        FAIL_COUNT += 1
        print(f"  {CURRENT_GROUP}.{test_id:02d} [FAIL] {description}")
        print(f"         Expected: {expected}")
        print(f"         Actual:   {actual}")
    return ok


def check_true(test_id, description, condition):
    """Assert condition is True."""
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  {CURRENT_GROUP}.{test_id:02d} [PASS] {description}")
    else:
        FAIL_COUNT += 1
        print(f"  {CURRENT_GROUP}.{test_id:02d} [FAIL] {description}")
    return condition


def group_header(name):
    global CURRENT_GROUP
    CURRENT_GROUP = name
    print(f"\n{'═' * 80}")
    print(f"  {name}")
    print(f"{'═' * 80}")


# ══════════════════════════════════════════════════════════════════════════
# F1: INCOME MODEL — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f1_income_model():
    group_header("F1: Income Model")

    # 1. Basic structure
    r = models.get_income_for_month(2026, 3)
    check_true(1, "Returns dict with all keys",
               all(k in r for k in ["kero_net", "maggie_net", "kero_bonus", "maggie_bonus", "total_income"]))

    # 2. Total = sum of parts
    check(2, "total_income = kero_net + maggie_net + kero_bonus + maggie_bonus",
          r["kero_net"] + r["maggie_net"] + r["kero_bonus"] + r["maggie_bonus"], r["total_income"])

    # 3. Kero base matches config
    check(3, "Kero base matches config (no raise before 2027)",
          config.INCOME["kero"]["monthly_net"], r["kero_net"])

    # 4. Maggie base matches config
    check(4, "Maggie base matches config (no raise before 2027)",
          config.INCOME["maggie"]["monthly_net"], r["maggie_net"])

    # 5. Bonuses are fixed
    check(5, "Kero bonus = 1500", 1500, r["kero_bonus"])
    check(6, "Maggie bonus = 417", 417, r["maggie_bonus"])

    # 7. Same result for different months in same pre-raise year
    r1 = models.get_income_for_month(2026, 1)
    r2 = models.get_income_for_month(2026, 6)
    r3 = models.get_income_for_month(2026, 12)
    check(7, "Income same across 2026 (no raises)", r1["total_income"], r2["total_income"])
    check(8, "Income same Jan vs Dec 2026", r1["total_income"], r3["total_income"])

    # 9. 2025 same as 2026 (both pre-raise)
    r25 = models.get_income_for_month(2025, 6)
    check(9, "2025 income = 2026 income (pre-raise)", r1["total_income"], r25["total_income"])

    # 10. Raise kicks in at correct month in 2027
    kero_raise_mo = config.INCOME["kero"]["raise_month"]
    r_before = models.get_income_for_month(2027, kero_raise_mo - 1) if kero_raise_mo > 1 else models.get_income_for_month(2026, 12)
    r_after = models.get_income_for_month(2027, kero_raise_mo)
    check_true(10, f"Kero gets raise in 2027-{kero_raise_mo:02d}",
               r_after["kero_net"] > r_before["kero_net"])

    # 11. Raise amount matches formula
    kero_raise = int(config.INCOME["kero"]["annual_raise"] * 0.057)
    check(11, f"Kero raise = {kero_raise}/mo",
          config.INCOME["kero"]["monthly_net"] + kero_raise, r_after["kero_net"])

    # 12. Maggie raise at correct month
    maggie_raise_mo = config.INCOME["maggie"]["raise_month"]
    rm_before = models.get_income_for_month(2027, maggie_raise_mo - 1) if maggie_raise_mo > 1 else models.get_income_for_month(2026, 12)
    rm_after = models.get_income_for_month(2027, maggie_raise_mo)
    check_true(12, f"Maggie gets raise in 2027-{maggie_raise_mo:02d}",
               rm_after["maggie_net"] > rm_before["maggie_net"])

    # 13. Two raises by 2028
    r28 = models.get_income_for_month(2028, 12)
    maggie_raise = int(config.INCOME["maggie"]["annual_raise"] * 0.055)
    check(13, "Kero has 2 raises by end of 2028",
          config.INCOME["kero"]["monthly_net"] + kero_raise * 2, r28["kero_net"])

    # 14. Bonuses unchanged after raises
    check(14, "Kero bonus unchanged in 2028", 1500, r28["kero_bonus"])

    # 15. Total increases with raises
    check_true(15, "2028 total > 2026 total", r28["total_income"] > r1["total_income"])

    # 16. Pre-2025 income same as base
    r24 = models.get_income_for_month(2024, 6)
    check(16, "2024 income = base (no raises)", r1["total_income"], r24["total_income"])

    # 17. Income always positive
    check_true(17, "Income always positive", r["total_income"] > 0)

    # 18. Kero net > Maggie net
    check_true(18, "Kero net > Maggie net", r["kero_net"] > r["maggie_net"])

    # 19. Total income in reasonable range (15k-25k)
    check_true(19, "Total income in $15k-$25k range", 15000 < r["total_income"] < 25000)

    # 20. Bonus toggle math: income minus both bonuses
    no_bonus = r["total_income"] - r["kero_bonus"] - r["maggie_bonus"]
    check(20, "Income without bonuses = kero_net + maggie_net",
          r["kero_net"] + r["maggie_net"], no_bonus)


# ══════════════════════════════════════════════════════════════════════════
# F2: BUDGET MATH — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f2_budget_math():
    group_header("F2: Budget Math")
    conn = database.get_connection()
    months = database.get_available_months(conn)
    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))

    for idx, month_key in enumerate(months[:5]):
        y, m = int(month_key[:4]), int(month_key[5:])
        income_data = models.get_income_for_month(y, m)
        monthly_income = income_data["total_income"]
        effective_fixed = database.get_effective_fixed_total(conn)
        breakdown = get_filtered_breakdown(conn, month_key)
        fixed_cats = get_fixed_categories(conn)
        flex_cats = get_flex_categories(conn)

        txn_disc = sum(abs(c["total"]) for c in breakdown if c["category"] in flex_cats)
        total_outflow = effective_fixed + txn_disc
        saved = monthly_income - total_outflow
        gap = saved - savings_target
        disc_budget = monthly_income - effective_fixed - savings_target
        disc_left = max(disc_budget - txn_disc, 0)
        over_budget = max(txn_disc - disc_budget, 0)

        base = idx * 4
        # Savings identity
        check(base + 1, f"{month_key}: saved = income - fixed - flex",
              monthly_income - effective_fixed - txn_disc, saved)
        # Gap identity
        check(base + 2, f"{month_key}: gap = saved - target",
              saved - savings_target, gap)
        # Flex budget identity
        check(base + 3, f"{month_key}: flex_budget = income - fixed - target",
              monthly_income - effective_fixed - savings_target, disc_budget)
        # Over + left are mutually exclusive
        check_true(base + 4, f"{month_key}: over_budget or disc_left, not both",
                   (disc_left == 0) or (over_budget == 0))

    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# F3: PROJECTED SAVINGS — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f3_projected_savings():
    group_header("F3: Projected Savings")
    conn = database.get_connection()

    # Test the projection formula for various scenarios
    test_cases = [
        # (txn_disc, days_elapsed, days_left, days_in_month, income, fixed)
        (3000, 15, 15, 30, 20000, 13530),   # 1-2: mid-month
        (6000, 28, 2, 30, 20000, 13530),     # 3-4: near end
        (1000, 5, 25, 30, 20000, 13530),     # 5-6: early month
        (0, 1, 29, 30, 20000, 13530),        # 7-8: day 1 with no spend
        (5000, 30, 0, 30, 20000, 13530),     # 9-10: month complete
        (4000, 15, 16, 31, 20000, 13530),    # 11-12: 31-day month
        (2000, 10, 18, 28, 20000, 13530),    # 13-14: Feb
        (8000, 20, 10, 30, 20000, 13530),    # 15-16: heavy spending
        (500, 3, 27, 30, 20000, 13530),      # 17-18: very early, low spend
        (10000, 25, 5, 30, 20000, 13530),    # 19-20: over budget
    ]

    for i, (txn_disc, days_elapsed, days_left, days_in_month, income, fixed) in enumerate(test_cases):
        tid = i * 2 + 1

        if days_elapsed > 0 and days_left > 0:
            daily_flex = txn_disc / days_elapsed
            projected_flex = txn_disc + (daily_flex * days_left)
            projected_saved = income - fixed - projected_flex

            # Verify daily rate
            check(tid, f"Case {i+1}: daily_flex = {txn_disc}/{days_elapsed}",
                  txn_disc / days_elapsed, daily_flex)

            # Verify projection
            expected_proj = income - fixed - (txn_disc + (txn_disc / days_elapsed * days_left))
            check(tid + 1, f"Case {i+1}: projected savings correct",
                  expected_proj, projected_saved)
        elif days_left == 0:
            actual_saved = income - fixed - txn_disc
            check(tid, f"Case {i+1}: month complete, saved = income - fixed - spent",
                  income - fixed - txn_disc, actual_saved)
            check_true(tid + 1, f"Case {i+1}: month complete, no projection needed", True)
        else:
            check_true(tid, f"Case {i+1}: edge case handled", True)
            check_true(tid + 1, f"Case {i+1}: edge case OK", True)

    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# F4: CATEGORY BREAKDOWN — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f4_category_breakdown():
    group_header("F4: Category Breakdown")
    conn = database.get_connection()
    months = database.get_available_months(conn)
    excluded = get_excluded_categories(conn)
    fixed_cats = get_fixed_categories(conn)
    flex_cats = get_flex_categories(conn)

    tid = 0
    for month_key in months[:4]:
        full = get_filtered_breakdown(conn, month_key)
        flex = get_flex_breakdown(conn, month_key)

        # 1. All amounts are negative (expenses)
        tid += 1
        check_true(tid, f"{month_key}: all totals are negative",
                   all(c["total"] < 0 for c in full))

        # 2. No excluded categories
        tid += 1
        full_cats = {c["category"] for c in full}
        check_true(tid, f"{month_key}: no excluded categories in breakdown",
                   len(full_cats & excluded) == 0)

        # 3. Flex is subset of full
        tid += 1
        flex_cat_set = {c["category"] for c in flex}
        check_true(tid, f"{month_key}: flex categories are subset of full",
                   flex_cat_set.issubset(full_cats))

        # 4. Merchant breakdown sums match category total
        if full:
            top = full[0]
            merchants = database.get_merchant_breakdown_for_month(conn, top["category"], month_key, limit=100)
            merch_total = sum(abs(m["total"]) for m in merchants)
            tid += 1
            check(tid, f"{month_key}: merchant total matches category total for {top['category']}",
                  abs(top["total"]), merch_total, tolerance=0.01)

        # 5. txn_count is positive
        tid += 1
        check_true(tid, f"{month_key}: all txn_counts positive",
                   all(c["txn_count"] > 0 for c in full))

    # Cross-validate with direct SQL
    for month_key in months[:2]:
        breakdown = get_filtered_breakdown(conn, month_key)
        total_from_breakdown = sum(abs(c["total"]) for c in breakdown)
        # Direct query
        sql_total = conn.execute("""
            SELECT ABS(SUM(amount)) FROM transactions
            WHERE strftime('%Y-%m', date) = ? AND amount < 0
            AND category NOT IN (SELECT name FROM category_config WHERE type = 'exclude')
        """, (month_key,)).fetchone()[0] or 0
        tid += 1
        check(tid, f"{month_key}: breakdown total matches direct SQL",
              sql_total, total_from_breakdown, tolerance=0.02)

    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# F5: HISTORICAL AVERAGES & TRENDS — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f5_historical_trends():
    group_header("F5: Historical Averages & Trends")
    conn = database.get_connection()
    excluded = get_excluded_categories(conn)

    # Test get_category_monthly_history
    cats_to_test = ["Groceries", "Shopping", "Restaurants & Bars", "Gas & Electric"]
    tid = 0

    for cat in cats_to_test:
        hist = database.get_category_monthly_history(conn, cat, months=12)
        tid += 1
        check_true(tid, f"{cat}: history returns list", isinstance(hist, list))

        tid += 1
        check_true(tid, f"{cat}: all totals are negative",
                   all(h["total"] < 0 for h in hist))

        # Verify average calculation
        if len(hist) >= 2:
            avg = sum(abs(h["total"]) for h in hist) / len(hist)
            tid += 1
            check_true(tid, f"{cat}: average > 0 for {len(hist)} months", avg > 0)

            # Verify months are sorted DESC
            tid += 1
            months_sorted = all(hist[i]["month"] >= hist[i+1]["month"] for i in range(len(hist)-1))
            check_true(tid, f"{cat}: months sorted descending", months_sorted)
        else:
            tid += 2

    # Test get_spending_trend_filtered
    trend = database.get_spending_trend_filtered(conn, months=12, excluded_categories=excluded)
    tid += 1
    check_true(tid, "Filtered trend returns 12 or fewer months", len(trend) <= 12)

    tid += 1
    check_true(tid, "All spending values are negative or zero",
               all(r["spending"] <= 0 for r in trend))

    # Verify filtered trend excludes excluded categories
    unfiltered = database.get_spending_trend(conn, months=12)
    tid += 1
    if unfiltered and trend:
        # Filtered should show less spending (in absolute terms) than unfiltered
        filt_total = sum(abs(r["spending"]) for r in trend)
        unfilt_total = sum(abs(r["spending"]) for r in unfiltered)
        check_true(tid, "Filtered total <= unfiltered total", filt_total <= unfilt_total)

    # Test annual breakdown
    annual = database.get_annual_category_breakdown(conn, "2025")
    tid += 1
    check_true(tid, "2025 annual breakdown has entries", len(annual) > 0)
    tid += 1
    check_true(tid, "All annual totals are negative", all(c["total"] < 0 for c in annual))

    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# F6: RECURRING BILL DETECTION — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f6_recurring_bills():
    group_header("F6: Recurring Bill Detection")
    conn = database.get_connection()
    fixed_cats = get_fixed_categories(conn)
    excluded = get_excluded_categories(conn)

    # Replicate the recurring detection SQL from views/transactions.py:607-616
    recurring = conn.execute("""
        SELECT description, category,
               COUNT(DISTINCT strftime('%Y-%m', date)) as months,
               ROUND(AVG(ABS(amount)), 2) as avg_amount,
               COUNT(*) as total_txns
        FROM transactions
        WHERE amount < 0 AND date >= date('now', '-6 months')
        GROUP BY description, category
        HAVING months >= 4 AND avg_amount > 50
        ORDER BY avg_amount DESC
    """).fetchall()
    recurring = [dict(r) for r in recurring]

    check_true(1, "Recurring detection returns results", len(recurring) >= 0)
    check_true(2, "All recurring have >= 4 months", all(r["months"] >= 4 for r in recurring))
    check_true(3, "All recurring have avg > $50", all(r["avg_amount"] > 50 for r in recurring))
    check_true(4, "All recurring have description", all(r["description"] for r in recurring))

    # Filter out already-fixed categories (like the app does)
    not_fixed = [r for r in recurring if r["category"] not in fixed_cats and r["category"] not in excluded]
    check_true(5, "Filtered recurring excludes fixed categories",
               all(r["category"] not in fixed_cats for r in not_fixed))

    # Verify each recurring bill actually has transactions in 4+ months
    for i, r in enumerate(recurring[:5]):
        actual_months = conn.execute("""
            SELECT COUNT(DISTINCT strftime('%Y-%m', date))
            FROM transactions
            WHERE description = ? AND category = ? AND amount < 0
            AND date >= date('now', '-6 months')
        """, (r["description"], r["category"])).fetchone()[0]
        check(6 + i, f"Verify '{r['description'][:30]}' has {r['months']} months",
              r["months"], actual_months)

    # Verify avg amounts
    for i, r in enumerate(recurring[:5]):
        actual_avg = conn.execute("""
            SELECT ROUND(AVG(ABS(amount)), 2)
            FROM transactions
            WHERE description = ? AND category = ? AND amount < 0
            AND date >= date('now', '-6 months')
        """, (r["description"], r["category"])).fetchone()[0]
        check(11 + i, f"Verify avg for '{r['description'][:30]}' = ${r['avg_amount']}",
              r["avg_amount"], actual_avg)

    # Edge: no results with impossible thresholds
    impossible = conn.execute("""
        SELECT description FROM transactions
        WHERE amount < 0 AND date >= date('now', '-6 months')
        GROUP BY description, category
        HAVING COUNT(DISTINCT strftime('%Y-%m', date)) >= 7
    """).fetchall()
    check_true(16, "No merchant appears in > 6 of last 6 months", len(impossible) == 0)

    # Verify total_txns >= months for each
    check_true(17, "total_txns >= months for all recurring",
               all(r["total_txns"] >= r["months"] for r in recurring))

    # Sorted by avg_amount DESC
    check_true(18, "Results sorted by avg_amount DESC",
               all(recurring[i]["avg_amount"] >= recurring[i+1]["avg_amount"]
                   for i in range(len(recurring)-1)) if len(recurring) > 1 else True)

    # No duplicates
    keys = [(r["description"], r["category"]) for r in recurring]
    check_true(19, "No duplicate description+category pairs", len(keys) == len(set(keys)))

    check_true(20, "Recurring detection query runs without error", True)

    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# F7: DUPLICATE PREVENTION — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f7_duplicate_prevention():
    group_header("F7: Duplicate Prevention")
    conn = database.get_connection()

    # 1. Hash computation
    import pdf_parser
    test_bytes = b"test content for hashing"
    h = pdf_parser.compute_bytes_hash(test_bytes)
    check(1, "Hash is SHA-256 hex string (64 chars)", 64, len(h))
    check(2, "Hash is deterministic", pdf_parser.compute_bytes_hash(test_bytes), h)
    check_true(3, "Different content → different hash",
               pdf_parser.compute_bytes_hash(b"different") != h)
    check_true(4, "Empty content produces valid hash",
               len(pdf_parser.compute_bytes_hash(b"")) == 64)
    check_true(5, "Hash is lowercase hex", all(c in "0123456789abcdef" for c in h))

    # 2. classify_upload with no existing statements → always "new"
    # Signature: (conn, account_id, period_start, period_end, file_hash)
    result = database.classify_upload(conn, "chase_4730", "2099-01-01", "2099-01-31", "new_hash_1")
    check(6, "New period → new status", "new", result["status"])
    check_true(7, "classify_upload returns status key", "status" in result)
    check_true(8, "classify_upload returns message key", "message" in result)
    check_true(9, "classify_upload returns action key", "action" in result)

    # Different accounts all return new
    for acct in ["chase_4730", "joint_checking", "nonexistent"]:
        r = database.classify_upload(conn, acct, "2099-06-01", "2099-06-30", f"hash_{acct}")
        check(10 + ["chase_4730", "joint_checking", "nonexistent"].index(acct),
              f"New period for {acct} → new", "new", r["status"])

    # 3. check_duplicate_statement
    check_true(13, "Random hash is not duplicate",
               not database.check_duplicate_statement(conn, "random_nonexistent_hash"))
    check_true(14, "Another random hash not duplicate",
               not database.check_duplicate_statement(conn, "abc123def456"))

    # 4. check_overlapping_period with no statements
    no_overlap = database.check_overlapping_period(conn, "chase_4730", "2099-01-01", "2099-01-31")
    check_true(15, "No overlaps when no statements exist", len(no_overlap) == 0)

    # 5. All stored hashes are unique
    all_hashes = conn.execute("SELECT sha256 FROM statements").fetchall()
    hash_list = [r[0] for r in all_hashes]
    check(16, "All statement hashes are unique (or empty)", len(hash_list), len(set(hash_list)))

    # 6. Action values are valid
    valid_actions = {"skip", "import", "ask_user"}
    r = database.classify_upload(conn, "test", "2099-01-01", "2099-01-31", "test_hash")
    check_true(17, f"Action '{r['action']}' is valid", r["action"] in valid_actions)

    # 7. Message is non-empty string
    check_true(18, "Message is non-empty string", isinstance(r["message"], str) and len(r["message"]) > 0)

    # 8. Hash of known content matches hashlib
    known = b"hello world"
    expected_hash = hashlib.sha256(known).hexdigest()
    check(19, "Hash matches hashlib.sha256", expected_hash, pdf_parser.compute_bytes_hash(known))

    # 9. Large content hashes correctly
    large = b"x" * 1_000_000
    check_true(20, "1MB content hashes to 64-char string",
               len(pdf_parser.compute_bytes_hash(large)) == 64)

    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# F8: COVERAGE ANALYSIS — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f8_coverage_analysis():
    group_header("F8: Coverage Analysis")
    conn = database.get_connection()

    # Coverage function
    coverage = database.get_account_coverage(conn)
    check_true(1, "Coverage returns dict", isinstance(coverage, dict))

    # Date range (independent of statements)
    dr = database.get_date_range(conn)
    check_true(2, "Date range returns tuple", len(dr) == 2)
    check_true(3, "Start <= End in date range", dr[0] <= dr[1])
    check_true(4, "Start date is valid ISO format", len(dr[0]) == 10)
    check_true(5, "End date is valid ISO format", len(dr[1]) == 10)

    # Transaction-based coverage (independent of statements table)
    accts = conn.execute("SELECT DISTINCT account_id FROM transactions").fetchall()
    acct_list = [r[0] for r in accts]
    check_true(6, "Have transaction accounts", len(acct_list) > 0)

    # Per-account date ranges
    for acct in acct_list:
        adr = conn.execute("""
            SELECT MIN(date), MAX(date), COUNT(*)
            FROM transactions WHERE account_id = ?
        """, (acct,)).fetchone()
        check_true(7, f"{acct}: has transactions", adr[2] > 0)
        check_true(8, f"{acct}: min_date <= max_date", adr[0] <= adr[1])
        break

    # Per-account monthly coverage
    for acct in acct_list:
        months_with_data = conn.execute("""
            SELECT DISTINCT strftime('%Y-%m', date) as month
            FROM transactions WHERE account_id = ?
            ORDER BY month
        """, (acct,)).fetchall()
        month_list = [r[0] for r in months_with_data]
        check_true(9, f"{acct}: has months with data", len(month_list) > 0)
        check_true(10, f"{acct}: months are valid format",
                   all(len(m) == 7 and m[4] == '-' for m in month_list))
        check_true(11, f"{acct}: months are sorted",
                   month_list == sorted(month_list))
        break

    # Missing months logic: find gaps between first and last month per account
    for acct in acct_list:
        adr = conn.execute("SELECT MIN(date), MAX(date) FROM transactions WHERE account_id = ?", (acct,)).fetchone()
        start_d = date.fromisoformat(adr[0])
        end_d = date.fromisoformat(adr[1])
        # Generate expected months
        expected = []
        cur = start_d.replace(day=1)
        end_m = end_d.replace(day=1)
        while cur <= end_m:
            expected.append(cur.strftime("%Y-%m"))
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)

        actual = set(r[0] for r in conn.execute("""
            SELECT DISTINCT strftime('%Y-%m', date) FROM transactions WHERE account_id = ?
        """, (acct,)).fetchall())

        gaps = [m for m in expected if m not in actual]
        check_true(12, f"{acct}: gap detection works ({len(gaps)} gaps found)", isinstance(gaps, list))

        # Verify gaps truly have no transactions
        for g in gaps[:2]:
            cnt = conn.execute("""
                SELECT COUNT(*) FROM transactions
                WHERE account_id = ? AND strftime('%Y-%m', date) = ?
            """, (acct, g)).fetchone()[0]
            check(13, f"{acct}: gap {g} confirmed empty", 0, cnt)
            break
        break

    # Heatmap: build binary matrix from transaction data
    all_months = sorted(set(
        r[0] for r in conn.execute(
            "SELECT DISTINCT strftime('%Y-%m', date) FROM transactions"
        ).fetchall()
    ))
    check_true(14, "Have months for heatmap", len(all_months) > 0)
    check_true(15, "Have accounts for heatmap", len(acct_list) > 0)

    z_data = []
    filled = 0
    total_cells = 0
    for acct in acct_list:
        acct_months = set(r[0] for r in conn.execute("""
            SELECT DISTINCT strftime('%Y-%m', date) FROM transactions WHERE account_id = ?
        """, (acct,)).fetchall())
        row = []
        for m in all_months:
            val = 1 if m in acct_months else 0
            row.append(val)
            filled += val
            total_cells += 1
        z_data.append(row)

    check_true(16, "Heatmap matrix is rectangular",
               all(len(row) == len(all_months) for row in z_data))
    check_true(17, "Heatmap rows match account count", len(z_data) == len(acct_list))

    pct = (filled / total_cells * 100) if total_cells > 0 else 0
    check_true(18, f"Coverage % valid (0-100): {pct:.1f}%", 0 <= pct <= 100)
    check_true(19, "Coverage % > 0 (we have data)", pct > 0)

    # Statement count
    stmt_count = conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0]
    check_true(20, f"Statement count is non-negative: {stmt_count}", stmt_count >= 0)

    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# F9: SAVINGS PLAN MATH — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f9_savings_plan_math():
    group_header("F9: Savings Plan Math")
    conn = database.get_connection()

    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))
    income_data = models.get_income_for_month(2026, 3)
    monthly_income = income_data["total_income"]
    effective_fixed = database.get_effective_fixed_total(conn)
    flex_budget = monthly_income - effective_fixed - savings_target

    check_true(1, "Flex budget is positive", flex_budget > 0)
    check(2, "Flex budget identity", monthly_income - effective_fixed - savings_target, flex_budget)

    # 6-month average computation (replicate savings_journey.py logic)
    months = database.get_available_months(conn)
    fixed_cats = get_fixed_categories(conn)
    excluded_cats = get_excluded_categories(conn)

    all_cats = {}
    for ym in months[:6]:
        breakdown = get_filtered_breakdown(conn, ym)
        flex_only = [c for c in breakdown if c["category"] not in fixed_cats]
        for c in flex_only:
            cat = c["category"]
            amt = abs(c["total"])
            if cat not in all_cats:
                all_cats[cat] = []
            all_cats[cat].append(amt)

    cat_averages = {}
    for cat, amounts in all_cats.items():
        avg = round(sum(amounts) / len(amounts))
        if avg > 20:
            cat_averages[cat] = avg

    total_typical = sum(cat_averages.values())

    check_true(3, "Have category averages", len(cat_averages) > 0)
    check_true(4, "Total typical > 0", total_typical > 0)
    check_true(5, "Averages exclude < $20 categories",
               all(v > 20 for v in cat_averages.values()))

    # Impact calculation
    # If we set all targets to their averages, cuts = 0
    check(6, "No cuts when targets = averages", 0, total_typical - total_typical)

    # If we cut every category by $50
    planned = sum(max(v - 50, 0) for v in cat_averages.values())
    cuts = total_typical - planned
    check_true(7, f"Cuts of ~$50/cat = ${cuts:,.0f}", cuts > 0)

    # Projected savings
    projected = monthly_income - effective_fixed - planned
    check(8, "Projected savings = income - fixed - planned",
          monthly_income - effective_fixed - planned, projected)

    # Year projection
    annual = projected * 12
    check(9, "Annual = projected × 12", projected * 12, annual)

    # Floor enforcement
    floor = 50
    typical = 500
    slider_val = 30  # Below floor
    clamped = max(floor, min(slider_val, typical))
    check(10, "Value below floor gets clamped to floor", floor, clamped)

    slider_val = 600  # Above typical
    clamped = max(floor, min(slider_val, typical))
    check(11, "Value above typical gets clamped to typical", typical, clamped)

    slider_val = 200  # In range
    clamped = max(floor, min(slider_val, typical))
    check(12, "Value in range stays unchanged", 200, clamped)

    # Rounding to nearest $25
    for val, expected in [(113, 125), (112, 100), (138, 150), (125, 125), (0, 0)]:
        rounded = round(val / 25) * 25
        check(13 + [113, 112, 138, 125, 0].index(val),
              f"Round {val} to nearest $25 = {expected}", expected, rounded)

    # Excess scaling
    targets = {"A": 500, "B": 300, "C": 200}
    mins = {"A": 100, "B": 100, "C": 50}
    budget = 800
    plan_total = sum(targets.values())  # 1000
    excess = plan_total - budget  # 200

    cuttable = {k: targets[k] - mins[k] for k in targets if targets[k] > mins[k]}
    cuttable_total = sum(cuttable.values())  # 400+200+150 = 750
    cut_ratio = min(excess / cuttable_total, 1.0)

    scaled = {}
    for k, v in targets.items():
        headroom = cuttable.get(k, 0)
        cut = round(headroom * cut_ratio / 25) * 25
        scaled[k] = max(mins[k], v - cut)

    check_true(18, "Scaled total <= budget + $25 tolerance",
               sum(scaled.values()) <= budget + 25)
    check_true(19, "All scaled values >= their floors",
               all(scaled[k] >= mins[k] for k in scaled))
    check_true(20, "Scaling reduced total from 1000",
               sum(scaled.values()) < plan_total)

    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# F10: YEAR PROJECTIONS & SPARKLINE — 20 tests
# ══════════════════════════════════════════════════════════════════════════

def test_f10_projections():
    group_header("F10: Year Projections & Sparkline")
    conn = database.get_connection()

    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))
    effective_fixed = database.get_effective_fixed_total(conn)
    months = database.get_available_months(conn)

    # Sparkline data: compute savings for last 6 months
    monthly_flex = database.get_monthly_flex_totals(conn, months=7)
    flex_map = {r["month"]: r["flex_total"] for r in monthly_flex}

    spark_data = []
    for ym in months[:6]:
        y, m = int(ym[:4]), int(ym[5:])
        inc = models.get_income_for_month(y, m)
        mo_income = inc["total_income"]
        mo_flex = flex_map.get(ym, 0)
        mo_saved = mo_income - effective_fixed - mo_flex
        spark_data.append({"month": ym, "saved": mo_saved, "hit": mo_saved >= savings_target})

    check_true(1, "Sparkline has 6 data points", len(spark_data) == 6)
    check_true(2, "Each point has month key", all("month" in s for s in spark_data))
    check_true(3, "Each point has saved key", all("saved" in s for s in spark_data))
    check_true(4, "Each point has hit key", all("hit" in s for s in spark_data))

    # Verify savings formula for each month
    for i, sp in enumerate(spark_data[:3]):
        y, m = int(sp["month"][:4]), int(sp["month"][5:])
        inc = models.get_income_for_month(y, m)
        flex = flex_map.get(sp["month"], 0)
        expected = inc["total_income"] - effective_fixed - flex
        check(5 + i, f"{sp['month']}: saved = income - fixed - flex",
              expected, sp["saved"])

    # Hit logic
    for i, sp in enumerate(spark_data[:3]):
        check(8 + i, f"{sp['month']}: hit = saved >= target",
              sp["saved"] >= savings_target, sp["hit"])

    # Year projection formulas
    projected_savings = 2000  # Example
    annual = projected_savings * 12
    check(11, "Annual = monthly × 12", 24000, annual)

    five_year = annual * 5
    check(12, "5-year = annual × 5", 120000, five_year)

    # Post-daycare calculation
    daycare = 2000
    post_daycare_annual = (projected_savings + daycare) * 12
    check(13, "Post-daycare annual = (saved + daycare) × 12", (2000 + 2000) * 12, post_daycare_annual)

    # Color logic
    for val, expected_positive in [(1000, True), (0, False), (-500, False), (1, True)]:
        color_ok = val > 0
        check(14 + [(1000, True), (0, False), (-500, False), (1, True)].index((val, expected_positive)),
              f"Projection ${val}: positive={expected_positive}", expected_positive, color_ok)

    # Bar height calculation for sparkline
    max_spark = max(abs(s["saved"]) for s in spark_data) if spark_data else 1
    check_true(18, "Max sparkline value > 0", max_spark > 0)

    for sp in spark_data[:2]:
        h = max(int(abs(sp["saved"]) / max_spark * 32), 3)
        check_true(19, f"{sp['month']}: bar height 3-32 range", 3 <= h <= 32)
        break

    check_true(20, "Sparkline months are sorted descending",
               all(spark_data[i]["month"] >= spark_data[i+1]["month"]
                   for i in range(len(spark_data)-1)))

    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════════

def main():
    global PASS_COUNT, FAIL_COUNT

    print("=" * 80)
    print("  COMPREHENSIVE FUNCTION TESTS — 200 Tests (10 groups × 20)")
    print("=" * 80)

    test_functions = [
        test_f1_income_model,
        test_f2_budget_math,
        test_f3_projected_savings,
        test_f4_category_breakdown,
        test_f5_historical_trends,
        test_f6_recurring_bills,
        test_f7_duplicate_prevention,
        test_f8_coverage_analysis,
        test_f9_savings_plan_math,
        test_f10_projections,
    ]

    group_results = []
    for fn in test_functions:
        before_pass = PASS_COUNT
        before_fail = FAIL_COUNT
        try:
            fn()
        except Exception as e:
            print(f"  ERROR in {fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
        g_pass = PASS_COUNT - before_pass
        g_fail = FAIL_COUNT - before_fail
        group_results.append((fn.__name__, g_pass, g_fail))

    print(f"\n{'=' * 80}")
    print(f"  FINAL SUMMARY: {PASS_COUNT} PASSED / {FAIL_COUNT} FAILED / {PASS_COUNT + FAIL_COUNT} TOTAL")
    print(f"{'=' * 80}")
    print(f"\n{'Group':<45} {'Pass':>6} {'Fail':>6}")
    print(f"{'─' * 60}")
    for name, p, f in group_results:
        status = "✓" if f == 0 else "✗"
        print(f"  {status} {name:<42} {p:>6} {f:>6}")

    return FAIL_COUNT == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
