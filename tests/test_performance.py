"""Performance tests — verify optimized queries return correct data.

Tests the bulk query functions against the per-item equivalents
to ensure optimizations don't change results.
"""

import database
from shared.filters import get_flex_breakdown, get_flex_categories


class TestBulkWeeklyQuery:
    """Verify get_weekly_category_spending matches per-week queries."""

    def test_bulk_matches_individual_march(self, conn):
        """Bulk weekly query must match individual per-week queries for March."""
        from datetime import date, timedelta

        month_start = "2026-03-01"
        month_end = "2026-03-31"

        # Bulk query (optimized)
        bulk = database.get_weekly_category_spending(conn, month_start, month_end)

        # Individual queries (old way)
        ws = date(2026, 3, 1)
        wn = 1
        individual = {}
        while ws <= date(2026, 3, 31):
            we = min(ws + timedelta(days=6), date(2026, 3, 31))
            rows = conn.execute(
                "SELECT category, SUM(ABS(amount)) as total FROM transactions "
                "WHERE date >= ? AND date <= ? AND amount < 0 GROUP BY category",
                (ws.isoformat(), we.isoformat()),
            ).fetchall()
            for r in rows:
                individual[(r["category"], wn)] = r["total"]
            ws = we + timedelta(days=1)
            wn += 1

        # Compare: every individual result must be in bulk
        for key, val in individual.items():
            bulk_val = bulk.get(key, 0)
            assert abs(bulk_val - val) < 0.01, \
                f"Mismatch for {key}: bulk={bulk_val}, individual={val}"


class TestBulkMonthlyFlexTotals:
    """Verify get_monthly_flex_totals matches per-month get_flex_breakdown."""

    def test_bulk_matches_individual(self, conn):
        """Bulk monthly flex totals must match sum of get_flex_breakdown per month."""
        bulk = database.get_monthly_flex_totals(conn, months=3)
        bulk_map = {r["month"]: r["flex_total"] for r in bulk}

        for month in ["2026-03", "2026-02", "2026-01"]:
            flex = get_flex_breakdown(conn, month)
            individual_total = sum(abs(c["total"]) for c in flex)
            bulk_total = bulk_map.get(month, 0)
            assert abs(bulk_total - individual_total) < 0.01, \
                f"Month {month}: bulk={bulk_total}, individual={individual_total}"

    def test_returns_newest_first(self, conn):
        """Results should be ordered newest month first."""
        bulk = database.get_monthly_flex_totals(conn, months=3)
        if len(bulk) >= 2:
            assert bulk[0]["month"] >= bulk[1]["month"]


class TestCompositeIndex:
    """Verify the composite index exists after init_db."""

    def test_index_exists(self, conn):
        """idx_txn_date_cat_amt should exist."""
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='transactions'"
        ).fetchall()
        idx_names = {r["name"] for r in indexes}
        assert "idx_txn_date_cat_amt" in idx_names

    def test_catconfig_type_index_exists(self, conn):
        """idx_catconfig_type should exist."""
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='category_config'"
        ).fetchall()
        idx_names = {r["name"] for r in indexes}
        assert "idx_catconfig_type" in idx_names


class TestQueryReductionIntegrity:
    """Verify that reusing cached data produces correct results."""

    def test_flex_breakdown_idempotent(self, conn):
        """Calling get_flex_breakdown twice returns identical results."""
        r1 = get_flex_breakdown(conn, "2026-03")
        r2 = get_flex_breakdown(conn, "2026-03")
        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a["category"] == b["category"]
            assert a["total"] == b["total"]

    def test_effective_fixed_idempotent(self, conn):
        """Calling get_effective_fixed_total twice returns identical results."""
        r1 = database.get_effective_fixed_total(conn)
        r2 = database.get_effective_fixed_total(conn)
        assert r1 == r2
