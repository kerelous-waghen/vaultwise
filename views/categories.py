"""Categories page — manage fix/flex/exclude classification for all categories."""

from calendar import month_name as _mn
from datetime import date

import streamlit as st

import analytics_cache
import config
import database
from shared.components import CATEGORY_EMOJIS, CATEGORY_ICON_BG, get_category_icon
from shared.state import get_conn

_TYPE_LABELS = {"fix": "Fixed", "flex": "Flex", "exclude": "Muted"}
_TYPE_ICONS = {"fix": "🏠", "flex": "💳", "exclude": "🔇"}
_TYPE_COLORS = {
    "fix": "#6b7280",   # grey
    "flex": "#2563eb",  # blue
    "exclude": "#9ca3af",  # light grey
}


def _migrate_config_muted(conn):
    """One-time: seed config.MUTED_CATEGORIES into category_config as 'exclude'."""
    muted = getattr(config, "MUTED_CATEGORIES", [])
    if not muted:
        return
    for cat in muted:
        row = conn.execute(
            "SELECT type FROM category_config WHERE name = ?", (cat,)
        ).fetchone()
        if not row:
            database.ensure_category_config(conn, cat, "exclude")
        elif row["type"] != "exclude":
            database.set_category_type(conn, cat, "exclude")


def _get_3month_averages(conn):
    """Returns {category: avg} for fixed categories over last 3 months with data."""
    fix_cats = database.get_categories_by_type(conn, "fix")
    if not fix_cats:
        return {}

    averages = {}
    for cat in fix_cats:
        rows = conn.execute("""
            SELECT SUM(ABS(amount)) as total
            FROM transactions
            WHERE category = ? AND amount < 0
            GROUP BY strftime('%Y-%m', date)
            ORDER BY strftime('%Y-%m', date) DESC
            LIMIT 3
        """, (cat,)).fetchall()
        if rows:
            vals = [r["total"] for r in rows]
            averages[cat] = round(sum(vals) / len(vals))
    return averages


def categories_page():
    conn = get_conn()

    # One-time migration of hardcoded MUTED_CATEGORIES
    _migrate_config_muted(conn)

    # Ensure all transaction categories exist in category_config
    all_configured = {r["name"] for r in database.get_all_category_config(conn)}
    txn_cats = {r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM transactions"
    ).fetchall()}
    for cat in txn_cats - all_configured:
        database.ensure_category_config(conn, cat, "flex")

    # Get current month breakdown for spend info
    today = date.today()
    current_month = f"{today.year:04d}-{today.month:02d}"
    breakdown = {
        r["category"]: r
        for r in database.get_monthly_category_breakdown(conn, current_month)
    }

    # Load all category configs
    all_cats = database.get_all_category_config(conn)
    # Group by type
    groups = {"fix": [], "flex": [], "exclude": []}
    for cat in all_cats:
        t = cat["type"]
        if t not in groups:
            t = "flex"
        spend_row = breakdown.get(cat["name"], {})
        cat["spend"] = abs(spend_row.get("total", 0))
        cat["txn_count"] = spend_row.get("txn_count", 0)
        groups[t].append(cat)

    # Sort each group by spend descending
    for g in groups.values():
        g.sort(key=lambda c: c["spend"], reverse=True)

    month_label = f"{_mn[today.month]} {today.year}"

    # Get capped fixed totals for display
    capped_fixed = database.get_capped_fixed_for_month(conn, current_month)

    # ── V5 Header ──────────────────────────────────────────────
    _hdr_l, _hdr_r = st.columns([3, 1])
    with _hdr_l:
        st.markdown(
            '<div style="font-size:18px;font-weight:700;color:var(--vw-text);">Categories</div>'
            '<div style="font-size:12px;color:var(--vw-text-muted);">How your spending is classified</div>',
            unsafe_allow_html=True,
        )
    with _hdr_r:
        # "Update Budgets from Recent Data" button (fixed cats)
        if st.button("Update Budgets from Recent Data", key="update_budgets_btn"):
            st.session_state["show_budget_update"] = True

    # ── Allocation summary bar ─────────────────────────────────
    _fix_total = sum(c["spend"] for c in groups["fix"])
    _flex_total = sum(c["spend"] for c in groups["flex"])
    _total_all = _fix_total + _flex_total
    if _total_all > 0:
        _f_pct = _fix_total / _total_all * 100
        _x_pct = _flex_total / _total_all * 100
    else:
        _f_pct = _x_pct = 50

    st.markdown(
        f'<div style="background:var(--vw-card-bg);border-radius:16px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,0.04);margin-bottom:14px;">'
        f'<div style="display:flex;height:10px;border-radius:5px;overflow:hidden;margin-bottom:8px;">'
        f'<div style="flex:{_f_pct:.0f};background:#374151;"></div>'
        f'<div style="flex:{_x_pct:.0f};background:#3b82f6;"></div>'
        f'</div>'
        f'<div style="display:flex;gap:16px;font-size:12px;">'
        f'<div style="display:flex;align-items:center;gap:4px;">'
        f'<div style="width:8px;height:8px;border-radius:2px;background:#374151;"></div>'
        f'<span style="color:var(--vw-text-muted);">Fixed <strong style="color:var(--vw-text);">${_fix_total:,.0f}</strong></span></div>'
        f'<div style="display:flex;align-items:center;gap:4px;">'
        f'<div style="width:8px;height:8px;border-radius:2px;background:#3b82f6;"></div>'
        f'<span style="color:var(--vw-text-muted);">Flex <strong style="color:var(--vw-text);">${_flex_total:,.0f}</strong></span></div>'
        f'<div style="display:flex;align-items:center;gap:4px;">'
        f'<div style="width:8px;height:8px;border-radius:2px;background:#e5e7eb;"></div>'
        f'<span style="color:var(--vw-text-faint);">Muted</span></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── Budget update panel (shown when button clicked) ────────
    _render_update_budgets(conn, groups["fix"])

    # ── Render each group ──────────────────────────────────────
    for cat_type, label, icon in [
        ("fix", "Fixed Bills", "🏠"),
        ("flex", "Flex Spending", "💳"),
        ("exclude", "Muted", "🔇"),
    ]:
        cats = groups[cat_type]
        total = sum(c["spend"] for c in cats)

        # Show capped info for fixed
        if cat_type == "fix":
            capped_total = sum(capped_fixed.values())
            if capped_total > 0 and capped_total != total:
                st.markdown(
                    f'<div class="vw-section-label">{icon} {label} &mdash; ${total:,.0f} actual &rarr; ${capped_total:,.0f} after caps</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="vw-section-label">{icon} {label} &mdash; ${total:,.0f}</div>',
                    unsafe_allow_html=True,
                )
        elif cat_type == "exclude":
            # Muted section — collapsed by default
            _muted_names = ", ".join(c["name"] for c in cats[:3])
            _muted_suffix = f", +{len(cats) - 3} more" if len(cats) > 3 else ""
            with st.expander(f"🔇 {len(cats)} Muted ({_muted_names}{_muted_suffix})", expanded=False):
                for cat in cats:
                    _render_category_row(conn, cat, cat_type)
            continue
        else:
            st.markdown(
                f'<div class="vw-section-label">{icon} {label} &mdash; ${total:,.0f}</div>',
                unsafe_allow_html=True,
            )

        if not cats:
            st.markdown(f"*No {label.lower()} categories.*")
        else:
            for cat in cats:
                _render_category_row(conn, cat, cat_type)

        st.divider()


def _render_update_budgets(conn, fixed_cats):
    """Render the Update Budgets expander with 3-month averages and override inputs."""
    if not st.session_state.get("show_budget_update"):
        return

    averages = _get_3month_averages(conn)
    if not averages:
        st.info("No spending data to calculate averages.")
        return

    st.markdown("**Last 3-month averages** — adjust any value, then click Apply.")

    updates = {}
    for cat in fixed_cats:
        name = cat["name"]
        avg = averages.get(name, 0)
        current_budget = cat.get("monthly_budget")
        current_val = int(current_budget) if current_budget else 0

        col_name, col_avg, col_new = st.columns([2.5, 1.5, 1.5])
        with col_name:
            st.markdown(f"**{name}**")
        with col_avg:
            st.markdown(f"3mo avg: **${avg:,.0f}**")
        with col_new:
            new_val = st.number_input(
                "New cap",
                min_value=0,
                value=avg if avg > 0 else current_val,
                step=50,
                key=f"update_budget_{name}",
                label_visibility="collapsed",
            )
            updates[name] = new_val

    col_apply, col_cancel = st.columns(2)
    with col_apply:
        if st.button("Apply", type="primary", key="apply_budgets"):
            for name, val in updates.items():
                budget_val = val if val > 0 else None
                database.set_category_budget(conn, name, budget_val)
            st.session_state["show_budget_update"] = False
            st.success(f"Updated budgets for {len(updates)} categories.")
            st.rerun()
    with col_cancel:
        if st.button("Cancel", key="cancel_budgets"):
            st.session_state["show_budget_update"] = False
            st.rerun()


def _render_category_row(conn, cat, current_type):
    """Render a single category row with V5 icon tile style + controls."""
    name = cat["name"]
    spend = cat["spend"]
    txn_count = cat["txn_count"]
    budget = cat.get("monthly_budget")

    # Get icon and background
    emoji, bg_color = get_category_icon(name)

    # Fixed categories use neutral grey background for icon tile
    if current_type == "fix":
        bg_color = "#f3f4f6"

    # Build sub-text and trend color
    if current_type == "fix":
        if budget and budget > 0:
            trend_text = f"Budget: ${budget:,.0f}"
            _pct = spend / budget * 100 if budget > 0 else 0
            trend_color = "#22c55e" if _pct < 90 else ("#f59e0b" if _pct <= 100 else "#ef4444")
        else:
            trend_text = f"{txn_count} txns" if txn_count > 0 else ""
            trend_color = "#6b7280"
    elif current_type == "exclude":
        trend_text = f"{txn_count} txns" if txn_count > 0 else "excluded"
        trend_color = "#9ca3af"
    else:
        # Flex — show trend % badge from analytics cache
        _trend = analytics_cache.get_cached_trend(conn, name)
        if _trend and spend > 0:
            _t_mean = float(_trend.get("mean", 0))
            if _t_mean > 0:
                _t_pct = ((spend / _t_mean) - 1) * 100
                if _t_pct > 5:
                    trend_text = f"&#8593;{_t_pct:.0f}% &bull; avg ${_t_mean:,.0f}"
                    trend_color = "#ef4444"
                elif _t_pct < -5:
                    trend_text = f"&#8595;{abs(_t_pct):.0f}% &bull; avg ${_t_mean:,.0f}"
                    trend_color = "#22c55e"
                else:
                    trend_text = f"&#8594; Stable &bull; avg ${_t_mean:,.0f}"
                    trend_color = "#22c55e"
            else:
                trend_text = f"{txn_count} txns" if txn_count > 0 else ""
                trend_color = "#6b7280"
        else:
            trend_text = f"{txn_count} txns" if txn_count > 0 else ""
            trend_color = "#6b7280"

    # Dim opacity for muted categories
    row_opacity = "opacity:0.5;" if current_type == "exclude" else ""

    # HTML tile
    tile_html = (
        f'<div class="vw-cat-tile-row" style="{row_opacity}">'
        f'<div class="tile-icon" style="background:{bg_color};">{emoji}</div>'
        f'<div class="tile-details">'
        f'<div class="tile-name">{name}</div>'
        f'<div class="tile-sub" style="color:{trend_color};">{trend_text}</div>'
        f'</div>'
        f'<div class="tile-amount">${spend:,.0f}</div>'
        f'</div>'
    )

    # Layout: HTML card on left, controls on right
    if current_type == "fix":
        col_card, col_budget, col_type = st.columns([3.5, 1.5, 1.5])
    else:
        col_card, col_type = st.columns([5, 1.5])
        col_budget = None

    with col_card:
        st.markdown(tile_html, unsafe_allow_html=True)

    if col_budget is not None:
        with col_budget:
            new_budget = st.number_input(
                "Cap/mo",
                min_value=0,
                value=int(budget) if budget else 0,
                step=50,
                key=f"cat_budget_{name}",
                label_visibility="collapsed",
                help="Monthly cap — if actual exceeds this, only the cap is counted",
            )
            new_budget_val = new_budget if new_budget > 0 else None
            old_budget_val = int(budget) if budget else None
            if new_budget_val != old_budget_val:
                database.set_category_budget(conn, name, new_budget_val)
                st.rerun()

    with col_type:
        options = ["Fixed", "Flex", "Muted"]
        current_idx = {"fix": 0, "flex": 1, "exclude": 2}.get(current_type, 1)
        new_label = st.selectbox(
            "Type",
            options,
            index=current_idx,
            key=f"cat_type_{name}",
            label_visibility="collapsed",
        )
        new_type = {"Fixed": "fix", "Flex": "flex", "Muted": "exclude"}[new_label]
        if new_type != current_type:
            database.set_category_type(conn, name, new_type)
            st.rerun()
