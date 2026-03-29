"""Plan page — The Math, Close the Gap, Your Progress."""

import json
import calendar as _cal
from datetime import date as _date

import streamlit as st

import category_engine
import config
import database
import models
from shared.state import get_conn


def _get_flexible_spending(conn, year_month: str, fixed_cats, muted_cats, merges):
    """Get flexible spending for a month using same logic as dashboard.

    Returns (total_flexible, category_totals_dict).
    """
    _raw = database.get_monthly_category_breakdown(conn, year_month)
    _active = category_engine.get_active_categories(conn)
    _cats = [c for c in _raw if c["category"] in _active]

    # Apply merges (same as home.py lines 121-133)
    _merge_sources = set()
    for _target, _sources in merges.items():
        _merge_sources.update(_sources)
        _target_entry = next((c for c in _cats if c["category"] == _target), None)
        for _src in _sources:
            _src_entry = next((c for c in _cats if c["category"] == _src), None)
            if _src_entry:
                if _target_entry:
                    _target_entry["total"] += _src_entry["total"]
                    _target_entry["txn_count"] += _src_entry["txn_count"]
                else:
                    _src_entry["category"] = _target
                    _target_entry = _src_entry
                    _merge_sources.discard(_src)

    # Filter muted + merge sources
    _cats = [c for c in _cats
             if c["category"] not in muted_cats
             and c["category"] not in _merge_sources]

    # Separate fixed vs flexible
    _flex = [c for c in _cats if c["category"] not in fixed_cats]
    _total = sum(abs(c["total"]) for c in _flex)
    _by_cat = {c["category"]: abs(c["total"]) for c in _flex}
    return _total, _by_cat


def savings_journey_page():
    """Render the Plan page: The Math, Close the Gap, Your Progress."""
    conn = get_conn()

    # ── Recompute key variables ───────────────────────────────────────
    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))
    _today = _date.today()
    _income_data = models.get_income_for_month(_today.year, _today.month)
    _monthly_income = _income_data["total_income"] if isinstance(_income_data, dict) else _income_data
    _kero_bonus = _income_data.get("kero_bonus", 0) if isinstance(_income_data, dict) else 0
    _maggie_bonus = _income_data.get("maggie_bonus", 0) if isinstance(_income_data, dict) else 0
    _monthly_income -= (_kero_bonus + _maggie_bonus)
    _effective_fixed = sum(config.FIXED_MONTHLY_EXPENSES.values())
    _savings_target = savings_target
    _spending_money = _monthly_income - _effective_fixed - _savings_target

    # ── Category sets (same as dashboard home.py) ──────────────────────
    _muted_cats = set(getattr(config, 'MUTED_CATEGORIES', []))
    _fixed_cats = {"Housing & Utilities", "Debt Payments", "Family Support",
                   "Transportation", "Phone & Internet", "Car Insurance"}
    _fixed_cats.update(getattr(config, 'MONARCH_FIXED_MAP', {}).keys())
    _merges = getattr(config, 'CATEGORY_MERGES', {})

    # ── Get last 6 months of flexible spending ─────────────────────────
    _month_keys = conn.execute("""
        SELECT DISTINCT strftime('%Y-%m', date) as month
        FROM transactions WHERE amount < 0
        ORDER BY month DESC LIMIT 6
    """).fetchall()

    _hist_rows = []
    _month_cat_totals = {}
    for _mk in _month_keys:
        _ym = _mk["month"]
        _total, _by_cat = _get_flexible_spending(
            conn, _ym, _fixed_cats, _muted_cats, _merges)
        _hist_rows.append({"month": _ym, "total": _total})
        _month_cat_totals[_ym] = _by_cat

    # ── Compute category averages across all months ────────────────────
    _all_cats = {}
    for _ym, _by_cat in _month_cat_totals.items():
        for _cat_name, _amt in _by_cat.items():
            _all_cats.setdefault(_cat_name, []).append(_amt)
    _cat_avgs = []
    for _cat_name, _amounts in _all_cats.items():
        _avg = round(sum(_amounts) / len(_amounts))
        if _avg > 20:
            _cat_avgs.append({"category": _cat_name, "avg_spend": _avg})
    _cat_avgs.sort(key=lambda c: c["avg_spend"], reverse=True)

    _typical_total = sum(c["avg_spend"] for c in _cat_avgs)

    # ── Load saved targets ─────────────────────────────────────────────
    _saved_targets_raw = database.get_setting(conn, "flex_category_targets", "")
    _saved_targets = json.loads(_saved_targets_raw) if _saved_targets_raw else {}

    # ══════════════════════════════════════════════════════════════════
    # SECTION 1: THE MATH
    # ══════════════════════════════════════════════════════════════════
    st.markdown("### The Math")

    _rows = [
        ("Income", f"${_monthly_income:,.0f}", "#1a1a2e"),
        ("− Fixed bills", f"−${_effective_fixed:,.0f}", "#ef4444"),
        ("− Savings target", f"−${_savings_target:,.0f}", "#f59e0b"),
    ]
    _html = '<div style="font-size:0.88rem;line-height:2;">'
    for label, value, color in _rows:
        _html += (
            f'<div style="display:flex;justify-content:space-between;">'
            f'<span style="color:#888;">{label}</span>'
            f'<span style="font-weight:600;color:{color};">{value}</span></div>'
        )
    _html += (
        f'<div style="border-top:2px solid #1a1a2e;margin-top:4px;padding-top:4px;'
        f'display:flex;justify-content:space-between;">'
        f'<span style="font-weight:800;">= Flex budget</span>'
        f'<span style="font-weight:800;font-size:1.05rem;color:#16a34a;">'
        f'${_spending_money:,.0f}/mo</span></div>'
    )

    # Reality context: typical spending + gap
    _gap_to_close = _typical_total - _spending_money
    _gap_color = "#ef4444" if _gap_to_close > 0 else "#16a34a"
    _html += (
        f'<div style="margin-top:8px;padding-top:6px;border-top:1px dashed #e5e7eb;">'
        f'<div style="display:flex;justify-content:space-between;">'
        f'<span style="color:#888;">Your typical flex spending</span>'
        f'<span style="font-weight:600;color:#1a1a2e;">${_typical_total:,.0f}/mo</span></div>'
        f'<div style="display:flex;justify-content:space-between;">'
        f'<span style="color:#888;">Gap to close</span>'
        f'<span style="font-weight:700;color:{_gap_color};">'
        f'{"−" if _gap_to_close <= 0 else ""}${abs(_gap_to_close):,.0f}/mo</span></div>'
        f'</div></div>'
    )
    st.markdown(_html, unsafe_allow_html=True)

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 2: CLOSE THE GAP
    # ══════════════════════════════════════════════════════════════════
    st.markdown("### Close the Gap")

    # Honesty check: can the gap even be closed?
    _min_total = sum(max(int(c["avg_spend"] * 0.1), 0) for c in _cat_avgs)
    _impossible = _min_total > _spending_money

    if _impossible:
        _realistic_target = _monthly_income - _effective_fixed - _min_total
        st.markdown(
            f'<div style="background:#fef2f2;border:1px solid #fecaca;'
            f'border-radius:8px;padding:10px 14px;margin-bottom:12px;'
            f'font-size:0.82rem;color:#991b1b;line-height:1.5;">'
            f'Even cutting everything to the bone, flex spending would be '
            f'~${_min_total:,.0f}/mo — but your budget is ${_spending_money:,.0f}/mo. '
            f'Consider adjusting your savings target from '
            f'${_savings_target:,.0f} to ~${max(_realistic_target, 0):,.0f}/mo '
            f'to make a plan you can actually hit.</div>',
            unsafe_allow_html=True,
        )

    st.caption(
        "Set a realistic target for each category. "
        "The gap shrinks as you reduce targets below typical."
    )

    # Category target inputs
    _target_values = {}
    _target_typical_total = 0

    for _cat in _cat_avgs:
        _name = _cat["category"]
        _avg = int(_cat["avg_spend"])
        _target_typical_total += _avg
        _min_val = max(int(_avg * 0.1), 0)
        _default = _saved_targets.get(_name, _avg)
        # Clamp default to valid range
        _default = max(_min_val, min(_default, _avg))

        _col_label, _col_input, _col_save = st.columns([3, 2, 1])
        with _col_label:
            st.markdown(
                f'<div style="font-size:0.82rem;color:#555;padding-top:8px;">'
                f'{_name}<br>'
                f'<span style="font-size:0.68rem;color:#bbb;">typical ${_avg:,.0f}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with _col_input:
            _val = st.number_input(
                _name,
                min_value=_min_val,
                max_value=_avg,
                value=_default,
                step=25,
                key=f"target_{_name}",
                label_visibility="collapsed",
            )
        with _col_save:
            _cut = _avg - _val
            if _cut > 0:
                st.markdown(
                    f'<div style="font-size:0.72rem;color:#16a34a;'
                    f'font-weight:700;padding-top:10px;">'
                    f'−${_cut:,.0f}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div style="padding-top:10px;font-size:0.72rem;color:#ccc;">—</div>',
                    unsafe_allow_html=True,
                )

        _target_values[_name] = _val

    # ── Gap counter + result card ────────────────────────────────────
    _plan_total = sum(_target_values.values())
    _total_cuts = _target_typical_total - _plan_total
    _remaining_gap = _plan_total - _spending_money
    _plan_hits = _remaining_gap <= 0

    if _plan_hits:
        _buffer = _spending_money - _plan_total
        _total_saved = _savings_target + _buffer
        _card_bg = "linear-gradient(135deg, #f0fdf4, #dcfce7)"
        _card_border = "#bbf7d0"
        _card_color = "#166534"
        _card_text = (
            f'Your plan saves ~${_total_saved:,.0f}/mo total — '
            f'${_savings_target:,.0f} to savings'
        )
        if _buffer > 0:
            _card_text += f' + ${_buffer:,.0f} buffer'
        _card_text += '.'
        _card_headline = f'<span style="font-size:1.2rem;">✅</span> Plan fits!'
    elif _total_cuts > 0:
        _card_bg = "linear-gradient(135deg, #fffbeb, #fef3c7)"
        _card_border = "#fde68a"
        _card_color = "#92400e"
        _card_text = (
            f'Still ${_remaining_gap:,.0f}/mo over budget. '
            f'Try cutting another category, or consider adjusting your '
            f'${_savings_target:,.0f}/mo savings target.'
        )
        _card_headline = f'${_remaining_gap:,.0f}/mo over'
    else:
        _card_bg = "linear-gradient(135deg, #fef2f2, #fee2e2)"
        _card_border = "#fecaca"
        _card_color = "#991b1b"
        _card_text = (
            f'Typical spending is ${_gap_to_close:,.0f}/mo above budget. '
            f'Set targets below typical to close the gap.'
        )
        _card_headline = f'${_gap_to_close:,.0f}/mo gap'

    _cuts_badge = ""
    if _total_cuts > 0:
        _cuts_badge = (
            f'<span style="font-size:0.7rem;font-weight:700;color:#16a34a;'
            f'background:#f0fdf4;padding:3px 8px;border-radius:8px;'
            f'margin-left:8px;">cutting ${_total_cuts:,.0f}/mo</span>'
        )

    st.markdown(
        f'<div style="background:{_card_bg};border:1px solid {_card_border};'
        f'border-radius:12px;padding:14px 16px;margin-top:12px;">'
        f'<div style="display:flex;align-items:center;margin-bottom:6px;">'
        f'<span style="font-size:1.1rem;font-weight:800;color:{_card_color};">'
        f'{_card_headline}</span>{_cuts_badge}</div>'
        f'<div style="font-size:0.82rem;color:{_card_color};line-height:1.5;">'
        f'{_card_text}</div></div>',
        unsafe_allow_html=True,
    )

    # ── Save button ──────────────────────────────────────────────────
    if st.button("Save My Plan", type="primary", use_container_width=True):
        database.set_setting(
            conn, "flex_category_targets", json.dumps(_target_values))
        _saved_targets = _target_values.copy()
        st.success("Plan saved! Track your progress below.")

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 3: YOUR PROGRESS
    # ══════════════════════════════════════════════════════════════════
    st.markdown("### Your Progress")

    if not _saved_targets:
        st.info("Set targets above and click **Save My Plan** to start tracking.")
        conn.close()
        return

    # Get current month actuals
    _cur_month = f"{_today.year}-{_today.month:02d}"
    _, _cur_by_cat = _get_flexible_spending(
        conn, _cur_month, _fixed_cats, _muted_cats, _merges)

    _days_in_month = _cal.monthrange(_today.year, _today.month)[1]
    _pct_elapsed = _today.day / _days_in_month

    st.caption(
        f"{_cal.month_name[_today.month]} {_today.year} — "
        f"day {_today.day} of {_days_in_month} "
        f"({_pct_elapsed:.0%} elapsed)"
    )

    # Progress table
    _progress_html = (
        '<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr 28px;'
        'gap:4px;font-size:0.6rem;color:#bbb;font-weight:700;'
        'text-transform:uppercase;margin-bottom:4px;padding:0 2px;">'
        '<span>Category</span>'
        '<span style="text-align:right;">Target</span>'
        '<span style="text-align:right;">Actual</span>'
        '<span style="text-align:right;">Pace</span>'
        '<span></span></div>'
    )

    _total_target = 0
    _total_actual = 0

    # Sort by target descending
    _sorted_targets = sorted(_saved_targets.items(), key=lambda x: x[1], reverse=True)

    for _name, _target in _sorted_targets:
        _actual = round(_cur_by_cat.get(_name, 0))
        _total_target += _target
        _total_actual += _actual

        # Project pace to month-end
        _projected = round(_actual / max(_pct_elapsed, 0.1))

        # Status: compare projected to target
        if _projected <= _target:
            _icon = "🟢"
            _actual_color = "#16a34a"
        elif _projected <= _target * 1.15:
            _icon = "🟡"
            _actual_color = "#d97706"
        else:
            _icon = "🔴"
            _actual_color = "#ef4444"

        _progress_html += (
            f'<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr 28px;'
            f'gap:4px;font-size:0.82rem;padding:5px 2px;'
            f'border-bottom:1px solid #f5f3ef;">'
            f'<span style="color:#555;font-weight:500;">{_name}</span>'
            f'<span style="text-align:right;color:#888;">${_target:,.0f}</span>'
            f'<span style="text-align:right;font-weight:600;color:{_actual_color};">'
            f'${_actual:,.0f}</span>'
            f'<span style="text-align:right;font-size:0.72rem;color:#aaa;">'
            f'→${_projected:,.0f}</span>'
            f'<span style="text-align:center;">{_icon}</span></div>'
        )

    # Summary row
    _total_projected = round(_total_actual / max(_pct_elapsed, 0.1))
    if _total_projected <= _total_target:
        _summary_icon = "🟢"
        _summary_color = "#16a34a"
    elif _total_projected <= _total_target * 1.15:
        _summary_icon = "🟡"
        _summary_color = "#d97706"
    else:
        _summary_icon = "🔴"
        _summary_color = "#ef4444"

    _progress_html += (
        f'<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr 28px;'
        f'gap:4px;font-size:0.82rem;padding:8px 2px;'
        f'border-top:2px solid #1a1a2e;font-weight:700;">'
        f'<span style="color:#1a1a2e;">Total</span>'
        f'<span style="text-align:right;color:#1a1a2e;">${_total_target:,.0f}</span>'
        f'<span style="text-align:right;color:{_summary_color};">'
        f'${_total_actual:,.0f}</span>'
        f'<span style="text-align:right;font-size:0.72rem;color:#aaa;">'
        f'→${_total_projected:,.0f}</span>'
        f'<span style="text-align:center;">{_summary_icon}</span></div>'
    )

    st.markdown(_progress_html, unsafe_allow_html=True)

    # Context message
    _remaining = _total_target - _total_actual
    if _remaining > 0:
        _daily_left = _remaining / max(_days_in_month - _today.day, 1)
        st.markdown(
            f'<div style="font-size:0.78rem;color:#555;margin-top:10px;'
            f'line-height:1.5;">'
            f'${_remaining:,.0f} left in your plan budget — '
            f'${_daily_left:,.0f}/day for the next '
            f'{_days_in_month - _today.day} days.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="font-size:0.78rem;color:#ef4444;margin-top:10px;'
            f'line-height:1.5;">'
            f'You\'ve used your full plan budget. '
            f'${abs(_remaining):,.0f} over target with '
            f'{_days_in_month - _today.day} days left.</div>',
            unsafe_allow_html=True,
        )

    conn.close()
