"""Plan page — The Math, Your Trend, What You Can Control."""

import calendar as _cal
from datetime import date as _date

import plotly.graph_objects as go
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
    """Render the Plan page with budget math, trend chart, and what-if sliders."""
    conn = get_conn()

    # ── Recompute key variables ───────────────────────────────────────
    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))
    _today = _date.today()
    _income_data = models.get_income_for_month(_today.year, _today.month)
    _monthly_income = _income_data["total_income"] if isinstance(_income_data, dict) else _income_data
    # Exclude bonuses by default (same as dashboard)
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

    _hist_rows = []         # [{month, total}, ...]
    _month_cat_totals = {}  # {month: {cat: amount}}
    for _mk in _month_keys:
        _ym = _mk["month"]
        _total, _by_cat = _get_flexible_spending(
            conn, _ym, _fixed_cats, _muted_cats, _merges)
        _hist_rows.append({"month": _ym, "total": _total})
        _month_cat_totals[_ym] = _by_cat

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
        f'<span style="font-weight:800;">= Spending money</span>'
        f'<span style="font-weight:800;font-size:1.05rem;color:#16a34a;">'
        f'${_spending_money:,.0f}/mo</span></div></div>'
    )
    st.markdown(_html, unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:0.65rem;color:#bbb;font-weight:700;'
        'text-transform:uppercase;letter-spacing:0.5px;margin:14px 0 6px;">'
        'Last 6 Months</div>',
        unsafe_allow_html=True,
    )

    # Header
    _table = (
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr 24px;'
        'gap:4px;font-size:0.6rem;color:#bbb;font-weight:700;'
        'text-transform:uppercase;margin-bottom:4px;padding:0 2px;">'
        '<span>Month</span>'
        '<span style="text-align:right;">Spent</span>'
        '<span style="text-align:right;">vs Budget</span>'
        '<span></span></div>'
    )

    for r in _hist_rows:
        _mo = r["month"]  # "2026-03"
        _mo_num = int(_mo[-2:])
        _mo_year = _mo[:4]
        _mo_label = f"{_cal.month_abbr[_mo_num]} '{_mo_year[-2:]}"
        _actual = round(r["total"])
        _diff = _spending_money - _actual
        _icon = "✅" if _diff >= 0 else "❌"
        _spent_color = "#ef4444" if _actual > _spending_money else "#1a1a2e"
        _diff_color = "#16a34a" if _diff >= 0 else "#ef4444"
        _diff_str = f"+${_diff:,.0f}" if _diff >= 0 else f"−${abs(_diff):,.0f}"

        _table += (
            f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr 24px;'
            f'gap:4px;font-size:0.82rem;padding:5px 2px;'
            f'border-bottom:1px solid #f5f3ef;">'
            f'<span style="color:#555;font-weight:500;">{_mo_label}</span>'
            f'<span style="text-align:right;font-weight:600;color:{_spent_color};">'
            f'${_actual:,.0f}</span>'
            f'<span style="text-align:right;font-weight:700;color:{_diff_color};">'
            f'{_diff_str}</span>'
            f'<span style="text-align:center;">{_icon}</span></div>'
        )

    st.markdown(_table, unsafe_allow_html=True)

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 2: YOUR TREND
    # ══════════════════════════════════════════════════════════════════
    st.markdown("### Your Trend")

    _months = [r["month"] for r in reversed(_hist_rows)]
    _values = [round(r["total"]) for r in reversed(_hist_rows)]
    _colors = ["#ef4444" if v > _spending_money else "#22c55e" for v in _values]
    _labels = [
        f"{_cal.month_abbr[int(m[-2:])]} '{m[2:4]}" for m in _months
    ]

    _fig = go.Figure()

    # Bars
    _fig.add_trace(go.Bar(
        x=_labels, y=_values,
        marker_color=_colors,
        hovertemplate="%{x}: $%{y:,.0f}<extra></extra>",
        text=[f"${v:,.0f}" for v in _values],
        textposition="outside",
        textfont=dict(size=10, color="#888"),
    ))

    # Budget line
    _fig.add_hline(
        y=_spending_money,
        line_dash="dash", line_color="#1a1a2e", line_width=1.5,
        annotation_text=f"${_spending_money:,.0f} budget",
        annotation_position="top right",
        annotation_font=dict(size=10, color="#888"),
    )

    _fig.update_layout(
        height=200,
        margin=dict(t=30, b=30, l=50, r=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, tickfont=dict(size=10, color="#aaa")),
        yaxis=dict(
            showgrid=True, gridcolor="#f5f5f5",
            tickfont=dict(size=9, color="#bbb"),
            tickformat="$,.0f", zeroline=False,
        ),
        showlegend=False,
    )

    st.plotly_chart(_fig, width="stretch",
                    config={"displayModeBar": False})

    # Metric pills
    _avg_actual = round(sum(_values) / max(len(_values), 1))
    _months_hit = sum(1 for v in _values if v <= _spending_money)

    _c1, _c2 = st.columns(2)
    _c1.metric("Avg Monthly Spending", f"${_avg_actual:,.0f}",
               delta=f"vs ${_spending_money:,.0f} budget",
               delta_color="inverse")
    _c2.metric("Hit Target", f"{_months_hit} of {len(_values)}",
               delta="months")

    if _avg_actual > _spending_money:
        _gap = _avg_actual - _spending_money
        st.markdown(
            f'<div style="background:#fef2f2;border:1px solid #fecaca;'
            f'border-radius:8px;padding:8px 12px;margin-top:8px;'
            f'font-size:0.82rem;color:#991b1b;line-height:1.4;">'
            f'Typical spending is ~${_gap:,.0f}/mo above budget. '
            f'The What-If below helps find where to cut.</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 3: WHAT YOU CAN CONTROL
    # ══════════════════════════════════════════════════════════════════
    # Compute average monthly spend per flexible category from the same data
    _all_cats = {}  # {cat: [month_amounts]}
    for _ym, _by_cat in _month_cat_totals.items():
        for _cat_name, _amt in _by_cat.items():
            _all_cats.setdefault(_cat_name, []).append(_amt)
    _cat_avgs = []
    for _cat_name, _amounts in _all_cats.items():
        _avg = round(sum(_amounts) / len(_amounts))
        if _avg > 20:
            _cat_avgs.append({"category": _cat_name, "avg_spend": _avg})
    _cat_avgs.sort(key=lambda c: c["avg_spend"], reverse=True)

    st.markdown("### What You Can Control")
    st.caption(
        f"Drag sliders to see if your total fits inside "
        f"${_spending_money:,.0f}. Only flexible categories — "
        f"fixed bills are excluded."
    )

    _slider_values = {}
    _typical_total = 0

    for _cat in _cat_avgs[:8]:  # top 8 by average
        _name = _cat["category"]
        _avg = int(_cat["avg_spend"])
        _typical_total += _avg

        # Minimum: roughly 10% of average (floor for necessities)
        _min_val = max(int(_avg * 0.1), 0)

        _val = st.slider(
            f"{_name} (typical ${_avg:,.0f})",
            min_value=_min_val,
            max_value=_avg,
            value=_avg,
            step=25,
            key=f"whatif_{_name}",
        )
        _slider_values[_name] = _val

    # ── Result card ───────────────────────────────────────────────────
    _new_total = sum(_slider_values.values())
    _total_cuts = _typical_total - _new_total
    _gap = _new_total - _spending_money
    _hits_target = _gap <= 0

    # Visual result card
    if _hits_target:
        _bg = "linear-gradient(135deg, #f0fdf4, #dcfce7)"
        _border = "#bbf7d0"
        _headline_color = "#16a34a"
        _headline = "✅ Fits!"
    else:
        _bg = "linear-gradient(135deg, #fef2f2, #fee2e2)"
        _border = "#fecaca"
        _headline_color = "#ef4444"
        _headline = f"${_gap:,.0f} over"

    _cuts_badge = ""
    if _total_cuts > 0:
        _cuts_badge = (
            f'<span style="font-size:0.7rem;font-weight:700;color:#16a34a;'
            f'background:#f0fdf4;padding:3px 8px;border-radius:8px;">'
            f'saving ${_total_cuts:,.0f}/mo</span>'
        )

    # Progress bar: new total vs budget
    _bar_pct = min((_new_total / (_spending_money * 2)) * 100, 100)
    _bar_color = ("linear-gradient(90deg, #22c55e, #16a34a)" if _hits_target
                  else "linear-gradient(90deg, #f59e0b, #ef4444)")
    _marker_pct = (_spending_money / (_spending_money * 2)) * 100

    _result_html = (
        f'<div style="background:{_bg};border:1px solid {_border};'
        f'border-radius:12px;padding:14px 16px;margin-top:10px;">'

        # Headline row
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:center;margin-bottom:8px;">'
        f'<span style="font-size:1.3rem;font-weight:800;color:{_headline_color};">'
        f'{_headline}</span>{_cuts_badge}</div>'

        # Progress bar
        f'<div style="position:relative;margin-bottom:16px;">'
        f'<div style="height:12px;background:#e5e7eb;border-radius:6px;overflow:hidden;">'
        f'<div style="height:100%;width:{_bar_pct}%;background:{_bar_color};'
        f'border-radius:6px;transition:width 0.3s;"></div></div>'
        # Budget marker
        f'<div style="position:absolute;top:-2px;left:{_marker_pct}%;'
        f'width:3px;height:16px;background:#1a1a2e;border-radius:2px;"></div>'
        f'<div style="position:absolute;top:16px;left:{_marker_pct}%;'
        f'transform:translateX(-50%);font-size:0.55rem;color:#888;">'
        f'${_spending_money:,.0f}</div></div>'

        # Totals
        f'<div style="display:flex;justify-content:space-between;'
        f'font-size:0.82rem;color:#555;margin-top:6px;">'
        f'<span>New total: <b>${_new_total:,.0f}</b></span>'
        f'<span>Budget: <b>${_spending_money:,.0f}</b></span></div>'
    )

    # Context message
    if _hits_target:
        _buffer = _spending_money - _new_total
        _total_saved = _savings_target + _buffer
        _result_html += (
            f'<div style="font-size:0.78rem;color:#166534;margin-top:8px;'
            f'line-height:1.4;">These cuts would save ~${_total_saved:,.0f}/mo total.'
        )
        if _buffer > 0:
            _result_html += f' That\'s ${_buffer:,.0f} buffer beyond your target.'
        _result_html += '</div>'
    elif _total_cuts > 0:
        _result_html += (
            f'<div style="font-size:0.78rem;color:#991b1b;margin-top:8px;'
            f'line-height:1.4;">Still ${_gap:,.0f} over. Try another category, '
            f'or consider whether ${_savings_target:,.0f}/mo target is realistic '
            f'right now.</div>'
        )
    else:
        _result_html += (
            f'<div style="font-size:0.78rem;color:#991b1b;margin-top:8px;'
            f'line-height:1.4;">Typical spending is '
            f'${_typical_total - _spending_money:,.0f}/mo above budget. '
            f'Drag the sliders to find which cuts close the gap.</div>'
        )

    _result_html += '</div>'
    st.markdown(_result_html, unsafe_allow_html=True)

    conn.close()
