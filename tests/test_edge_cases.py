"""Edge case tests — zero data, refunds, budget caps, boundary conditions."""

import database
from shared.filters import get_filtered_breakdown, get_fixed_categories


class TestZeroTransactionMonth:
    """Handle months with no data gracefully."""

    def test_empty_breakdown(self, conn):
        """A month with no transactions should return empty list."""
        breakdown = get_filtered_breakdown(conn, "2025-06")
        assert breakdown == []

    def test_empty_breakdown_no_division_error(self, conn):
        """Summing an empty breakdown should be zero, not an error."""
        breakdown = get_filtered_breakdown(conn, "2025-06")
        total = sum(abs(c["total"]) for c in breakdown)
        assert total == 0


class TestRefunds:
    """Verify refunds (positive amounts) don't contaminate expense calculations."""

    def test_refunds_excluded_from_expense_breakdown(self, conn):
        """get_monthly_category_breakdown only includes amount < 0."""
        breakdown = database.get_monthly_category_breakdown(conn, "2026-03")
        for row in breakdown:
            assert row["total"] < 0

    def test_refund_not_counted_as_expense(self, conn):
        """The $30 Shopping refund in March should not reduce Shopping expenses."""
        breakdown = database.get_monthly_category_breakdown(conn, "2026-03")
        by_cat = {c["category"]: c for c in breakdown}
        # Shopping has -75 expense, the +30 refund should NOT be in here
        assert by_cat["Shopping"]["total"] == -75


class TestBudgetCaps:
    """Verify fixed category budget caps prevent over-counting."""

    def test_cap_limits_category_total(self, conn):
        """If a category exceeds its monthly_budget, it should be capped."""
        # Gas & Electric budget is 335, insert a huge bill
        conn.execute(
            "INSERT INTO transactions (date, description, raw_description, amount, category, account_id) "
            "VALUES ('2026-03-28', 'Huge electric', 'Huge electric', -1000, 'Gas & Electric', 'checking_1234')"
        )
        conn.commit()

        fixed = database._get_fixed_for_month(conn, "2026-03")
        # Gas & Electric: $335 + $1000 = $1335 in transactions, but capped at $335
        assert fixed["Gas & Electric"] == 335

    def test_no_cap_when_below_budget(self, conn):
        """Categories below their budget should not be affected by cap."""
        fixed = database._get_fixed_for_month(conn, "2026-03")
        # Gas & Electric: $335 in transactions, budget is $335 — should be exact
        assert fixed["Gas & Electric"] == 335

    def test_no_cap_when_no_budget_set(self, conn):
        """Categories without monthly_budget should not be capped."""
        # Groceries is flex with no budget — but let's test a fix category without budget
        conn.execute(
            "INSERT OR REPLACE INTO category_config (name, type, monthly_budget) "
            "VALUES ('Test Fixed', 'fix', NULL)"
        )
        conn.execute(
            "INSERT INTO transactions (date, description, raw_description, amount, category, account_id) "
            "VALUES ('2026-03-28', 'Test', 'Test', -999, 'Test Fixed', 'checking_1234')"
        )
        conn.commit()

        fixed = database._get_fixed_for_month(conn, "2026-03")
        assert fixed["Test Fixed"] == 999  # No cap applied


class TestExcludedOnlyMonth:
    """A month where all transactions are excluded categories."""

    def test_returns_empty_filtered_breakdown(self, conn):
        """If only excluded transactions exist, filtered breakdown should be empty."""
        # Insert only excluded transactions in a new month
        conn.execute(
            "INSERT INTO transactions (date, description, raw_description, amount, category, account_id) "
            "VALUES ('2025-09-01', 'CC Pay', 'CC Pay', -3000, 'Credit Card Payment', 'checking_1234')"
        )
        conn.execute(
            "INSERT INTO transactions (date, description, raw_description, amount, category, account_id) "
            "VALUES ('2025-09-15', 'Transfer', 'Transfer', -1000, 'Transfer', 'checking_1234')"
        )
        conn.commit()

        breakdown = get_filtered_breakdown(conn, "2025-09")
        assert breakdown == []
