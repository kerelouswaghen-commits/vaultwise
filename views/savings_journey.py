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

# Category colors for the stacked bar
_CAT_COLORS = [
    "#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6",
    "#8b5cf6", "#ef4444", "#14b8a6", "#f97316", "#64748b",
]


def _get_flexible_spending(conn, year_month: str, fixed_cats, muted_cats, merges):
    """Get flexible spending for a month using same logic as dashboard.

    Returns (total_flexible, category_totals_dict).
    """
    _raw = database.get_monthly_category_breakdown(conn, year_month)
    _active = category_engine.get_active_categories(conn)
    _cats = [c for c in _raw if c["category"] in _active]

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

    _cats = [c for c in _cats
             if c["category"] not in muted_cats
             and c["category"] not in _merge_sources]

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

    # ── Category sets ──────────────────────────────────────────────────
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

    # ── Compute category averages ──────────────────────────────────────
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

    # ── Load saved targets ─────────────────────────────────────────────
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
    # SECTION 2: SAVINGS METER + SPENDING BAR (placeholders)
    # ══════════════════════════════════════════════════════════════════
    _meter_placeholder = st.empty()
    _bar_placeholder = st.empty()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 3: FIND YOUR SAVINGS (sliders with visual feedback)
    # ══════════════════════════════════════════════════════════════════
    st.markdown("### Find Your Savings")
    st.caption("Drag sliders left to cut spending. "
               "Watch the savings meter and spending bar update live.")

    _main_cats = _cat_avg_sorted[:5]
    _extra_cats = _cat_avg_sorted[5:]

    _total_planned = 0
    _slider_results = []  # (cat, typical, val, color_idx)

    for i, (cat, typical) in enumerate(_main_cats):
        _key = f"plan_slider_{cat}"
        _current = st.session_state.plan_targets.get(cat, typical)
        _current = max(0, min(_current, typical))
        _color = _CAT_COLORS[i % len(_CAT_COLORS)]

        # Category header with color dot and cut badge
        _cut_preview = typical - _current
        _badge = ""
        if _cut_preview > 0:
            _badge = (
                f'<span style="font-size:11px;font-weight:600;color:#0d9488;'
                f'background:#f0fdfa;padding:2px 6px;border-radius:4px;'
                f'margin-left:6px;">−${_cut_preview:,}</span>'
            )
        st.markdown(
            f'<div style="display:flex;align-items:center;margin-bottom:-10px;'
            f'margin-top:8px;">'
            f'<span style="width:10px;height:10px;border-radius:50%;'
            f'background:{_color};display:inline-block;margin-right:6px;'
            f'flex-shrink:0;"></span>'
            f'<span style="font-size:13px;font-weight:500;color:#1a1a2e;">'
            f'{cat}</span>'
            f'<span style="font-size:11px;color:#94a3b8;margin-left:6px;">'
            f'typical ${typical:,}</span>'
            f'{_badge}</div>',
            unsafe_allow_html=True,
        )

        val = st.slider(
            label=cat,
            min_value=0,
            max_value=typical,
            value=_current,
            step=25,
            key=_key,
            label_visibility="collapsed",
        )
        st.session_state.plan_targets[cat] = val
        _total_planned += val
        _slider_results.append((cat, typical, val, i))

    # Extra categories behind expander
    if _extra_cats:
        _extra_total_typical = sum(avg for _, avg in _extra_cats)
        with st.expander(
            f"+ {len(_extra_cats)} smaller categories "
            f"(${_extra_total_typical:,}/mo)"
        ):
            for i, (cat, typical) in enumerate(_extra_cats, start=len(_main_cats)):
                _key = f"plan_slider_{cat}"
                _current = st.session_state.plan_targets.get(cat, typical)
                _current = max(0, min(_current, typical))
                _color = _CAT_COLORS[i % len(_CAT_COLORS)]

                _cut_preview = typical - _current
                _badge = ""
                if _cut_preview > 0:
                    _badge = (
                        f'<span style="font-size:11px;font-weight:600;'
                        f'color:#0d9488;background:#f0fdfa;padding:2px 6px;'
                        f'border-radius:4px;margin-left:6px;">'
                        f'−${_cut_preview:,}</span>'
                    )
                st.markdown(
                    f'<div style="display:flex;align-items:center;'
                    f'margin-bottom:-10px;margin-top:4px;">'
                    f'<span style="width:8px;height:8px;border-radius:50%;'
                    f'background:{_color};display:inline-block;'
                    f'margin-right:6px;"></span>'
                    f'<span style="font-size:12px;color:#1a1a2e;">'
                    f'{cat}</span>'
                    f'<span style="font-size:10px;color:#94a3b8;'
                    f'margin-left:4px;">typical ${typical:,}</span>'
                    f'{_badge}</div>',
                    unsafe_allow_html=True,
                )

                val = st.slider(
                    label=cat,
                    min_value=0,
                    max_value=typical,
                    value=_current,
                    step=25,
                    key=_key,
                    label_visibility="collapsed",
                )
                st.session_state.plan_targets[cat] = val
                _total_planned += val
                _slider_results.append((cat, typical, val, i))

    # ── Computed values ──────────────────────────────────────────────
    _total_cuts = _total_typical - _total_planned
    _projected_savings = _monthly_income - _effective_fixed - _total_planned

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
    # FILL SAVINGS METER (big visual dial)
    # ══════════════════════════════════════════════════════════════════
    _ratio = max(0, min(_projected_savings / _savings_target, 1.0)) \
        if _savings_target > 0 else 0

    if _projected_savings >= _savings_target:
        _m_color = "#0d9488"
        _m_bg = "#f0fdfa"
        _m_border = "#99f6e4"
        _m_label = "TARGET HIT"
        _m_emoji = "🎯"
        _m_text = f"Saving ${_projected_savings:,}/mo"
    elif _projected_savings > 0:
        _m_color = "#d97706"
        _m_bg = "#fffbeb"
        _m_border = "#fde68a"
        _m_label = "GETTING CLOSER"
        _m_emoji = "📈"
        _short = _savings_target - _projected_savings
        _m_text = f"Saving ${_projected_savings:,}/mo — ${_short:,} to go"
    else:
        _m_color = "#dc2626"
        _m_bg = "#fef2f2"
        _m_border = "#fecaca"
        _m_label = "OVER BUDGET"
        _m_emoji = "📉"
        _m_text = f"${abs(_projected_savings):,}/mo over what you earn"

    # Large savings number + progress ring (CSS-based)
    _ring_pct = max(0, min(_ratio * 100, 100))
    _ring_bg = f"conic-gradient({_m_color} {_ring_pct}%, #e5e7eb {_ring_pct}%)"

    _cuts_note = ""
    if _total_cuts > 0:
        _cuts_note = (
            f'<div style="font-size:11px;color:#0d9488;font-weight:600;'
            f'margin-top:4px;">cutting ${_total_cuts:,}/mo from typical</div>'
        )

    _meter_placeholder.markdown(
        f'<div style="background:{_m_bg};border:1px solid {_m_border};'
        f'border-radius:16px;padding:20px;margin:16px 0;">'

        # Top row: ring + savings number
        f'<div style="display:flex;align-items:center;gap:16px;">'

        # Progress ring
        f'<div style="width:64px;height:64px;border-radius:50%;'
        f'background:{_ring_bg};display:flex;align-items:center;'
        f'justify-content:center;flex-shrink:0;">'
        f'<div style="width:48px;height:48px;border-radius:50%;'
        f'background:{_m_bg};display:flex;align-items:center;'
        f'justify-content:center;font-size:22px;">{_m_emoji}</div></div>'

        # Text block
        f'<div style="flex:1;">'
        f'<div style="font-size:11px;font-weight:700;color:{_m_color};'
        f'text-transform:uppercase;letter-spacing:0.08em;'
        f'margin-bottom:2px;">{_m_label}</div>'
        f'<div style="font-family:monospace;font-size:24px;font-weight:700;'
        f'color:{_m_color};line-height:1.2;">'
        f'${_projected_savings:,}/mo</div>'
        f'<div style="font-size:12px;color:#64748b;margin-top:2px;">'
        f'{_m_text}</div>'
        f'{_cuts_note}'
        f'</div>'

        # Goal badge
        f'<div style="text-align:right;flex-shrink:0;">'
        f'<div style="font-size:10px;color:#94a3b8;text-transform:uppercase;'
        f'letter-spacing:0.05em;">Goal</div>'
        f'<div style="font-family:monospace;font-size:16px;font-weight:600;'
        f'color:#64748b;">${_savings_target:,}</div></div>'

        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════════════════
    # FILL SPENDING BREAKDOWN BAR (stacked segments by category)
    # ══════════════════════════════════════════════════════════════════
    # Build stacked bar segments
    _bar_max = max(_total_planned, _flex_budget) * 1.1  # 10% padding
    if _bar_max <= 0:
        _bar_max = 1

    _segments_html = ""
    for cat, typical, val, idx in _slider_results:
        if val <= 0:
            continue
        _seg_pct = (val / _bar_max) * 100
        _seg_color = _CAT_COLORS[idx % len(_CAT_COLORS)]
        _segments_html += (
            f'<div style="width:{_seg_pct}%;height:100%;'
            f'background:{_seg_color};transition:width 0.3s;" '
            f'title="{cat}: ${val:,}"></div>'
        )

    # Budget marker position
    _budget_marker_pct = min((_flex_budget / _bar_max) * 100, 100)

    _bar_placeholder.markdown(
        f'<div style="background:white;border:1px solid #e2e8f0;'
        f'border-radius:12px;padding:12px 16px;margin-bottom:16px;">'

        # Label
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:baseline;margin-bottom:8px;">'
        f'<span style="font-size:11px;font-weight:600;color:#64748b;'
        f'text-transform:uppercase;letter-spacing:0.05em;">'
        f'Planned Spending</span>'
        f'<span style="font-family:monospace;font-size:13px;'
        f'color:#1a1a2e;font-weight:600;">'
        f'${_total_planned:,} of ${_flex_budget:,} budget</span></div>'

        # Stacked bar with budget marker
        f'<div style="position:relative;margin-bottom:6px;">'
        f'<div style="height:16px;background:#f1f5f9;border-radius:8px;'
        f'overflow:hidden;display:flex;">'
        f'{_segments_html}</div>'

        # Budget line marker
        f'<div style="position:absolute;top:-3px;left:{_budget_marker_pct}%;'
        f'width:2px;height:22px;background:#1a1a2e;border-radius:1px;'
        f'"></div>'
        f'<div style="position:absolute;top:20px;'
        f'left:{_budget_marker_pct}%;transform:translateX(-50%);'
        f'font-size:9px;color:#64748b;white-space:nowrap;">'
        f'${_flex_budget:,} budget</div></div>'

        # Legend (compact, 2 per row)
        f'<div style="display:flex;flex-wrap:wrap;gap:4px 12px;'
        f'margin-top:14px;">'
        + "".join(
            f'<div style="display:flex;align-items:center;gap:4px;'
            f'font-size:10px;color:#64748b;">'
            f'<span style="width:8px;height:8px;border-radius:2px;'
            f'background:{_CAT_COLORS[idx % len(_CAT_COLORS)]};'
            f'flex-shrink:0;"></span>'
            f'{cat[:15]}{"..." if len(cat) > 15 else ""} ${val:,}</div>'
            for cat, typical, val, idx in _slider_results if val > 0
        )
        + f'</div></div>',
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
