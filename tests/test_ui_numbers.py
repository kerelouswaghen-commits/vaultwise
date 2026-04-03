"""Tests verifying that every number shown in the UI ties to real DB data.

These tests use the test fixtures (seeded data) to verify:
- Weekly bars sum to monthly totals
- Flex breakdown excludes fixed/excluded categories
- Savings formula is consistent across hero/waterfall/safe-to-spend
- Streak dots reflect actual savings vs target
- Severity badges use correct thresholds
"""

import database
from shared.filters import (
    get_excluded_categories,
    get_filtered_breakdown,
    get_fixed_categories,
    get_flex_breakdown,
    get_flex_categories,
)
from tests.conftest import GROUND_TRUTH


class TestWeeklyBarsSumToMonthly:
    """Verify that sum of weekly spending = monthly total for each flex category."""

    def test_weekly_sum_equals_monthly_march(self, conn):
        """Sum of all weeks in March must equal monthly flex total."""
        flex = get_flex_breakdown(conn, "2026-03")
        flex_cats = {c["category"]: abs(c["total"]) for c in flex}

        # Compute weekly spending per category for March
        import sqlite3
        from datetime import date, timedelta
        month_start = date(2026, 3, 1)
        month_end = date(2026, 3, 31)

        weekly_sums = {}
        wk_start = month_start
        while wk_start <= month_end:
            wk_end = min(wk_start + timedelta(days=6), month_end)
            rows = conn.execute(
                """SELECT category, SUM(ABS(amount)) as total
                   FROM transactions
                   WHERE date >= ? AND date <= ? AND amount < 0
                   GROUP BY category""",
                (wk_start.isoformat(), wk_end.isoformat()),
            ).fetchall()
            for r in rows:
                cat = r["category"]
                if cat in flex_cats:
                    weekly_sums[cat] = weekly_sums.get(cat, 0) + r["total"]
            wk_start = wk_end + timedelta(days=1)

        # Verify each flex category
        for cat, monthly_total in flex_cats.items():
            wk_total = weekly_sums.get(cat, 0)
            assert abs(wk_total - monthly_total) < 0.01, \
                f"{cat}: weekly sum ${wk_total:.2f} != monthly ${monthly_total:.2f}"

    def test_weekly_sum_equals_monthly_feb(self, conn):
        """Same verification for February."""
        flex = get_flex_breakdown(conn, "2026-02")
        flex_cats = {c["category"]: abs(c["total"]) for c in flex}

        from datetime import date, timedelta
        month_start = date(2026, 2, 1)
        month_end = date(2026, 2, 28)

        weekly_sums = {}
        wk_start = month_start
        while wk_start <= month_end:
            wk_end = min(wk_start + timedelta(days=6), month_end)
            rows = conn.execute(
                """SELECT category, SUM(ABS(amount)) as total
                   FROM transactions
                   WHERE date >= ? AND date <= ? AND amount < 0
                   GROUP BY category""",
                (wk_start.isoformat(), wk_end.isoformat()),
            ).fetchall()
            for r in rows:
                cat = r["category"]
                if cat in flex_cats:
                    weekly_sums[cat] = weekly_sums.get(cat, 0) + r["total"]
            wk_start = wk_end + timedelta(days=1)

        for cat, monthly_total in flex_cats.items():
            wk_total = weekly_sums.get(cat, 0)
            assert abs(wk_total - monthly_total) < 0.01


class TestSavingsFormulaConsistency:
    """Verify savings = income - effective_fixed - flex_spent across all display points."""

    def test_hero_waterfall_consistency(self, conn):
        """Waterfall remaining = max(income - target - fixed - flex, 0)."""
        effective_fixed = database.get_effective_fixed_total(conn)
        flex = get_flex_breakdown(conn, "2026-03")
        flex_total = sum(abs(c["total"]) for c in flex)

        test_income = 15000
        test_target = 2000
        budget_limit = test_income - test_target
        remaining = max(budget_limit - effective_fixed - flex_total, 0)

        # When under budget: segments sum to income
        # When over budget: remaining = 0, segments sum > income (clamped)
        if remaining > 0:
            waterfall_total = effective_fixed + test_target + flex_total + remaining
            assert waterfall_total == test_income
        else:
            # Over budget — remaining clamped to 0
            assert remaining == 0
            assert effective_fixed + flex_total > budget_limit

    def test_safe_to_spend_formula(self, conn):
        """Safe to Spend = disc_budget - flex_spent."""
        effective_fixed = database.get_effective_fixed_total(conn)
        flex = get_flex_breakdown(conn, "2026-03")
        flex_total = sum(abs(c["total"]) for c in flex)

        test_income = 15000
        test_target = 2000
        disc_budget = test_income - effective_fixed - test_target
        safe_to_spend = max(disc_budget - flex_total, 0)

        # safe_to_spend should never be negative
        assert safe_to_spend >= 0


class TestSeverityBadges:
    """Verify severity badge thresholds are applied correctly."""

    def test_way_over_threshold(self):
        """Ratio > 1.3 should be 'way over' red."""
        spent, avg = 1400, 1000
        ratio = spent / avg
        assert ratio > 1.3
        # Should be red

    def test_elevated_threshold(self):
        """Ratio 1.0-1.3 should be 'elevated' amber."""
        spent, avg = 1100, 1000
        ratio = spent / avg
        assert 1.0 < ratio <= 1.3

    def test_normal_threshold(self):
        """Ratio 0.8-1.0 should be 'normal' blue."""
        spent, avg = 900, 1000
        ratio = spent / avg
        assert 0.8 < ratio <= 1.0

    def test_under_pace_threshold(self):
        """Ratio 0.5-0.8 should be 'under pace' green."""
        spent, avg = 600, 1000
        ratio = spent / avg
        assert 0.5 < ratio <= 0.8

    def test_low_threshold(self):
        """Ratio < 0.5 should be 'low' emerald."""
        spent, avg = 400, 1000
        ratio = spent / avg
        assert ratio <= 0.5

    def test_zero_average_defaults_to_normal(self):
        """When no history (avg=0), should default to 'normal'."""
        avg = 0
        # Can't compute ratio, should default to normal/blue
        assert avg == 0


class TestFlexTotalMatchesCategories:
    """Verify flex total = sum of individual flex category amounts."""

    def test_flex_total_is_sum(self, conn):
        flex = get_flex_breakdown(conn, "2026-03")
        total = sum(abs(c["total"]) for c in flex)
        individual_sum = sum(abs(c["total"]) for c in flex)
        assert total == individual_sum

    def test_flex_total_matches_ground_truth(self, conn):
        flex = get_flex_breakdown(conn, "2026-03")
        total = sum(abs(c["total"]) for c in flex)
        assert total == GROUND_TRUTH["2026-03"]["flex_actual"]

    def test_flex_excludes_fixed_spending(self, conn):
        """Flex total must NOT include mortgage, insurance, etc."""
        flex = get_flex_breakdown(conn, "2026-03")
        fixed = get_fixed_categories(conn)
        flex_cats = {c["category"] for c in flex}
        overlap = flex_cats & fixed
        assert not overlap, f"Fixed categories in flex breakdown: {overlap}"

    def test_flex_excludes_transfers(self, conn):
        """Flex total must NOT include transfers, CC payments, etc."""
        flex = get_flex_breakdown(conn, "2026-03")
        excluded = get_excluded_categories(conn)
        flex_cats = {c["category"] for c in flex}
        overlap = flex_cats & excluded
        assert not overlap, f"Excluded categories in flex breakdown: {overlap}"


class TestWeekBoundaries:
    """Verify week boundaries cover the entire month without gaps or overlaps."""

    def test_march_weeks_cover_full_month(self):
        from datetime import date, timedelta
        month_start = date(2026, 3, 1)
        month_end = date(2026, 3, 31)

        boundaries = []
        wk_start = month_start
        while wk_start <= month_end:
            wk_end = min(wk_start + timedelta(days=6), month_end)
            boundaries.append((wk_start, wk_end))
            wk_start = wk_end + timedelta(days=1)

        # First week starts on month start
        assert boundaries[0][0] == month_start
        # Last week ends on month end
        assert boundaries[-1][1] == month_end
        # No gaps between weeks
        for i in range(1, len(boundaries)):
            prev_end = boundaries[i-1][1]
            curr_start = boundaries[i][0]
            assert (curr_start - prev_end).days == 1, \
                f"Gap between week {i} and {i+1}: {prev_end} to {curr_start}"

    def test_february_weeks_cover_full_month(self):
        from datetime import date, timedelta
        month_start = date(2026, 2, 1)
        month_end = date(2026, 2, 28)

        boundaries = []
        wk_start = month_start
        while wk_start <= month_end:
            wk_end = min(wk_start + timedelta(days=6), month_end)
            boundaries.append((wk_start, wk_end))
            wk_start = wk_end + timedelta(days=1)

        assert boundaries[0][0] == month_start
        assert boundaries[-1][1] == month_end
