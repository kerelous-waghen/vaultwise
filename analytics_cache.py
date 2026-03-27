"""
Analytics cache layer — pre-computes and stores all analytics in the database.
Dashboard reads from cache (instant), never runs Prophet/Monte Carlo on the hot path.

Usage:
    - refresh_all(conn): Full recompute → store in category_analytics table
    - get_cached(conn): Read cached results → same shape as analytics.build_statistical_context()
    - invalidate(conn): Mark cache stale (after upload/telegram import)
    - is_stale(conn): Check if cache needs refresh
"""

import json
from datetime import datetime, timedelta
from typing import Optional

import database


# How old the cache can be before we consider it stale
MAX_CACHE_AGE_HOURS = 24


def refresh_all(conn) -> dict:
    """
    Run the full analytics pipeline and store results in category_analytics table.
    Returns the computed analytics dict (same shape as get_cached()).
    """
    import analytics

    # Compute everything
    result = analytics.build_statistical_context(conn)

    # Store global context
    database.upsert_category_analytics(conn, "_global", "context", json.dumps(result, default=str))

    # Store per-category trend + budget data for fast individual lookups
    for cat_budget in result.get("budget_status", []):
        cat_name = cat_budget["category"]
        database.upsert_category_analytics(conn, cat_name, "budget", json.dumps(cat_budget, default=str))

    # Store per-category trend analysis
    # We need to recompute trends individually since build_statistical_context
    # only stores rising/wins — we want ALL categories cached
    budget = analytics.compute_budget_status(conn)
    active_cats = [b.category for b in budget if b.current_spend > 0]

    for cat in active_cats:
        trend = analytics.analyze_category_trend(conn, cat)
        trend_data = {
            "category": trend.category,
            "direction": trend.direction,
            "slope_per_month": trend.slope_per_month,
            "r_squared": trend.r_squared,
            "current": trend.current,
            "mean": trend.mean,
            "std": trend.std,
            "pct_vs_mean": trend.pct_vs_mean,
            "months_analyzed": trend.months_analyzed,
            "forecast_next": trend.forecast_next,
            "severity": trend.severity,
            "action": trend.action,
        }
        database.upsert_category_analytics(conn, cat, "trend", json.dumps(trend_data, default=str))

        # Store Prophet forecast per category
        try:
            pf = analytics.prophet_forecast_category(conn, cat, periods=2)
            if pf:
                database.upsert_category_analytics(conn, cat, "prophet", json.dumps(pf, default=str))
        except Exception:
            pass

    # Store Prophet total spending forecast
    try:
        total_pf = analytics.prophet_forecast_total_spending(conn, periods=6)
        if total_pf:
            database.upsert_category_analytics(conn, "_global", "prophet_total", json.dumps(total_pf, default=str))
    except Exception:
        pass

    # Merchant impact per category
    for cat in active_cats:
        try:
            merchants = analytics.compute_merchant_impact(conn, cat)
            if merchants:
                database.upsert_category_analytics(conn, cat, "merchants", json.dumps(merchants, default=str))
        except Exception:
            pass

    # Advanced analytics: Mann-Kendall per category
    for cat in active_cats:
        history = database.get_category_monthly_history(conn, cat, months=24)
        if len(history) >= 4:
            values = [abs(h["total"]) for h in reversed(history)]
            mk = analytics.mann_kendall_test(values)
            seas = analytics.seasonality_decomposition(values)
            advanced = {"mann_kendall": mk, "seasonality": seas}
            database.upsert_category_analytics(conn, cat, "advanced", json.dumps(advanced, default=str))

    # Cross-category correlations
    try:
        correlations = analytics.cross_category_correlation(conn)
        database.upsert_category_analytics(conn, "_global", "correlations", json.dumps(correlations, default=str))
    except Exception:
        pass

    # Granger causality for top correlated pairs
    try:
        corrs = analytics.cross_category_correlation(conn)
        granger_results = []
        for pair in corrs[:5]:  # Top 5 correlated pairs
            cat_a, cat_b = pair["category_a"], pair["category_b"]
            hist_a = database.get_category_monthly_history(conn, cat_a, months=12)
            hist_b = database.get_category_monthly_history(conn, cat_b, months=12)
            if len(hist_a) >= 6 and len(hist_b) >= 6:
                vals_a = [abs(h["total"]) for h in reversed(hist_a)]
                vals_b = [abs(h["total"]) for h in reversed(hist_b)]
                # Pad to same length
                min_len = min(len(vals_a), len(vals_b))
                gc = analytics.granger_causality_simple(vals_a[:min_len], vals_b[:min_len])
                if gc["significant"]:
                    granger_results.append({
                        "cause": cat_a,
                        "effect": cat_b,
                        "f_stat": gc["f_stat"],
                        "p_value": gc["p_value"],
                        "interpretation": f"{cat_a} spending predicts {cat_b} spending (F={gc['f_stat']:.1f}, p={gc['p_value']:.3f})"
                    })
        if granger_results:
            database.upsert_category_analytics(conn, "_global", "granger", json.dumps(granger_results, default=str))
    except Exception:
        pass

    # Mark refresh timestamp
    database.set_setting(conn, "analytics_last_refresh", datetime.now().isoformat())

    return result


def get_cached(conn) -> Optional[dict]:
    """
    Read cached analytics from DB. Returns the same shape as
    analytics.build_statistical_context(), or None if cache is empty.
    """
    row = database.get_cached_analytics_for(conn, "_global", "context")
    if not row:
        return None
    try:
        return json.loads(row)
    except (json.JSONDecodeError, TypeError):
        return None


def get_cached_trend(conn, category: str) -> Optional[dict]:
    """Read cached trend analysis for a single category."""
    row = database.get_cached_analytics_for(conn, category, "trend")
    if not row:
        return None
    try:
        return json.loads(row)
    except (json.JSONDecodeError, TypeError):
        return None


def get_cached_prophet(conn, category: str) -> Optional[dict]:
    """Read cached Prophet forecast for a single category."""
    row = database.get_cached_analytics_for(conn, category, "prophet")
    if not row:
        return None
    try:
        return json.loads(row)
    except (json.JSONDecodeError, TypeError):
        return None


def get_cached_prophet_total(conn) -> Optional[dict]:
    """Read cached Prophet total spending forecast."""
    row = database.get_cached_analytics_for(conn, "_global", "prophet_total")
    if not row:
        return None
    try:
        return json.loads(row)
    except (json.JSONDecodeError, TypeError):
        return None


def get_cached_merchants(conn, category: str) -> list:
    """Read cached merchant impact ranking for a category."""
    row = database.get_cached_analytics_for(conn, category, "merchants")
    if not row:
        return []
    try:
        return json.loads(row)
    except (json.JSONDecodeError, TypeError):
        return []


def get_cached_advanced(conn, category: str) -> Optional[dict]:
    """Read cached Mann-Kendall + seasonality analysis for a category."""
    row = database.get_cached_analytics_for(conn, category, "advanced")
    if not row:
        return None
    try:
        return json.loads(row)
    except (json.JSONDecodeError, TypeError):
        return None


def get_cached_correlations(conn) -> list:
    """Read cached cross-category correlations."""
    row = database.get_cached_analytics_for(conn, "_global", "correlations")
    if not row:
        return []
    try:
        return json.loads(row)
    except (json.JSONDecodeError, TypeError):
        return []


def get_cached_granger(conn) -> list:
    """Read cached Granger causality results."""
    row = database.get_cached_analytics_for(conn, "_global", "granger")
    if not row:
        return []
    try:
        return json.loads(row)
    except (json.JSONDecodeError, TypeError):
        return []


def invalidate(conn) -> None:
    """Mark cache as stale by clearing the last refresh timestamp."""
    database.set_setting(conn, "analytics_last_refresh", "")


def is_stale(conn) -> bool:
    """Check if the cache needs refresh."""
    last_refresh = database.get_setting(conn, "analytics_last_refresh", "")
    if not last_refresh:
        return True
    try:
        last_dt = datetime.fromisoformat(last_refresh)
        return (datetime.now() - last_dt) > timedelta(hours=MAX_CACHE_AGE_HOURS)
    except (ValueError, TypeError):
        return True


def get_last_refresh_display(conn) -> str:
    """Return a human-readable string of when analytics were last refreshed."""
    last_refresh = database.get_setting(conn, "analytics_last_refresh", "")
    if not last_refresh:
        return "Never"
    try:
        last_dt = datetime.fromisoformat(last_refresh)
        delta = datetime.now() - last_dt
        if delta.total_seconds() < 60:
            return "Just now"
        elif delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)} min ago"
        elif delta.total_seconds() < 86400:
            return f"{int(delta.total_seconds() / 3600)} hours ago"
        else:
            return f"{int(delta.days)} days ago"
    except (ValueError, TypeError):
        return "Unknown"
