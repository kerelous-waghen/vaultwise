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
_PILL_CLASSES = {"fix": "vw-pill-fix", "flex": "vw-pill-flex", "exclude": "vw-pill-muted"}


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


def _get_meta_html(conn, cat, cat_type):
    """Build the meta line HTML (trend/budget info) for a category."""
    name = cat["name"]
    spend = cat["spend"]
    budget = cat.get("monthly_budget")
    txn_count = cat["txn_count"]

    if cat_type == "fix":
        if budget and budget > 0:
            _pct = spend / budget * 100
            _color = "#22c55e" if _pct < 90 else ("#f59e0b" if _pct <= 100 else "#ef4444")
            if spend > budget:
                return f'<span style="color:{_color};">${spend:,.0f} / ${budget:,.0f} cap</span>', _color
            return f'<span style="color:{_color};">Budget: ${budget:,.0f}</span>', _color
        if txn_count > 0:
            return f'<span style="color:#6b7280;">{txn_count} txns</span>', ""
        return "", ""
    elif cat_type == "exclude":
        if txn_count > 0:
            return f'<span style="color:#9ca3af;">{txn_count} txns</span>', ""
        return '<span style="color:#9ca3af;">excluded</span>', ""
    else:
        # Flex — trend from cache or history
        _trend = analytics_cache.get_cached_trend(conn, name)
        _t_mean = float(_trend.get("mean", 0)) if _trend else 0
        if _t_mean <= 0:
            hist = database.get_category_monthly_history(conn, name, months=6)
            if hist and len(hist) >= 2:
                _t_mean = sum(abs(h["total"]) for h in hist) / len(hist)
        if _t_mean > 0 and spend > 0:
            _t_pct = ((spend / _t_mean) - 1) * 100
            if _t_pct > 5:
                return f'<span style="color:#ef4444;">↑{_t_pct:.0f}% · avg ${_t_mean:,.0f}</span>', "#ef4444"
            elif _t_pct < -5:
                return f'<span style="color:#22c55e;">↓{abs(_t_pct):.0f}% · avg ${_t_mean:,.0f}</span>', "#22c55e"
            else:
                return f'<span style="color:#9ca3af;">→ Stable · avg ${_t_mean:,.0f}</span>', ""
        if txn_count > 0:
            return f'<span style="color:#6b7280;">{txn_count} txns</span>', ""
        return "", ""


def _render_cat_row_html(cat, cat_type, meta_html, amt_color):
    """Render one category row as HTML (icon + name + pill + meta + amount + progress)."""
    name = cat["name"]
    spend = cat["spend"]
    budget = cat.get("monthly_budget")
    emoji, bg_color = get_category_icon(name)
    if cat_type == "fix":
        bg_color = "#f3f4f6"

    _pill_cls = _PILL_CLASSES.get(cat_type, "vw-pill-flex")
    _pill_label = _TYPE_LABELS.get(cat_type, "Flex")
    _opacity = "opacity:0.5;" if cat_type == "exclude" else ""
    _amt_style = f"color:{amt_color};" if amt_color else ""

    # Progress bar
    _prog_html = ""
    if spend > 0:
        if cat_type == "fix" and budget and budget > 0:
            _pct = min(spend / budget * 100, 100)
            _pc = "#22c55e" if spend <= budget else "#ef4444"
        elif amt_color:
            _pct = 100
            _pc = amt_color
        else:
            _pct = 100
            _pc = "#6366f1"
        _prog_html = f'<div class="cat-progress-v2"><div class="cat-progress-fill-v2" style="width:{_pct:.0f}%;background:{_pc};"></div></div>'

    st.markdown(
        f'<div class="vw-cat-row-v2" style="{_opacity}">'
        f'<div class="cat-icon-v2" style="background:{bg_color};">{emoji}</div>'
        f'<div class="cat-info-v2">'
        f'<div class="cat-name-v2">{name}</div>'
        f'<div class="cat-meta-v2">'
        f'<span class="vw-cat-type-pill {_pill_cls}">{_pill_label}</span>'
        f'<div class="meta-dot"></div>'
        f'{meta_html}'
        f'</div></div>'
        f'<div class="cat-right-v2">'
        f'<div class="cat-amount-v2" style="{_amt_style}">${spend:,.0f}</div>'
        f'{_prog_html}'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def _render_cat_controls(conn, cat, cat_type):
    """Render the type selector + budget input for one category."""
    name = cat["name"]
    budget = cat.get("monthly_budget")

    if cat_type == "fix":
        _c1, _c2 = st.columns([1, 1])
        with _c1:
            options = ["Fixed", "Flex", "Muted"]
            current_idx = {"fix": 0, "flex": 1, "exclude": 2}.get(cat_type, 1)
            new_label = st.selectbox(
                "Type", options, index=current_idx,
                key=f"cat_type_{name}", label_visibility="collapsed",
            )
            new_type = {"Fixed": "fix", "Flex": "flex", "Muted": "exclude"}[new_label]
            if new_type != cat_type:
                database.set_category_type(conn, name, new_type)
                st.rerun()
        with _c2:
            new_budget = st.number_input(
                "Cap/mo", min_value=0,
                value=int(budget) if budget else 0,
                step=50, key=f"cat_budget_{name}",
                label_visibility="collapsed",
                help="Monthly cap",
            )
            new_budget_val = new_budget if new_budget > 0 else None
            old_budget_val = int(budget) if budget else None
            if new_budget_val != old_budget_val:
                database.set_category_budget(conn, name, new_budget_val)
                st.rerun()
    else:
        options = ["Fixed", "Flex", "Muted"]
        current_idx = {"fix": 0, "flex": 1, "exclude": 2}.get(cat_type, 1)
        new_label = st.selectbox(
            "Type", options, index=current_idx,
            key=f"cat_type_{name}", label_visibility="collapsed",
        )
        new_type = {"Fixed": "fix", "Flex": "flex", "Muted": "exclude"}[new_label]
        if new_type != cat_type:
            database.set_category_type(conn, name, new_type)
            st.rerun()

    st.markdown(
        '<div style="font-size:10px;color:#10b981;display:flex;align-items:center;gap:4px;margin-top:2px;">'
        '✓ Changes save automatically</div>',
        unsafe_allow_html=True,
    )


def _render_single_cat(conn, cat, cat_type):
    """Render one category: HTML row + popover for controls, inside one container."""
    meta_html, amt_color = _get_meta_html(conn, cat, cat_type)
    _render_cat_row_html(cat, cat_type, meta_html, amt_color)
    with st.popover(f"✏ Edit {cat['name']}", use_container_width=True):
        _render_cat_controls(conn, cat, cat_type)


def _render_group(conn, cats, cat_type, show_first=8):
    """Render a group of categories matching the mockup layout."""
    visible = cats[:show_first]
    hidden = cats[show_first:]

    if not cats:
        st.markdown("*No categories.*")
        return

    # Each category: HTML row + popover, inside a shared bordered container
    with st.container(border=True):
        for cat in visible:
            _render_single_cat(conn, cat, cat_type)

    # Hidden categories in expander
    if hidden:
        with st.expander(f"Show {len(hidden)} more {_TYPE_LABELS.get(cat_type, '')} categories"):
            for cat in hidden:
                _render_single_cat(conn, cat, cat_type)


def categories_page():
    conn = get_conn()

    # One-time migration
    _migrate_config_muted(conn)

    # Ensure all transaction categories exist in category_config
    all_configured = {r["name"] for r in database.get_all_category_config(conn)}
    txn_cats = {r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM transactions"
    ).fetchall()}
    for cat in txn_cats - all_configured:
        database.ensure_category_config(conn, cat, "flex")

    # Get current month breakdown
    today = date.today()
    current_month = f"{today.year:04d}-{today.month:02d}"
    breakdown = {
        r["category"]: r
        for r in database.get_monthly_category_breakdown(conn, current_month)
    }

    # Load and group categories
    all_cats = database.get_all_category_config(conn)
    groups = {"fix": [], "flex": [], "exclude": []}
    for cat in all_cats:
        t = cat["type"]
        if t not in groups:
            t = "flex"
        spend_row = breakdown.get(cat["name"], {})
        cat["spend"] = abs(spend_row.get("total", 0))
        cat["txn_count"] = spend_row.get("txn_count", 0)
        groups[t].append(cat)

    for g in groups.values():
        g.sort(key=lambda c: c["spend"], reverse=True)

    # ══════════════════════════════════════════════════════════════
    # ALLOCATION HERO
    # ══════════════════════════════════════════════════════════════
    _fix_total = sum(c["spend"] for c in groups["fix"])
    _flex_total = sum(c["spend"] for c in groups["flex"])
    _total_all = _fix_total + _flex_total
    _f_pct = _fix_total / max(_total_all, 1) * 100
    _x_pct = _flex_total / max(_total_all, 1) * 100

    st.markdown(
        f'<div class="vw-alloc-hero-v2">'
        f'<div style="font-size:11px;color:var(--vw-text-faint);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">How your spending is classified</div>'
        f'<div class="vw-alloc-bar-v2">'
        f'<div style="flex:{_f_pct:.0f};background:#374151;border-radius:6px 0 0 6px;"></div>'
        f'<div style="flex:{_x_pct:.0f};background:#3b82f6;border-radius:0 6px 6px 0;"></div>'
        f'</div>'
        f'<div class="vw-alloc-legend-v2">'
        f'<div class="al-item"><div class="al-dot" style="background:#374151;"></div><span class="al-label">Fixed</span><span class="al-value">${_fix_total:,.0f}</span></div>'
        f'<div class="al-item"><div class="al-dot" style="background:#3b82f6;"></div><span class="al-label">Flex</span><span class="al-value">${_flex_total:,.0f}</span></div>'
        f'<div class="al-item"><div class="al-dot" style="background:#e5e7eb;"></div><span class="al-label">Muted</span></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════════════
    # FIXED BILLS
    # ══════════════════════════════════════════════════════════════
    st.markdown(
        f'<div class="vw-cat-sec-header">'
        f'<div class="csh-left"><span style="font-size:16px;">🏠</span><span class="csh-title">Fixed Bills</span>'
        f'<span class="csh-count">· {len(groups["fix"])}</span></div>'
        f'<span class="csh-total">${_fix_total:,.0f}</span></div>',
        unsafe_allow_html=True,
    )
    _render_group(conn, groups["fix"], "fix")

    # ══════════════════════════════════════════════════════════════
    # FLEX SPENDING
    # ══════════════════════════════════════════════════════════════
    st.markdown(
        f'<div class="vw-cat-sec-header">'
        f'<div class="csh-left"><span style="font-size:16px;">💳</span><span class="csh-title">Flex Spending</span>'
        f'<span class="csh-count">· {len(groups["flex"])}</span></div>'
        f'<span class="csh-total" style="color:#3b82f6;">${_flex_total:,.0f}</span></div>',
        unsafe_allow_html=True,
    )
    _render_group(conn, groups["flex"], "flex")

    # ══════════════════════════════════════════════════════════════
    # MUTED (collapsed)
    # ══════════════════════════════════════════════════════════════
    _muted_cats = groups["exclude"]
    _muted_names = ", ".join(c["name"] for c in _muted_cats[:3])
    _muted_suffix = f", +{len(_muted_cats) - 3} more" if len(_muted_cats) > 3 else ""

    st.markdown(
        f'<div class="vw-cat-sec-header">'
        f'<div class="csh-left"><span style="font-size:16px;">🔇</span><span class="csh-title">Muted</span>'
        f'<span class="csh-count">· {len(_muted_cats)} hidden</span></div></div>',
        unsafe_allow_html=True,
    )

    if _muted_cats:
        with st.expander(f"🔇 {len(_muted_cats)} Muted ({_muted_names}{_muted_suffix})", expanded=False):
            st.markdown('<div class="vw-cat-card-v2">', unsafe_allow_html=True)
            for cat in _muted_cats:
                meta_html, amt_color = _get_meta_html(conn, cat, "exclude")
                _render_cat_row_html(cat, "exclude", meta_html, amt_color)
            st.markdown('</div>', unsafe_allow_html=True)

            for cat in _muted_cats:
                with st.expander(f"Edit: {cat['name']}", expanded=False):
                    _render_cat_controls(conn, cat, "exclude")

    # ══════════════════════════════════════════════════════════════
    # UPDATE BUDGETS
    # ══════════════════════════════════════════════════════════════
    st.divider()
    if st.button("📊 Update Budgets from Recent Data", key="update_budgets_btn", use_container_width=True):
        st.session_state["show_budget_update"] = True
    _render_update_budgets(conn, groups["fix"])

    conn.close()


def _render_update_budgets(conn, fixed_cats):
    """Render the Update Budgets panel with 3-month averages."""
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
                "New cap", min_value=0,
                value=avg if avg > 0 else current_val,
                step=50, key=f"update_budget_{name}",
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
