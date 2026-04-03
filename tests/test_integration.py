"""Integration test — connects to real DB if available."""

import os
import pytest

REAL_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "expenses.db")


@pytest.mark.skipif(not os.path.exists(REAL_DB), reason="Real DB not available")
class TestRealDatabase:
    """Smoke tests against the production database."""

    @pytest.fixture(autouse=True)
    def real_conn(self):
        import database
        self.conn = database.get_connection(REAL_DB)
        yield
        self.conn.close()

    def test_filtered_breakdown_excludes_transfers(self):
        """Verify excluded categories are absent from filtered breakdown."""
        from shared.filters import get_filtered_breakdown, get_excluded_categories
        excluded = get_excluded_categories(self.conn)
        months = self.conn.execute(
            "SELECT DISTINCT strftime('%Y-%m', date) as month FROM transactions ORDER BY month DESC LIMIT 1"
        ).fetchall()
        if not months:
            pytest.skip("No transactions in DB")
        month = months[0]["month"]
        breakdown = get_filtered_breakdown(self.conn, month)
        for c in breakdown:
            assert c["category"] not in excluded, f"Excluded category {c['category']} in breakdown"

    def test_effective_fixed_positive(self):
        """Effective fixed total should be a positive number."""
        import database
        eft = database.get_effective_fixed_total(self.conn)
        assert eft > 0

    def test_savings_formula_sanity(self):
        """Savings formula should produce a number in a reasonable range."""
        import database
        import models
        from shared.filters import get_filtered_breakdown, get_fixed_categories

        months = database.get_available_months(self.conn)
        if not months:
            pytest.skip("No months available")
        month = months[0]
        y, m = month.split("-")

        income_data = models.get_income_for_month(int(y), int(m))
        monthly_income = income_data["total_income"] - income_data["kero_bonus"] - income_data["maggie_bonus"]
        effective_fixed = database.get_effective_fixed_total(self.conn)
        breakdown = get_filtered_breakdown(self.conn, month)
        fixed_cats = get_fixed_categories(self.conn)
        flex = sum(abs(c["total"]) for c in breakdown if c["category"] not in fixed_cats)

        saved = monthly_income - effective_fixed - flex
        # Sanity: savings should be between -50k and +50k
        assert -50000 < saved < 50000, f"Savings {saved} seems unreasonable"

    def test_category_config_has_excluded(self):
        """DB should have excluded categories configured."""
        import database
        excluded = database.get_categories_by_type(self.conn, "exclude")
        assert len(excluded) > 0
        # At minimum, Transfer and Credit Card Payment should be excluded
        excluded_set = set(excluded)
        assert "Transfer" in excluded_set or "Transfers & Payments" in excluded_set
