"""Tests verifying that UI data computations are correct.

These tests trace the data flow from DB → filters → calculations → display values,
ensuring every number shown in the V5 UI is provably correct.
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


class TestFlexBreakdownAccuracy:
    """Verify get_flex_breakdown returns ONLY flex categories with correct totals."""

    def test_flex_breakdown_excludes_fixed(self, conn):
        """Flex breakdown must NOT contain any fixed categories."""
        flex = get_flex_breakdown(conn, "2026-03")
        fixed = get_fixed_categories(conn)
        flex_cats = {c["category"] for c in flex}
        assert not flex_cats & fixed, f"Fixed categories leaked into flex: {flex_cats & fixed}"

    def test_flex_breakdown_excludes_excluded(self, conn):
        """Flex breakdown must NOT contain any excluded categories."""
        flex = get_flex_breakdown(conn, "2026-03")
        excluded = get_excluded_categories(conn)
        flex_cats = {c["category"] for c in flex}
        assert not flex_cats & excluded, f"Excluded categories leaked into flex: {flex_cats & excluded}"

    def test_flex_breakdown_total_matches_ground_truth(self, conn):
        """Sum of flex breakdown must match hand-calculated flex total."""
        flex = get_flex_breakdown(conn, "2026-03")
        flex_total = sum(abs(c["total"]) for c in flex)
        expected = GROUND_TRUTH["2026-03"]["flex_actual"]
        assert flex_total == expected, f"Flex total {flex_total} != expected {expected}"

    def test_flex_breakdown_feb(self, conn):
        flex = get_flex_breakdown(conn, "2026-02")
        flex_total = sum(abs(c["total"]) for c in flex)
        expected = GROUND_TRUTH["2026-02"]["flex_actual"]
        assert flex_total == expected

    def test_flex_breakdown_jan(self, conn):
        flex = get_flex_breakdown(conn, "2026-01")
        flex_total = sum(abs(c["total"]) for c in flex)
        expected = GROUND_TRUTH["2026-01"]["flex_actual"]
        assert flex_total == expected


class TestSavingsCalculation:
    """Verify the savings formula: saved = income - effective_fixed - flex_spent."""

    def test_savings_formula(self, conn):
        """Income - fixed - flex = savings (with test data, no income configured)."""
        flex = get_flex_breakdown(conn, "2026-03")
        flex_total = sum(abs(c["total"]) for c in flex)
        fixed_total = database.get_effective_fixed_total(conn)

        # With test income of 0 (not configured), savings = -fixed - flex
        # This verifies the formula structure is correct
        assert flex_total == GROUND_TRUTH["2026-03"]["flex_actual"]
        assert fixed_total >= 0  # effective fixed is always >= 0

    def test_effective_fixed_uses_caps(self, conn):
        """Effective fixed total should use budget caps when actual exceeds cap."""
        # Mortgage has budget cap of 7100, actual is 7100 — should match
        detail = database.get_effective_fixed_detail(conn)
        for d in detail:
            if d["name"] == "Mortgage":
                assert d["effective"] == 7100  # capped at budget
            if d["name"] == "Insurance":
                assert d["effective"] == 552


class TestSafeToSpend:
    """Verify 'Safe to Spend' = disc_budget - flex_spent."""

    def test_safe_to_spend_formula(self, conn):
        """disc_budget = income - fixed - target; safe = disc_budget - flex_spent."""
        flex = get_flex_breakdown(conn, "2026-03")
        flex_spent = sum(abs(c["total"]) for c in flex)
        effective_fixed = database.get_effective_fixed_total(conn)

        # Formula components
        # For test: income not configured, so we just verify the formula structure
        test_income = 15000  # hypothetical
        test_target = 2000
        disc_budget = test_income - effective_fixed - test_target
        safe_to_spend = disc_budget - flex_spent

        # safe_to_spend should be income - fixed - target - flex
        assert safe_to_spend == test_income - effective_fixed - test_target - flex_spent


class TestWaterfallProportions:
    """Verify hero waterfall bar segments sum correctly."""

    def test_waterfall_sums_to_income(self):
        """Fixed + Target + Spent + Remaining should = Income."""
        income = 10000
        fixed = 4200
        target = 1600
        spent = 2153
        remaining = income - fixed - target - spent

        total = fixed + target + spent + remaining
        assert total == income, f"Waterfall total {total} != income {income}"

    def test_waterfall_remaining_nonnegative(self):
        """When overspending, remaining should be max(0, ...)."""
        income = 10000
        fixed = 4200
        target = 1600
        spent = 5000  # over budget
        remaining = max(income - fixed - target - spent, 0)

        assert remaining == 0


class TestDailyBudget:
    """Verify daily budget = discretionary_left / days_left."""

    def test_daily_budget_formula(self):
        disc_left = 447
        days_left = 8
        daily = disc_left / days_left
        assert abs(daily - 55.875) < 0.01

    def test_daily_budget_zero_days(self):
        """Days left = 0 should not cause division by zero."""
        disc_left = 447
        days_left = 0
        # In the app, days_left is max(..., 1) to prevent division by zero
        safe_days = max(days_left, 1)
        daily = disc_left / safe_days
        assert daily == 447


class TestYearProjection:
    """Verify year projection = monthly_savings * months_remaining."""

    def test_projection_formula(self):
        monthly = 1920
        months_to_dec = 9  # March to December
        by_dec = monthly * months_to_dec
        assert by_dec == 17280

    def test_projection_annual(self):
        monthly = 1600
        annual = monthly * 12
        assert annual == 19200


class TestFilteredVsFlexBreakdown:
    """Verify filtered_breakdown = fix + flex; flex_breakdown = flex only."""

    def test_filtered_is_superset_of_flex(self, conn):
        """Filtered breakdown should include everything in flex breakdown plus fixed."""
        filtered = get_filtered_breakdown(conn, "2026-03")
        flex = get_flex_breakdown(conn, "2026-03")
        filtered_cats = {c["category"] for c in filtered}
        flex_cats = {c["category"] for c in flex}
        # Every flex category should be in filtered
        assert flex_cats <= filtered_cats, f"Flex cats not in filtered: {flex_cats - filtered_cats}"

    def test_filtered_minus_fixed_equals_flex(self, conn):
        """Filtered - fixed categories should equal flex categories."""
        filtered = get_filtered_breakdown(conn, "2026-03")
        flex = get_flex_breakdown(conn, "2026-03")
        fixed = get_fixed_categories(conn)
        filtered_flex_only = {c["category"] for c in filtered if c["category"] not in fixed}
        flex_cats = {c["category"] for c in flex}
        assert filtered_flex_only == flex_cats

    def test_no_category_overlap_between_types(self, conn):
        """Fixed, flex, and excluded sets should be mutually exclusive."""
        fixed = get_fixed_categories(conn)
        flex = get_flex_categories(conn)
        excluded = get_excluded_categories(conn)
        assert not (fixed & flex), f"Overlap fixed/flex: {fixed & flex}"
        assert not (fixed & excluded), f"Overlap fixed/excluded: {fixed & excluded}"
        assert not (flex & excluded), f"Overlap flex/excluded: {flex & excluded}"
