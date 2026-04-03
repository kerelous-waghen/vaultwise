"""Test fixtures for VaultWise expenses tracker."""

import os
import sys
import tempfile

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database


@pytest.fixture
def db_path(tmp_path):
    """Returns a temp DB path."""
    return str(tmp_path / "test_expenses.db")


@pytest.fixture
def conn(db_path):
    """Provides an initialized in-memory-like SQLite connection with schema + seed data."""
    database.init_db(db_path)
    c = database.get_connection(db_path)

    # Seed category_config
    categories = [
        ("Mortgage", "fix", 7100),
        ("Insurance", "fix", 552),
        ("Student Loans", "fix", 518),
        ("Gas & Electric", "fix", 335),
        ("Phone", "fix", 144),
        ("Internet & Cable", "fix", 67),
        ("Groceries", "flex", None),
        ("Restaurants & Bars", "flex", None),
        ("Shopping", "flex", None),
        ("Entertainment & Recreation", "flex", None),
        ("Coffee Shops", "flex", None),
        ("Transfers & Payments", "exclude", None),
        ("Credit Card Payment", "exclude", None),
        ("Transfer", "exclude", None),
        ("Paychecks", "exclude", None),
    ]
    for name, cat_type, budget in categories:
        c.execute(
            "INSERT OR REPLACE INTO category_config (name, type, monthly_budget) VALUES (?, ?, ?)",
            (name, cat_type, budget),
        )
    c.commit()

    # Seed a statement
    c.execute(
        "INSERT INTO statements (filename, account_id, period_start, period_end, sha256) "
        "VALUES ('test.csv', 'checking_1234', '2026-03-01', '2026-03-31', 'abc123')"
    )
    c.commit()
    stmt_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Seed 3 months of transactions
    txns = [
        # March 2026 — Fixed
        ("2026-03-01", "Mortgage payment", "Mortgage payment", -7100, "Mortgage", "checking_1234", stmt_id),
        ("2026-03-05", "State Farm", "State Farm", -552, "Insurance", "checking_1234", stmt_id),
        ("2026-03-10", "Student loan", "Student loan", -518, "Student Loans", "checking_1234", stmt_id),
        ("2026-03-15", "PSE bill", "PSE bill", -335, "Gas & Electric", "checking_1234", stmt_id),
        # March 2026 — Flex
        ("2026-03-02", "Safeway", "Safeway groceries", -150, "Groceries", "checking_1234", stmt_id),
        ("2026-03-08", "Target", "Target shopping", -75, "Shopping", "checking_1234", stmt_id),
        ("2026-03-12", "Olive Garden", "Olive Garden", -60, "Restaurants & Bars", "checking_1234", stmt_id),
        ("2026-03-20", "Starbucks", "Starbucks", -12, "Coffee Shops", "checking_1234", stmt_id),
        # March 2026 — Excluded (should be filtered out)
        ("2026-03-01", "CC Payment", "CC Payment", -5000, "Credit Card Payment", "checking_1234", stmt_id),
        ("2026-03-15", "Transfer to savings", "Transfer to savings", -2000, "Transfer", "checking_1234", stmt_id),
        # March 2026 — Income (positive)
        ("2026-03-01", "Paycheck", "Paycheck deposit", 5000, "Paychecks", "checking_1234", stmt_id),
        # March 2026 — Refund (positive in expense category)
        ("2026-03-25", "Target refund", "Target return", 30, "Shopping", "checking_1234", stmt_id),

        # February 2026 — Fixed
        ("2026-02-01", "Mortgage payment", "Feb mortgage", -7100, "Mortgage", "checking_1234", stmt_id),
        ("2026-02-05", "State Farm", "Feb insurance", -552, "Insurance", "checking_1234", stmt_id),
        ("2026-02-10", "Student loan", "Feb student loan", -518, "Student Loans", "checking_1234", stmt_id),
        # February 2026 — Flex
        ("2026-02-03", "Costco", "Costco groceries", -200, "Groceries", "checking_1234", stmt_id),
        ("2026-02-14", "Date night", "Restaurant", -80, "Restaurants & Bars", "checking_1234", stmt_id),
        # February 2026 — Excluded
        ("2026-02-01", "CC Payment", "Feb CC", -3000, "Credit Card Payment", "checking_1234", stmt_id),

        # January 2026 — Fixed
        ("2026-01-01", "Mortgage payment", "Jan mortgage", -7100, "Mortgage", "checking_1234", stmt_id),
        ("2026-01-05", "State Farm", "Jan insurance", -552, "Insurance", "checking_1234", stmt_id),
        # January 2026 — Flex
        ("2026-01-10", "Grocery store", "Jan groceries", -180, "Groceries", "checking_1234", stmt_id),
        ("2026-01-20", "Amazon", "Amazon order", -45, "Shopping", "checking_1234", stmt_id),
    ]
    for date_str, desc, raw_desc, amount, cat, acct, sid in txns:
        c.execute(
            "INSERT INTO transactions (date, description, raw_description, amount, category, account_id, statement_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (date_str, desc, raw_desc, amount, cat, acct, sid),
        )
    c.commit()

    yield c
    c.close()


# Known ground truth for test data
GROUND_TRUTH = {
    "2026-03": {
        "fixed_actual": 7100 + 552 + 518 + 335,  # 8505
        "flex_actual": 150 + 75 + 60 + 12,  # 297
        "excluded_actual": 5000 + 2000,  # 7000
        "budget_floor": 7100 + 552 + 518 + 335 + 144 + 67,  # 8716
    },
    "2026-02": {
        "fixed_actual": 7100 + 552 + 518,  # 8170
        "flex_actual": 200 + 80,  # 280
        "excluded_actual": 3000,
    },
    "2026-01": {
        "fixed_actual": 7100 + 552,  # 7652
        "flex_actual": 180 + 45,  # 225
        "excluded_actual": 0,
    },
}
