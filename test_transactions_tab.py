#!/usr/bin/env python3
"""
Transactions Tab Data Validation — 100 Tests
=============================================
Tests every filter combination (category, date range, account, hide_transfers,
search) against the actual database to validate the sum/count logic used in
views/transactions.py.
"""

import sys
import json
import itertools
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

import config
import database
import category_engine

# ── Replicate the exact filtering logic from views/transactions.py ───────

EXCLUDED_CATEGORIES = config.EXCLUDED_CATEGORIES


def simulate_transactions_tab(conn, start_date, end_date, account, category,
                              hide_transfers, search_q=""):
    """
    Replicate views/transactions.py lines 460-514 exactly:
      1. Fetch from DB with filters
      2. Apply hide_transfers
      3. Apply search
      4. Compute spending sum
    Returns dict with total_spent, txn_count, category_totals.
    """
    txns = database.get_transactions(
        conn,
        start_date=start_date,
        end_date=end_date,
        account_id=account if account != "All" else None,
        category=category if category != "All" else None,
    )
    if not txns:
        return {"total_spent": 0, "txn_count": 0, "expense_count": 0, "category_totals": {}}

    df = pd.DataFrame([dict(t) for t in txns])

    # Replicate hide logic (line 479-481)
    if hide_transfers and category == "All":
        _hide_cats = EXCLUDED_CATEGORIES | set()  # _muted_cats is empty
        df = df[~df["category"].isin(_hide_cats)]

    # Search filter (line 483-485)
    if search_q:
        df = df[df["description"].str.contains(search_q, case=False, na=False) |
                df["category"].str.contains(search_q, case=False, na=False)]

    if df.empty:
        return {"total_spent": 0, "txn_count": 0, "expense_count": 0, "category_totals": {}}

    # Spending summary (line 495-496)
    spending_df = df[df["amount"] < 0]
    total_spent = abs(spending_df["amount"].sum()) if not spending_df.empty else 0
    txn_count = len(df)
    expense_count = len(spending_df)

    cat_totals = {}
    if not spending_df.empty:
        cat_totals = spending_df.groupby("category")["amount"].sum().abs().to_dict()

    return {
        "total_spent": round(total_spent, 2),
        "txn_count": txn_count,
        "expense_count": expense_count,
        "category_totals": cat_totals,
    }


def direct_db_query(conn, start_date, end_date, account, category,
                    hide_transfers, search_q=""):
    """
    Compute the expected result using a direct SQL query — independent of
    the DataFrame logic — to cross-validate.
    """
    query = "SELECT * FROM transactions WHERE date >= ? AND date <= ?"
    params = [start_date, end_date]

    if account != "All":
        query += " AND account_id = ?"
        params.append(account)
    if category != "All":
        query += " AND category = ?"
        params.append(category)

    rows = conn.execute(query, params).fetchall()
    results = [dict(r) for r in rows]

    # Apply hide_transfers
    if hide_transfers and category == "All":
        _hide = EXCLUDED_CATEGORIES | set()
        results = [r for r in results if r["category"] not in _hide]

    # Apply search
    if search_q:
        sq = search_q.lower()
        results = [r for r in results if sq in r["description"].lower() or sq in r["category"].lower()]

    expenses = [r for r in results if r["amount"] < 0]
    total_spent = round(abs(sum(r["amount"] for r in expenses)), 2)

    cat_totals = {}
    for r in expenses:
        cat_totals[r["category"]] = cat_totals.get(r["category"], 0) + abs(r["amount"])
    cat_totals = {k: round(v, 2) for k, v in cat_totals.items()}

    return {
        "total_spent": total_spent,
        "txn_count": len(results),
        "expense_count": len(expenses),
        "category_totals": cat_totals,
    }


# ── Test Generation ──────────────────────────────────────────────────────

def generate_100_tests(conn):
    """Generate 100 diverse filter combinations."""
    tests = []
    tid = 0
    date_range = database.get_date_range(conn)
    min_date = date_range[0]
    max_date = date_range[1]
    active_cats = category_engine.get_active_categories(conn)
    accounts = ["All", "chase_4730", "joint_checking"]

    # Get categories with actual spending for meaningful tests
    cat_rows = conn.execute("""
        SELECT category, COUNT(*) as c, SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) as spend
        FROM transactions WHERE amount < 0
        GROUP BY category ORDER BY spend ASC
    """).fetchall()
    all_cats_with_spend = [r[0] for r in cat_rows]

    # Top 20 spending categories
    top_cats = all_cats_with_spend[:20]
    # Small categories
    small_cats = all_cats_with_spend[-10:]

    # Date ranges to test
    date_ranges = [
        ("Full range", min_date, max_date),
        ("Year 2025", "2025-01-01", "2025-12-31"),
        ("Year 2024", "2024-01-01", "2024-12-31"),
        ("Year 2026", "2026-01-01", "2026-12-31"),
        ("Jan 2026", "2026-01-01", "2026-01-31"),
        ("Feb 2026", "2026-02-01", "2026-02-28"),
        ("Mar 2026", "2026-03-01", "2026-03-31"),
        ("Dec 2025", "2025-12-01", "2025-12-31"),
        ("Q1 2026", "2026-01-01", "2026-03-31"),
        ("Q4 2025", "2025-10-01", "2025-12-31"),
        ("Last 90 days", (date.today() - timedelta(days=90)).isoformat(), date.today().isoformat()),
        ("Single day 2026-03-05", "2026-03-05", "2026-03-05"),
        ("Jul 2025", "2025-07-01", "2025-07-31"),
        ("Apr 2024", "2024-04-01", "2024-04-30"),
    ]

    # ── Group 1: Every category with full date range (tests 1-30) ──
    for cat in top_cats[:15]:
        tid += 1
        tests.append({
            "id": tid,
            "desc": f"All time | {cat} | All accounts | hide=True",
            "start": min_date, "end": max_date,
            "account": "All", "category": cat,
            "hide_transfers": True, "search": "",
        })
    for cat in small_cats[:5]:
        tid += 1
        tests.append({
            "id": tid,
            "desc": f"All time | {cat} | All accounts | hide=True",
            "start": min_date, "end": max_date,
            "account": "All", "category": cat,
            "hide_transfers": True, "search": "",
        })
    # All categories with hide_transfers=True and False
    for hide in [True, False]:
        tid += 1
        tests.append({
            "id": tid,
            "desc": f"All time | All cats | All accts | hide={hide}",
            "start": min_date, "end": max_date,
            "account": "All", "category": "All",
            "hide_transfers": hide, "search": "",
        })
    # Per account
    for acct in ["chase_4730", "joint_checking"]:
        tid += 1
        tests.append({
            "id": tid,
            "desc": f"All time | All cats | {acct} | hide=True",
            "start": min_date, "end": max_date,
            "account": acct, "category": "All",
            "hide_transfers": True, "search": "",
        })
    # Per account + category
    for acct in ["chase_4730", "joint_checking"]:
        for cat in top_cats[:4]:
            tid += 1
            tests.append({
                "id": tid,
                "desc": f"All time | {cat} | {acct} | hide=True",
                "start": min_date, "end": max_date,
                "account": acct, "category": cat,
                "hide_transfers": True, "search": "",
            })

    # ── Group 2: Date range variations (tests ~31-55) ──
    for label, s, e in date_ranges:
        tid += 1
        tests.append({
            "id": tid,
            "desc": f"{label} | All cats | All accts | hide=True",
            "start": s, "end": e,
            "account": "All", "category": "All",
            "hide_transfers": True, "search": "",
        })

    # ── Group 3: Date range + specific category (tests ~56-75) ──
    test_cats = ["Groceries", "Shopping", "Restaurants & Bars", "Gas & Electric",
                 "Gas", "Coffee Shops", "Education", "Medical", "Clothing",
                 "Cash & ATM"]
    for cat in test_cats:
        # Year 2025
        tid += 1
        tests.append({
            "id": tid,
            "desc": f"2025 | {cat} | All accts | hide=True",
            "start": "2025-01-01", "end": "2025-12-31",
            "account": "All", "category": cat,
            "hide_transfers": True, "search": "",
        })
    for cat in test_cats[:5]:
        # Q1 2026
        tid += 1
        tests.append({
            "id": tid,
            "desc": f"Q1 2026 | {cat} | All accts | hide=True",
            "start": "2026-01-01", "end": "2026-03-31",
            "account": "All", "category": cat,
            "hide_transfers": True, "search": "",
        })

    # ── Group 4: Search filter tests (tests ~76-85) ──
    search_terms = ["costco", "safeway", "amazon", "target", "starbucks",
                    "anthropic", "comcast", "t-mobile", "chase", "zelle"]
    for term in search_terms:
        tid += 1
        tests.append({
            "id": tid,
            "desc": f"All time | All cats | search='{term}' | hide=True",
            "start": min_date, "end": max_date,
            "account": "All", "category": "All",
            "hide_transfers": True, "search": term,
        })

    # ── Group 5: hide_transfers=False edge cases (tests ~86-92) ──
    excluded_cats = ["Credit Card Payment", "Transfer", "Loan Repayment",
                     "Check", "Taxes"]
    for cat in excluded_cats:
        if cat in all_cats_with_spend or cat in [r[0] for r in cat_rows]:
            tid += 1
            tests.append({
                "id": tid,
                "desc": f"All time | {cat} | hide=False",
                "start": min_date, "end": max_date,
                "account": "All", "category": cat,
                "hide_transfers": False, "search": "",
            })

    # ── Group 6: Single month + account combos (tests ~93-100) ──
    months_to_test = [
        ("2025-07", "2025-07-01", "2025-07-31"),
        ("2025-12", "2025-12-01", "2025-12-31"),
        ("2026-02", "2026-02-01", "2026-02-28"),
        ("2026-03", "2026-03-01", "2026-03-31"),
    ]
    for label, s, e in months_to_test:
        for acct in ["chase_4730", "joint_checking"]:
            tid += 1
            tests.append({
                "id": tid,
                "desc": f"{label} | All cats | {acct} | hide=True",
                "start": s, "end": e,
                "account": acct, "category": "All",
                "hide_transfers": True, "search": "",
            })

    # ── Group 7: More category + date combos to reach 100 ──
    extra_combos = [
        # Gas specifically (user's reported issue)
        ("Gas", "2024-03-26", max_date, "All"),
        ("Gas", "2024-01-01", "2024-12-31", "All"),
        ("Gas & Electric", "2026-01-01", "2026-03-31", "All"),
        # Single months with specific categories
        ("Groceries", "2026-03-01", "2026-03-31", "All"),
        ("Groceries", "2025-12-01", "2025-12-31", "All"),
        ("Shopping", "2025-07-01", "2025-07-31", "All"),
        ("Restaurants & Bars", "2025-12-01", "2025-12-31", "All"),
        ("Coffee Shops", "2026-03-01", "2026-03-31", "All"),
        ("Education", "2026-03-01", "2026-03-31", "All"),
        ("Medical", "2026-03-01", "2026-03-31", "All"),
        # Account-specific category combos
        ("Groceries", "2025-01-01", "2025-12-31", "chase_4730"),
        ("Shopping", "2025-01-01", "2025-12-31", "chase_4730"),
        ("Gas & Electric", min_date, max_date, "joint_checking"),
        ("Student Loans", min_date, max_date, "joint_checking"),
        # Search + category combo
        ("Groceries", min_date, max_date, "All"),
        ("Clothing", "2025-01-01", "2025-12-31", "All"),
    ]
    for cat, s, e, acct in extra_combos:
        tid += 1
        tests.append({
            "id": tid,
            "desc": f"{s[:7]}..{e[:7]} | {cat} | {acct} | hide=True",
            "start": s, "end": e,
            "account": acct, "category": cat,
            "hide_transfers": True, "search": "",
        })

    return tests[:100]


# ── Runner ───────────────────────────────────────────────────────────────

def run_tests():
    conn = database.get_connection()
    tests = generate_100_tests(conn)

    print("=" * 100)
    print(f"TRANSACTIONS TAB VALIDATION — {len(tests)} TESTS")
    print("=" * 100)

    passed = 0
    failed = 0
    failures = []

    for t in tests:
        tid = t["id"]
        desc = t["desc"]

        # Method 1: Simulate the DataFrame logic from views/transactions.py
        sim = simulate_transactions_tab(
            conn, t["start"], t["end"], t["account"], t["category"],
            t["hide_transfers"], t["search"],
        )

        # Method 2: Direct SQL query (independent validation)
        db = direct_db_query(
            conn, t["start"], t["end"], t["account"], t["category"],
            t["hide_transfers"], t["search"],
        )

        # Compare
        sum_match = abs(sim["total_spent"] - db["total_spent"]) < 0.02
        count_match = sim["txn_count"] == db["txn_count"]
        expense_match = sim["expense_count"] == db["expense_count"]

        # Cross-check category totals
        cat_match = True
        for cat_name in set(list(sim["category_totals"].keys()) + list(db["category_totals"].keys())):
            s_val = sim["category_totals"].get(cat_name, 0)
            d_val = db["category_totals"].get(cat_name, 0)
            if abs(s_val - d_val) > 0.02:
                cat_match = False
                break

        all_pass = sum_match and count_match and expense_match and cat_match
        status = "PASS" if all_pass else "FAIL"

        if all_pass:
            passed += 1
        else:
            failed += 1
            failures.append(t)

        # Print result
        if not all_pass:
            print(f"\n{'─' * 100}")
            print(f"TEST {tid:03d} [{status}]: {desc}")
            print(f"  Sim:  total=${sim['total_spent']:>12,.2f}  txns={sim['txn_count']:>5}  expenses={sim['expense_count']:>5}")
            print(f"  DB:   total=${db['total_spent']:>12,.2f}  txns={db['txn_count']:>5}  expenses={db['expense_count']:>5}")
            if not sum_match:
                print(f"  MISMATCH: total_spent differs by ${abs(sim['total_spent'] - db['total_spent']):,.2f}")
            if not count_match:
                print(f"  MISMATCH: txn_count sim={sim['txn_count']} vs db={db['txn_count']}")
            if not cat_match:
                for cn in set(list(sim["category_totals"].keys()) + list(db["category_totals"].keys())):
                    sv = sim["category_totals"].get(cn, 0)
                    dv = db["category_totals"].get(cn, 0)
                    if abs(sv - dv) > 0.02:
                        print(f"  MISMATCH: category '{cn}' sim=${sv:,.2f} vs db=${dv:,.2f}")
        else:
            cats_shown = len(sim["category_totals"])
            print(f"  TEST {tid:03d} [PASS]: {desc[:60]:<60} ${sim['total_spent']:>10,.2f} | {sim['txn_count']:>4} txns | {cats_shown:>2} cats")

    conn.close()

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'=' * 100}")
    print(f"SUMMARY: {passed} PASSED / {failed} FAILED / {len(tests)} TOTAL")
    print(f"{'=' * 100}")

    if failures:
        print(f"\nFAILED TESTS:")
        for f in failures:
            print(f"  #{f['id']:03d}: {f['desc']}")

    # Save results
    results = []
    conn2 = database.get_connection()
    for t in tests:
        sim = simulate_transactions_tab(
            conn2, t["start"], t["end"], t["account"], t["category"],
            t["hide_transfers"], t["search"],
        )
        db = direct_db_query(
            conn2, t["start"], t["end"], t["account"], t["category"],
            t["hide_transfers"], t["search"],
        )
        results.append({
            "id": t["id"],
            "desc": t["desc"],
            "sim_total": sim["total_spent"],
            "db_total": db["total_spent"],
            "sim_txns": sim["txn_count"],
            "db_txns": db["txn_count"],
            "match": abs(sim["total_spent"] - db["total_spent"]) < 0.02 and sim["txn_count"] == db["txn_count"],
        })
    conn2.close()

    with open("test_transactions_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to test_transactions_results.json")

    return passed, failed


if __name__ == "__main__":
    run_tests()
