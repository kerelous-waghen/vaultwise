"""Plan page — The Math, Savings Meter, Find Your Savings."""

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
    """Render the Plan page: The Math, Savings Meter, Find Your Savings."""
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
    _flex_budget = _monthly_income - _effective_fixed - _savings_target

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

    _month_cat_totals = {}
    for _mk in _month_keys:
        _ym = _mk["month"]
        _, _by_cat = _get_flexible_spending(
            conn, _ym, _fixed_cats, _muted_cats, _merges)
        _month_cat_totals[_ym] = _by_cat

    # ── Compute category averages across all months ────────────────────
    _all_cats = {}
    for _ym, _by_cat in _month_cat_totals.items():
        for _cat_name, _amt in _by_cat.items():
            _all_cats.setdefault(_cat_name, []).append(_amt)

    _cat_avg_sorted = []
    for _cat_name, _amounts in _all_cats.items():
        _avg = int(round(sum(_amounts) / len(_amounts)))
        if _avg > 20:
            _cat_avg_sorted.append((_cat_name, _avg))
    _cat_avg_sorted.sort(key=lambda x: -x[1])

    _total_typical = sum(avg for _, avg in _cat_avg_sorted)

    # ── Load saved targets into session state ──────────────────────────
    if "plan_targets" not in st.session_state:
        _saved_raw = database.get_setting(conn, "flex_category_targets", "")
        _saved = json.loads(_saved_raw) if _saved_raw else {}
        st.session_state.plan_targets = {
            cat: _saved.get(cat, avg) for cat, avg in _cat_avg_sorted
        }

    # ══════════════════════════════════════════════════════════════════
    # SECTION 1: THE MATH (compact)
    # ══════════════════════════════════════════════════════════════════
    st.markdown("### The Math")

    _math_html = '<div style="font-size:14px;line-height:2;">'
    for label, val, color in [
        ("Income", f"${_monthly_income:,.0f}", "#1a1a2e"),
        ("− Fixed bills", f"−${_effective_fixed:,.0f}", "#dc2626"),
        ("− Savings target", f"−${_savings_target:,.0f}", "#dc2626"),
    ]:
        _math_html += (
            f'<div style="display:flex;justify-content:space-between;">'
            f'<span style="color:#64748b;">{label}</span>'
            f'<span style="font-family:monospace;font-weight:500;'
            f'color:{color};">{val}</span></div>'
        )
    _math_html += (
        f'<div style="border-top:2px solid #0d9488;margin-top:4px;'
        f'padding-top:8px;display:flex;justify-content:space-between;'
        f'align-items:baseline;">'
        f'<b style="font-size:15px;color:#1a1a2e;">= Flex budget</b>'
        f'<b style="font-family:monospace;font-size:20px;color:#0d9488;">'
        f'${_flex_budget:,.0f}/mo</b></div></div>'
    )
    st.markdown(_math_html, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════
    # SECTION 2: SAVINGS METER (placeholder — filled after sliders)
    # ══════════════════════════════════════════════════════════════════
    _meter_placeholder = st.empty()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 3: FIND YOUR SAVINGS (sliders)
    # ══════════════════════════════════════════════════════════════════
    st.markdown("### Find Your Savings")
    st.caption("Drag sliders left to cut spending. "
               "The savings meter above updates live.")

    _main_cats = _cat_avg_sorted[:5]
    _extra_cats = _cat_avg_sorted[5:]

    _total_planned = 0

    for cat, typical in _main_cats:
        _key = f"plan_slider_{cat}"
        _current = st.session_state.plan_targets.get(cat, typical)
        _current = max(0, min(_current, typical))

        val = st.slider(
            label=cat,
            min_value=0,
            max_value=typical,
            value=_current,
            step=25,
            key=_key,
            help=f"Typical: ${typical:,}/mo",
        )
        st.session_state.plan_targets[cat] = val
        _total_planned += val

        _cut = typical - val
        if _cut > 0:
            st.markdown(
                f'<span style="background:#f0fdfa;color:#0d9488;'
                f'padding:2px 8px;border-radius:4px;font-size:12px;'
                f'font-weight:600;">−${_cut:,} saved</span>',
                unsafe_allow_html=True,
            )

    # Extra categories behind expander
    if _extra_cats:
        _extra_total_typical = sum(avg for _, avg in _extra_cats)
        with st.expander(
            f"+ {len(_extra_cats)} smaller categories "
            f"(${_extra_total_typical:,}/mo)"
        ):
            for cat, typical in _extra_cats:
                _key = f"plan_slider_{cat}"
                _current = st.session_state.plan_targets.get(cat, typical)
                _current = max(0, min(_current, typical))

                val = st.slider(
                    label=cat,
                    min_value=0,
                    max_value=typical,
                    value=_current,
                    step=25,
                    key=_key,
                )
                st.session_state.plan_targets[cat] = val
                _total_planned += val

    # ── Total cuts summary ───────────────────────────────────────────
    _total_cuts = _total_typical - _total_planned
    _projected_savings = _monthly_income - _effective_fixed - _total_planned

    if _total_cuts > 0:
        st.markdown(
            f'<div style="background:white;border:1px solid #e2e8f0;'
            f'border-radius:12px;padding:14px 16px;margin-top:16px;'
            f'display:flex;justify-content:space-between;align-items:center;">'
            f'<div>'
            f'<div style="font-family:monospace;font-size:18px;'
            f'font-weight:700;color:#0d9488;">−${_total_cuts:,}/mo</div>'
            f'<div style="font-size:12px;color:#64748b;">'
            f'total planned cuts</div></div></div>',
            unsafe_allow_html=True,
        )

    # ── Save button ──────────────────────────────────────────────────
    if _total_cuts > 0:
        if st.button("Save My Plan", type="primary",
                     use_container_width=True):
            database.set_setting(
                conn, "flex_category_targets",
                json.dumps(st.session_state.plan_targets))
            st.success(
                f"Plan saved! Targeting ${_projected_savings:,}/mo "
                f"in savings (${_total_cuts:,}/mo in cuts)."
            )

    # ══════════════════════════════════════════════════════════════════
    # FILL SAVINGS METER (now that we have _total_planned)
    # ══════════════════════════════════════════════════════════════════
    _ratio = max(0, min(_projected_savings / _savings_target, 1.0)) \
        if _savings_target > 0 else 0

    if _projected_savings >= _savings_target:
        _m_color = "#0d9488"
        _m_bg = "#f0fdfa"
        _m_label_prefix = "✓ Target Hit"
        _m_text = f"On track to save ${_projected_savings:,}/mo"
    elif _projected_savings > 0:
        _m_color = "#d97706"
        _m_bg = "#fffbeb"
        _m_label_prefix = "Monthly Savings"
        _short = _savings_target - _projected_savings
        _m_text = (f"Saving ${_projected_savings:,}/mo — "
                   f"${_short:,} short of target")
    else:
        _m_color = "#dc2626"
        _m_bg = "#fef2f2"
        _m_label_prefix = "Monthly Savings"
        _m_text = (f"Spending ${abs(_projected_savings):,}/mo "
                   f"more than you earn after fixed bills")

    _meter_placeholder.markdown(
        f'<div style="background:{_m_bg};border-radius:12px;'
        f'padding:14px 16px;margin-bottom:16px;">'
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:baseline;margin-bottom:8px;">'
        f'<span style="font-size:12px;font-weight:600;color:{_m_color};'
        f'text-transform:uppercase;letter-spacing:0.05em;">'
        f'{_m_label_prefix}</span>'
        f'<span style="font-family:monospace;font-size:13px;'
        f'color:#64748b;">goal: ${_savings_target:,}</span></div>'
        f'<div style="height:8px;border-radius:4px;'
        f'background:rgba(0,0,0,0.08);overflow:hidden;margin-bottom:8px;">'
        f'<div style="height:100%;border-radius:4px;'
        f'width:{max(_ratio * 100, 0):.0f}%;background:{_m_color};'
        f'transition:width 0.3s;"></div></div>'
        f'<p style="font-size:12px;color:{_m_color};margin:0;'
        f'font-weight:500;">{_m_text}</p></div>',
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════════════════
    # SECTION 4: REAL TALK (conditional)
    # ══════════════════════════════════════════════════════════════════
    if (_total_cuts > 0
            and _projected_savings < _savings_target
            and _total_planned < _total_typical * 0.5):
        _still_short = _savings_target - _projected_savings
        _actual_saving = max(0, _projected_savings)
        st.markdown(
            f'<div style="background:#fffbeb;border:1px solid #fde68a;'
            f'border-radius:12px;padding:14px 16px;margin-top:16px;">'
            f'<p style="font-size:14px;font-weight:600;color:#92400e;'
            f'margin:0 0 6px;">💡 Real talk</p>'
            f'<p style="font-size:13px;color:#92400e;margin:0;'
            f'line-height:1.5;">'
            f'You\'ve cut hard and you\'re still ${_still_short:,} short '
            f'of your ${_savings_target:,} target. Consider: is '
            f'${_savings_target:,}/mo realistic right now, or would '
            f'saving ${_actual_saving:,}/mo actually be a win?</p></div>',
            unsafe_allow_html=True,
        )

    conn.close()
