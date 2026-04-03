"""Centralized category filtering — single source of truth.

All category type logic (fix/flex/exclude) is driven by the `category_config`
database table. No hardcoded category sets anywhere in the codebase.
"""

import database


def get_fixed_categories(conn) -> set:
    """Returns set of category names tagged as 'fix' in DB."""
    return set(database.get_categories_by_type(conn, "fix"))


def get_excluded_categories(conn) -> set:
    """Returns set of category names tagged as 'exclude' in DB."""
    return set(database.get_categories_by_type(conn, "exclude"))


def get_flex_categories(conn) -> set:
    """Returns set of category names that are flex — explicit + unconfigured (default flex)."""
    explicit_flex = set(database.get_categories_by_type(conn, "flex"))
    all_configured = {r["name"] for r in database.get_all_category_config(conn)}
    all_txn_cats = {r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM transactions"
    ).fetchall()}
    return explicit_flex | (all_txn_cats - all_configured)


def get_filtered_breakdown(conn, month_key: str) -> list[dict]:
    """Get monthly category breakdown — only fix + flex categories (excludes 'exclude' type).

    Auto-registers any unknown transaction categories as flex so they don't
    silently fall through the cracks.

    Returns list of dicts with keys: category, total, txn_count.
    """
    raw = database.get_monthly_category_breakdown(conn, month_key)
    excluded = get_excluded_categories(conn)
    # Auto-register orphan categories as flex
    all_configured = {r["name"] for r in database.get_all_category_config(conn)}
    for c in raw:
        if c["category"] not in all_configured:
            database.ensure_category_config(conn, c["category"], "flex")
    return [c for c in raw if c["category"] not in excluded]


def get_flex_breakdown(conn, month_key: str) -> list[dict]:
    """Get monthly category breakdown — only flex categories.

    Returns list of dicts with keys: category, total, txn_count.
    """
    raw = database.get_monthly_category_breakdown(conn, month_key)
    flex = get_flex_categories(conn)
    return [c for c in raw if c["category"] in flex]


def get_fixed_breakdown(conn, month_key: str) -> list[dict]:
    """Get monthly category breakdown — only fix categories.

    Returns list of dicts with keys: category, total, txn_count.
    """
    raw = database.get_monthly_category_breakdown(conn, month_key)
    fixed = get_fixed_categories(conn)
    return [c for c in raw if c["category"] in fixed]
