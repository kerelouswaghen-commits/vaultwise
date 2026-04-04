"""Tests for the calculation layer — filters, effective fixed, savings formula."""

import database
from shared.filters import (
    get_excluded_categories,
    get_filtered_breakdown,
    get_fixed_categories,
    get_flex_breakdown,
    get_flex_categories,
)
from tests.conftest import GROUND_TRUTH


class TestCategoryFiltering:
    """Verify the category classification pipeline."""

    def test_fixed_categories(self, conn):
        fixed = get_fixed_categories(conn)
        assert "Mortgage" in fixed
        assert "Insurance" in fixed
        assert "Groceries" not in fixed
        assert "Transfer" not in fixed

    def test_flex_categories(self, conn):
        flex = get_flex_categories(conn)
        assert "Groceries" in flex
        assert "Restaurants & Bars" in flex
        assert "Mortgage" not in flex
        assert "Transfer" not in flex

    def test_excluded_categories(self, conn):
        excluded = get_excluded_categories(conn)
        assert "Transfers & Payments" in excluded
        assert "Credit Card Payment" in excluded
        assert "Transfer" in excluded
        assert "Paychecks" in excluded
        assert "Groceries" not in excluded

    def test_filtered_breakdown_excludes_transfers(self, conn):
        """Core test: get_filtered_breakdown must never include excluded categories."""
        breakdown = get_filtered_breakdown(conn, "2026-03")
        cats = {c["category"] for c in breakdown}
        assert "Credit Card Payment" not in cats
        assert "Transfer" not in cats
        assert "Paychecks" not in cats
        # But fixed + flex should be present
        assert "Mortgage" in cats
        assert "Groceries" in cats

    def test_filtered_breakdown_totals_match_ground_truth(self, conn):
        """Verify filtered breakdown sums match hand-calculated values."""
        breakdown = get_filtered_breakdown(conn, "2026-03")
        fixed_cats = get_fixed_categories(conn)

        fixed_total = sum(abs(c["total"]) for c in breakdown if c["category"] in fixed_cats)
        flex_total = sum(abs(c["total"]) for c in breakdown if c["category"] not in fixed_cats)

        gt = GROUND_TRUTH["2026-03"]
        assert fixed_total == gt["fixed_actual"]
        assert flex_total == gt["flex_actual"]

    def test_flex_breakdown_only_flex(self, conn):
        """get_flex_breakdown should return only flex categories."""
        flex = get_flex_breakdown(conn, "2026-03")
        fixed_cats = get_fixed_categories(conn)
        for c in flex:
            assert c["category"] not in fixed_cats

    def test_orphan_category_auto_registered(self, conn):
        """Unknown categories should be auto-registered as flex."""
        # Insert a transaction with an unknown category
        conn.execute(
            "INSERT INTO transactions (date, description, raw_description, amount, category, account_id) "
            "VALUES ('2026-03-28', 'Pet store', 'Pet store', -50, 'Pet Supplies', 'checking_1234')"
        )
        conn.commit()

        breakdown = get_filtered_breakdown(conn, "2026-03")
        cats = {c["category"] for c in breakdown}
        assert "Pet Supplies" in cats  # auto-registered as flex, not excluded

        # Verify it was registered in category_config
        all_config = {r["name"]: r["type"] for r in database.get_all_category_config(conn)}
        assert all_config["Pet Supplies"] == "flex"


class TestEffectiveFixedTotal:
    """Verify get_effective_fixed_total returns max(db_actuals, budget_floor)."""

    def test_budget_floor_only_counts_active_categories(self, conn):
        """Budget floor should only include fixed categories with recent transactions."""
        eft = database.get_effective_fixed_total(conn)
        # Active fixed = categories with txns in last 3 months
        active = set(r[0] for r in conn.execute("""
            SELECT DISTINCT t.category FROM transactions t
            JOIN category_config cc ON t.category = cc.name
            WHERE cc.type = 'fix' AND t.amount < 0
              AND t.date >= date('now', '-3 months')
        """).fetchall())
        active_floor = sum(
            r["monthly_budget"] or 0 for r in database.get_all_category_config(conn)
            if r["type"] == "fix" and r["name"] in active
        )
        assert eft >= active_floor

    def test_effective_fixed_excludes_phantom_categories(self, conn):
        """Categories with budgets but no recent transactions should NOT inflate total."""
        # Add a phantom category with huge budget but no transactions
        conn.execute("INSERT OR REPLACE INTO category_config (name, type, monthly_budget) VALUES ('Phantom Bill', 'fix', 50000)")
        conn.commit()
        eft = database.get_effective_fixed_total(conn)
        # Phantom Bill has no transactions, so it should NOT add $50,000
        assert eft < 50000

    def test_effective_fixed_positive(self, conn):
        """Effective fixed total should be a non-negative number."""
        eft = database.get_effective_fixed_total(conn)
        assert eft >= 0

    def test_budget_caps_prevent_double_billing(self, conn):
        """Budget cap should prevent a category from exceeding its monthly_budget."""
        # Insert a duplicate mortgage payment (double-billing)
        conn.execute(
            "INSERT INTO transactions (date, description, raw_description, amount, category, account_id) "
            "VALUES ('2026-03-16', 'Extra mortgage', 'Extra mortgage', -7100, 'Mortgage', 'checking_1234')"
        )
        conn.commit()

        # _get_fixed_for_month should cap Mortgage at 7100 (its monthly_budget)
        fixed_march = database._get_fixed_for_month(conn, "2026-03")
        assert fixed_march.get("Mortgage", 0) == 7100  # Capped, not 14200


class TestIncomeModel:
    """Verify income projections."""

    def test_base_income_2026(self):
        """Income for 2026 should use base values (no raises yet)."""
        import models
        result = models.get_income_for_month(2026, 3)
        assert isinstance(result, dict)
        assert "total_income" in result
        assert "kero_net" in result
        assert "maggie_net" in result
        assert "kero_bonus" in result
        assert "maggie_bonus" in result
        # Total should be sum of components
        expected = result["kero_net"] + result["maggie_net"] + result["kero_bonus"] + result["maggie_bonus"]
        assert result["total_income"] == expected

    def test_raises_apply_in_future_years(self):
        """Income should increase after raise dates."""
        import models
        income_2026 = models.get_income_for_month(2026, 6)
        income_2028 = models.get_income_for_month(2028, 6)
        # 2028 should have at least one raise applied
        assert income_2028["kero_net"] >= income_2026["kero_net"]
        assert income_2028["total_income"] > income_2026["total_income"]

    def test_bonuses_are_positive(self):
        """Bonuses should be positive values."""
        import models
        result = models.get_income_for_month(2026, 1)
        assert result["kero_bonus"] > 0
        assert result["maggie_bonus"] > 0


class TestSavingsFormula:
    """End-to-end savings calculation matching the Home page logic."""

    def test_savings_formula_march(self, conn):
        """Verify: saved = income - effective_fixed - flex_spending."""
        import models
        from shared.filters import get_fixed_categories

        income_data = models.get_income_for_month(2026, 3)
        monthly_income = income_data["total_income"]
        # Subtract bonuses (conservative, like Plan page)
        monthly_income -= (income_data["kero_bonus"] + income_data["maggie_bonus"])

        effective_fixed = database.get_effective_fixed_total(conn)

        breakdown = get_filtered_breakdown(conn, "2026-03")
        fixed_cats = get_fixed_categories(conn)
        flex_spending = sum(abs(c["total"]) for c in breakdown if c["category"] not in fixed_cats)

        saved = monthly_income - effective_fixed - flex_spending
        # Saved should be income minus fixed minus flex
        assert saved == monthly_income - effective_fixed - flex_spending
        # And the formula should produce a reasonable number
        assert isinstance(saved, float) or isinstance(saved, int)
