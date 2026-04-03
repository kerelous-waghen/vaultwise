"""Tests for the database layer — CRUD, dedup, queries."""

import database


class TestTransactionDeduplication:
    """Verify UNIQUE constraint prevents duplicate transactions."""

    def test_exact_duplicate_rejected(self, conn):
        """Inserting the same (date, amount, raw_description, account_id) should fail."""
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO transactions (date, description, raw_description, amount, category, account_id) "
                "VALUES ('2026-03-02', 'Safeway dup', 'Safeway groceries', -150, 'Groceries', 'checking_1234')"
            )

    def test_different_account_not_duplicate(self, conn):
        """Same transaction on different account should be allowed."""
        conn.execute(
            "INSERT INTO transactions (date, description, raw_description, amount, category, account_id) "
            "VALUES ('2026-03-02', 'Safeway', 'Safeway groceries', -150, 'Groceries', 'credit_5678')"
        )
        conn.commit()
        # Should succeed without error

    def test_different_amount_not_duplicate(self, conn):
        """Same description but different amount should be allowed."""
        conn.execute(
            "INSERT INTO transactions (date, description, raw_description, amount, category, account_id) "
            "VALUES ('2026-03-02', 'Safeway', 'Safeway groceries', -151, 'Groceries', 'checking_1234')"
        )
        conn.commit()


class TestMonthlyBreakdown:
    """Verify get_monthly_category_breakdown."""

    def test_returns_only_expenses(self, conn):
        """Should only include amount < 0 rows."""
        breakdown = database.get_monthly_category_breakdown(conn, "2026-03")
        for row in breakdown:
            assert row["total"] < 0  # All totals are negative (expenses)

    def test_includes_excluded_categories(self, conn):
        """Raw breakdown should include ALL categories (filtering is done by shared/filters)."""
        breakdown = database.get_monthly_category_breakdown(conn, "2026-03")
        cats = {c["category"] for c in breakdown}
        assert "Credit Card Payment" in cats
        assert "Transfer" in cats

    def test_category_totals_correct(self, conn):
        """Verify specific category totals."""
        breakdown = database.get_monthly_category_breakdown(conn, "2026-03")
        by_cat = {c["category"]: c for c in breakdown}

        assert abs(by_cat["Mortgage"]["total"]) == 7100
        assert abs(by_cat["Groceries"]["total"]) == 150
        assert by_cat["Groceries"]["txn_count"] == 1

    def test_refunds_not_in_breakdown(self, conn):
        """Positive amounts (refunds) should NOT appear in expense breakdown."""
        breakdown = database.get_monthly_category_breakdown(conn, "2026-03")
        # Shopping has -75 expense and +30 refund, only -75 should be in breakdown
        by_cat = {c["category"]: c for c in breakdown}
        assert by_cat["Shopping"]["total"] == -75  # Only the expense, not net


class TestAvailableMonths:
    """Verify get_available_months ordering."""

    def test_newest_first(self, conn):
        months = database.get_available_months(conn)
        assert months[0] == "2026-03"
        assert months[-1] == "2026-01"

    def test_all_months_present(self, conn):
        months = database.get_available_months(conn)
        assert set(months) == {"2026-01", "2026-02", "2026-03"}


class TestSettings:
    """Verify settings CRUD."""

    def test_get_default(self, conn):
        val = database.get_setting(conn, "nonexistent_key", "fallback")
        assert val == "fallback"

    def test_set_and_get(self, conn):
        database.set_setting(conn, "test_key", "test_value")
        val = database.get_setting(conn, "test_key")
        assert val == "test_value"

    def test_overwrite(self, conn):
        database.set_setting(conn, "test_key", "v1")
        database.set_setting(conn, "test_key", "v2")
        assert database.get_setting(conn, "test_key") == "v2"


class TestCategoryConfig:
    """Verify category config operations."""

    def test_get_categories_by_type(self, conn):
        fix = database.get_categories_by_type(conn, "fix")
        assert "Mortgage" in fix
        assert "Groceries" not in fix

    def test_ensure_category_config_idempotent(self, conn):
        """ensure_category_config should not overwrite existing config."""
        database.ensure_category_config(conn, "Mortgage", "flex")
        # Mortgage was 'fix', ensure should NOT change it (INSERT OR IGNORE)
        types = database.get_categories_by_type(conn, "fix")
        assert "Mortgage" in types

    def test_ensure_category_config_new(self, conn):
        """New categories should be inserted with default type."""
        database.ensure_category_config(conn, "BrandNewCategory", "flex")
        flex = database.get_categories_by_type(conn, "flex")
        assert "BrandNewCategory" in flex

    def test_set_category_type(self, conn):
        """Should be able to reclassify a category."""
        database.set_category_type(conn, "Coffee Shops", "fix")
        fix = database.get_categories_by_type(conn, "fix")
        assert "Coffee Shops" in fix


import pytest
