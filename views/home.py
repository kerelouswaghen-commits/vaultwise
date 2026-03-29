"""Home page — Savings mission control.
Know your status, see actions, take the next step.
"""

from calendar import month_name as _mn, monthrange as _monthrange
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analytics
import analytics_cache
import category_engine
import config
import database
import models
from shared.charts import CHART_LAYOUT, PALETTE, CATEGORY_PALETTE, SEVERITY_MAP, DIRECTION_ICONS, DEFAULT_TREND_DICT
from shared.components import render_savings_gauge
import spending_intelligence
from shared.state import get_conn, get_advisor, escape_dollars


def home_page():
    """Render the Home dashboard: savings gauge, gap closer, category cards, and AI chat."""
    conn = get_conn()
    txn_count = database.get_transaction_count(conn)

    st.markdown("## Home")

    # Data freshness warning
    latest_txn = analytics._get_latest_transaction_date(conn)
    data_age = (date.today() - latest_txn).days
    if data_age > 30:
        st.warning(
            f"Your transaction data is **{data_age} days old** (latest: {latest_txn.isoformat()}). "
            f"Upload recent statements for accurate insights."
        )
    elif data_age > 7:
        st.info(f"Data as of {latest_txn.isoformat()} ({data_age} days ago). Upload recent statements to stay current.")

    if txn_count == 0:
        st.info("Upload statements to see monthly spending breakdown.")
        conn.close()
        st.stop()

    available_months = database.get_available_months(conn)
    if not available_months:
        st.info("No transaction data yet.")
        conn.close()
        st.stop()

    # Month navigation
    selected_month = st.selectbox(
        "Month",
        available_months,
        index=0,
        format_func=lambda m: f"{_mn[int(m.split('-')[1])]} {m.split('-')[0]}",
        label_visibility="collapsed",
    )
    _y, _m = selected_month.split("-")
    month_display = f"{_mn[int(_m)]} {_y}"
    st.markdown(f"### {month_display}")

    # Get this month's data
    _raw_breakdown = database.get_monthly_category_breakdown(conn, selected_month)
    _active_cats_dash = category_engine.get_active_categories(conn)
    month_breakdown = [c for c in _raw_breakdown if c["category"] in _active_cats_dash]
    if not month_breakdown:
        st.info(f"No spending data for {month_display}.")
        conn.close()
        st.stop()

    total_spent = sum(abs(c["total"]) for c in month_breakdown)

    # ── 1. HERO: Savings Goal Gauge ──────────────────────────────────
    _sel_year, _sel_month = int(_y), int(_m)
    _income_data = models.get_income_for_month(_sel_year, _sel_month)
    _monthly_income = _income_data["total_income"] if isinstance(_income_data, dict) else _income_data
    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))

    with st.expander("Bonus income toggles", expanded=False):
        _bonus_col1, _bonus_col2 = st.columns(2)
        _income_keys = list(config.INCOME.keys())
        _label_1 = config.INCOME_LABELS.get(_income_keys[0], {}).get("bonus_label", "Include primary bonus") if _income_keys else "Include primary bonus"
        _label_2 = config.INCOME_LABELS.get(_income_keys[1] if len(_income_keys) > 1 else "", {}).get("bonus_label", "Include secondary bonus")
        _kero_bonus_on = _bonus_col1.checkbox(_label_1, value=False, key="dash_kero_bonus")
        _maggie_bonus_on = _bonus_col2.checkbox(_label_2, value=False, key="dash_maggie_bonus")
    _kero_bonus_val = _income_data.get("kero_bonus", 0) if isinstance(_income_data, dict) else 0
    _maggie_bonus_val = _income_data.get("maggie_bonus", 0) if isinstance(_income_data, dict) else 0
    if not _kero_bonus_on:
        _monthly_income -= _kero_bonus_val
    if not _maggie_bonus_on:
        _monthly_income -= _maggie_bonus_val

    _fixed_costs = sum(config.FIXED_MONTHLY_EXPENSES.values())
    _fixed_cats = {"Housing & Utilities", "Debt Payments", "Family Support", "Transportation",
                   "Phone & Internet", "Car Insurance"}
    _fixed_cats.update(config.MONARCH_FIXED_MAP.keys())
    _txn_fixed = sum(abs(c["total"]) for c in month_breakdown if c["category"] in _fixed_cats)
    _txn_discretionary = total_spent - _txn_fixed
    _effective_fixed = max(_fixed_costs, _txn_fixed)
    _total_outflow = _effective_fixed + _txn_discretionary
    _budget_limit = _monthly_income - savings_target
    _saved = _monthly_income - _total_outflow
    _gap = _saved - savings_target
    _on_track = _saved >= savings_target
    _spent_pct = min(_total_outflow / _budget_limit * 100, 100) if _budget_limit > 0 else 100

    if _on_track:
        _gauge_color = "#22c55e"
        _status_text = f"HITTING YOUR TARGET — ${_gap:,.0f} above goal"
        _status_icon = "✅"
    elif _saved > 0:
        _gauge_color = "#f59e0b"
        _status_text = f"AT RISK — ${abs(_gap):,.0f} short of target"
        _status_icon = "⚠️"
    else:
        _gauge_color = "#ef4444"
        _status_text = f"OVER BUDGET — ${abs(_saved):,.0f} in the red"
        _status_icon = "🔴"

    render_savings_gauge(
        month_display=month_display, saved=_saved, gauge_color=_gauge_color,
        status_icon=_status_icon, status_text=_status_text,
        total_outflow=_total_outflow, budget_limit=_budget_limit,
        savings_target=savings_target, effective_fixed=_effective_fixed,
        txn_discretionary=_txn_discretionary, spent_pct=_spent_pct,
    )

    # ── 2. KPI ROW: Savings Rate, Daily Pace, Streak ─────────────────
    _disc_budget = _monthly_income - _effective_fixed - savings_target
    _discretionary_left = max(_disc_budget - _txn_discretionary, 0)
    _over_budget = max(_txn_discretionary - _disc_budget, 0)

    _days_in_month = _monthrange(_sel_year, _sel_month)[1]
    _days_left = max(_days_in_month - min(date.today().day, _days_in_month), 1) if (date.today().year, date.today().month) == (_sel_year, _sel_month) else 0

    # Savings Rate
    _savings_rate = (_saved / _monthly_income * 100) if _monthly_income > 0 else 0
    _target_rate = (savings_target / _monthly_income * 100) if _monthly_income > 0 else 0

    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("Savings Rate", f"{_savings_rate:.0f}%",
                delta=f"Target: {_target_rate:.0f}%",
                delta_color="off")

    # Daily Pace
    if _days_left > 0:
        _daily_left = _discretionary_left / _days_left
        kpi2.metric("Daily Budget Left", f"${_daily_left:,.0f}/day",
                    delta=f"{_days_left} days left",
                    delta_color="off")
    else:
        kpi2.metric("Month Status", "Complete" if (date.today().year, date.today().month) != (_sel_year, _sel_month) else "Today")

    # Savings Streak
    try:
        _streak = models.compute_savings_streak(conn, savings_target)
    except Exception:
        _streak = 0
    kpi3.metric("Savings Streak", f"{_streak} mo" if _streak > 0 else "0",
                delta="consecutive months on target" if _streak > 0 else "Build your streak!",
                delta_color="off")

    # Daily pace banner
    if _days_left > 0:
        _daily_left = _discretionary_left / _days_left
        if _discretionary_left > 0:
            _pace_html = f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:12px 16px;margin-bottom:12px;"><span style="font-size:1.1rem;font-weight:700;color:#22c55e;">💰 ${_daily_left:,.0f}/day</span> <span style="color:#6b7280;">for the next {_days_left} days to hit your ${savings_target:,} target</span></div>'
        else:
            _freeze_detail = f" Keeping spending minimal for the last {_days_left} days stops it from growing." if _days_left > 0 else " The month is wrapping up."
            _pace_html = f'<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px 16px;margin-bottom:12px;"><span style="font-size:1.1rem;font-weight:700;color:#ef4444;">💸 ${_over_budget:,.0f} from savings</span> <span style="color:#6b7280;">used this month.{_freeze_detail}</span></div>'
        st.markdown(_pace_html, unsafe_allow_html=True)

    # ── 3. SPENDING COACH — Claude-driven summary + category cards ────
    _budget_status = spending_intelligence.get_category_budget_status(conn)
    _flex_status = [s for s in _budget_status if s["category"] not in _fixed_cats]
    _flex_status.sort(key=lambda x: x["current_spend"], reverse=True)

    # Decompose "Other" by merchant
    _other_detail = ""
    if any(s["category"] == "Other" for s in _flex_status):
        _other_rows = conn.execute("""
            SELECT description, SUM(ABS(amount)) as total, COUNT(*) as cnt
            FROM transactions
            WHERE strftime('%Y-%m', date) = ? AND category = 'Other' AND amount < 0
            GROUP BY description ORDER BY total DESC LIMIT 5
        """, (selected_month,)).fetchall()
        if _other_rows:
            _other_detail = "Breakdown of 'Other': " + ", ".join(
                f"{r['description']}: ${r['total']:,.0f}" for r in _other_rows)

    # Build spending data for Claude
    _spending_lines = "\n".join(
        f"- {s['category']}: ${s['current_spend']:,.0f} this month, "
        f"typical ${s['monthly_average']:,.0f}, median ${s['monthly_median']:,.0f}, "
        f"projected month-end ${s['projected_month_end']:,.0f}, "
        f"percentile {s['percentile']}, savings potential ${s['savings_potential']:,.0f}"
        for s in _flex_status[:12]
    )

    # Pull Prophet forecasts
    _forecast_lines = ""
    for _fs in _flex_status[:8]:
        _pf = analytics_cache.get_cached_prophet(conn, _fs["category"])
        if _pf and _pf.get("forecast"):
            _nxt = _pf["forecast"][0]
            _forecast_lines += (
                f"- {_fs['category']}: next month ${_nxt['predicted']:,.0f} "
                f"(range ${_nxt.get('lower', 0):,.0f}–${_nxt.get('upper', 0):,.0f})\n"
            )

    # 6-month history per category (for sparklines)
    _hist_data = {}
    for _fs in _flex_status[:12]:
        _cat_name = _fs["category"]
        _hist_rows = database.get_category_monthly_history(conn, _cat_name, months=6)
        _hist_data[_cat_name] = {
            "months": [r["month"][-2:] for r in _hist_rows],
            "values": [round(abs(r["total"])) for r in _hist_rows],
        }

    # Top merchants per category
    _merchant_data = {}
    for _fs in _flex_status[:12]:
        _cat_name = _fs["category"]
        _merch_rows = database.get_merchant_breakdown_for_month(conn, _cat_name, selected_month, limit=4)
        _merchant_data[_cat_name] = [
            {"name": r["name"][:28], "amount": round(abs(r["total"]))}
            for r in _merch_rows
        ]

    _excluded_list = ", ".join(sorted(_fixed_cats))

    # ── Call Claude for summary + per-category interpretation ──
    _coach_key = f"coach_{selected_month}_{int(_txn_discretionary)}"
    if _coach_key not in st.session_state:
        st.session_state[_coach_key] = None

    if st.session_state[_coach_key] is None:
        advisor = get_advisor()
        if advisor:
            with st.spinner("Analyzing spending..."):
                try:
                    _prompt = (
                        "You are a budget coach inside a personal finance app. "
                        "Analyze this month's spending and generate a summary "
                        "PLUS per-category insights.\n\n"
                        f"BUDGET CONTEXT:\n"
                        f"- Monthly income: ${_monthly_income:,.0f}\n"
                        f"- Fixed bills: ${_effective_fixed:,.0f}\n"
                        f"- Savings target: ${savings_target:,}/mo\n"
                        f"- Spending money: ${_disc_budget:,.0f}\n"
                        f"- Spent so far: ${_txn_discretionary:,.0f}\n"
                        f"- Remaining: ${_discretionary_left:,.0f}\n"
                        f"- Day {date.today().day} of {_days_in_month} "
                        f"({_days_left} days left)\n\n"
                        f"FLEXIBLE SPENDING BY CATEGORY:\n{_spending_lines}\n\n"
                        f"{_other_detail}\n\n"
                        f"FORECASTS (Prophet, next month):\n"
                        f"{_forecast_lines if _forecast_lines else 'No forecast data.'}\n\n"
                        f"EXCLUDED (fixed bills — never recommend cutting): {_excluded_list}\n\n"
                        "GENERATE TWO THINGS:\n\n"
                        "1. SUMMARY: A brief warm overview (3-5 sentences). "
                        "If over budget, explain where the extra came from. "
                        "If on track, be brief and encouraging. Use forecast data "
                        "in your forward-looking sentence when relevant. "
                        "Never suggest returning purchases or undoing transactions.\n\n"
                        "2. PER-CATEGORY: For each flexible category, assign:\n"
                        "   - badge: short label like 'normal', 'hot pace', "
                        "'elevated', 'one-time', 'under pace', 'low'\n"
                        "   - badge_icon: one emoji\n"
                        "   - bar_color: hex color for the progress bar "
                        "('#22c55e' green=fine, '#f59e0b' amber=watch, "
                        "'#dc2626' red=over)\n"
                        "   - bar_pct: 0-100, how full the bar should be "
                        "(100 = at or above typical spend)\n"
                        "   - one_liner: one sentence about this category\n\n"
                        "Return ONLY valid JSON:\n"
                        '{"headline": "10 words max summary",'
                        '"status": "on_track|watch|over",'
                        '"summary_color": "#hex for headline",'
                        '"body": "3-5 sentence summary",'
                        '"categories": [{"name": "category name",'
                        '"badge": "normal","badge_icon": "✅",'
                        '"bar_color": "#22c55e","bar_pct": 65,'
                        '"one_liner": "brief note"}]}\n'
                        "No markdown. No preamble. Just JSON."
                    )
                    _resp = advisor.generate_coach_response(_prompt, max_tokens=2048)
                    st.session_state[_coach_key] = _resp
                except Exception:
                    st.session_state[_coach_key] = {
                        "headline": "Spending summary",
                        "status": "watch" if _over_budget > 0 else "on_track",
                        "summary_color": "#f59e0b" if _over_budget > 0 else "#22c55e",
                        "body": f"Spent ${_txn_discretionary:,.0f} of ${_disc_budget:,.0f} spending money.",
                        "categories": [
                            {"name": s["category"], "badge": "—", "badge_icon": "",
                             "bar_color": "#6b7280",
                             "bar_pct": min(int(s["pct_of_average"]), 100),
                             "one_liner": f"${s['current_spend']:,.0f} spent"}
                            for s in _flex_status[:10]
                        ],
                    }

    # ── Render Claude summary ─────────────────────────────────────────
    _coach = st.session_state.get(_coach_key)
    if _coach:
        _sc = _coach.get("summary_color", "#6b7280")
        st.markdown(
            f'<div style="background:{_sc}0a;border:1px solid {_sc}20;'
            f'border-radius:12px;padding:10px 14px;margin-bottom:10px;">'
            f'<div style="font-weight:700;font-size:0.9rem;color:#1a1a2e;'
            f'margin-bottom:4px;">{escape_dollars(_coach.get("headline", ""))}'
            f'</div>'
            f'<div style="font-size:0.84rem;line-height:1.5;color:#555;">'
            f'{escape_dollars(_coach.get("body", ""))}</div></div>',
            unsafe_allow_html=True,
        )

        # ── Category Cards (ALWAYS visible) ───────────────────────────
        st.markdown(
            '<div style="font-size:0.68rem;color:#aaa;font-weight:700;'
            'text-transform:uppercase;letter-spacing:0.6px;'
            'margin:10px 0 6px 2px;">Your Spending Money Breakdown</div>',
            unsafe_allow_html=True,
        )
        _claude_cats = {c["name"]: c for c in _coach.get("categories", [])}

        for _fs in _flex_status:
            _cat_name = _fs["category"]
            _spent = _fs["current_spend"]
            _typical = _fs["monthly_average"]
            _median = _fs["monthly_median"]
            _pctile = _fs["percentile"]

            _ci = _claude_cats.get(_cat_name, {})
            _badge = _ci.get("badge", "")
            _badge_icon = _ci.get("badge_icon", "")
            _bar_color = _ci.get("bar_color", "#6b7280")
            _bar_pct = _ci.get("bar_pct", 50)
            _one_liner = _ci.get("one_liner", "")

            # Badge styling
            if any(k in _badge for k in ("normal", "under", "low")):
                _badge_bg, _badge_fg = "#f0fdf4", "#16a34a"
            elif any(k in _badge for k in ("hot", "one-time", "spike")):
                _badge_bg, _badge_fg = "#fffbeb", "#d97706"
            elif any(k in _badge for k in ("elevated", "high", "over")):
                _badge_bg, _badge_fg = "#fef2f2", "#dc2626"
            else:
                _badge_bg, _badge_fg = "#f5f5f5", "#888"

            # Collapsed card (always visible)
            st.markdown(
                f'<div style="background:#fff;border:1px solid #eae7e1;'
                f'border-radius:12px;padding:10px 13px;margin-bottom:2px;">'
                f'<div style="display:flex;justify-content:space-between;'
                f'align-items:center;margin-bottom:4px;">'
                f'<div style="display:flex;align-items:center;gap:6px;'
                f'flex:1;overflow:hidden;">'
                f'<span style="font-weight:700;font-size:0.88rem;color:#1a1a2e;'
                f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
                f'{_cat_name}</span>'
                f'<span style="font-size:0.62rem;font-weight:700;padding:2px 7px;'
                f'border-radius:10px;white-space:nowrap;flex-shrink:0;'
                f'background:{_badge_bg};color:{_badge_fg};">'
                f'{_badge_icon} {_badge}</span></div>'
                f'<span style="font-weight:800;font-size:0.92rem;color:{_bar_color};'
                f'white-space:nowrap;flex-shrink:0;">\\${_spent:,.0f}</span></div>'
                f'<div style="height:4px;border-radius:2px;background:#eee;'
                f'overflow:hidden;margin:3px 0;">'
                f'<div style="height:100%;width:{min(_bar_pct, 100)}%;'
                f'background:{_bar_color};border-radius:2px;"></div></div>'
                f'<div style="font-size:0.76rem;color:#999;margin-top:3px;">'
                f'{escape_dollars(_one_liner)} · typical ~\\${_typical:,.0f}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Expandable detail
            with st.expander(f"Details: {_cat_name}", expanded=False):
                _sc1, _sc2, _sc3 = st.columns(3)
                _sc1.metric("Typical", f"${_typical:,.0f}")
                _sc2.metric("Median", f"${_median:,.0f}")
                _sc3.metric("Percentile", f"{_pctile}th")

                # Sparkline
                _hist = _hist_data.get(_cat_name, {})
                _spark_vals = _hist.get("values", [])
                _spark_months = _hist.get("months", [])
                if len(_spark_vals) >= 2:
                    _spark_fig = go.Figure()
                    _spark_fig.add_trace(go.Scatter(
                        x=_spark_months, y=_spark_vals,
                        mode="lines+markers",
                        line=dict(color=_bar_color, width=2.5),
                        marker=dict(size=6, color=_bar_color),
                        fill="tozeroy",
                        fillcolor=f"rgba({int(_bar_color[1:3],16)},{int(_bar_color[3:5],16)},{int(_bar_color[5:7],16)},0.06)" if _bar_color.startswith("#") and len(_bar_color) == 7 else "rgba(107,114,128,0.06)",
                        hovertemplate="$%{y:,.0f}<extra></extra>",
                    ))
                    _spark_fig.update_layout(
                        height=120, margin=dict(t=10, b=20, l=40, r=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(showgrid=False, tickfont=dict(size=9)),
                        yaxis=dict(showgrid=True, gridcolor="#f0f0f0",
                                   tickfont=dict(size=9), tickformat="$,.0f"),
                        showlegend=False,
                    )
                    st.plotly_chart(_spark_fig, use_container_width=True,
                                    config={"displayModeBar": False})

                # Forecast
                _pf = analytics_cache.get_cached_prophet(conn, _cat_name)
                if _pf and _pf.get("forecast"):
                    _nxt = _pf["forecast"][0]
                    _fc_pred = _nxt.get("predicted", 0)
                    _fc_low = _nxt.get("lower", 0)
                    _fc_high = _nxt.get("upper", 0)
                    st.markdown(
                        f'<div style="background:linear-gradient(135deg,#f0f4ff,#e8f0fe);'
                        f'border:1px solid #d4e0f7;border-radius:10px;padding:10px 12px;'
                        f'margin-bottom:10px;">'
                        f'<div style="display:flex;align-items:center;gap:4px;margin-bottom:4px;">'
                        f'<span style="font-size:0.65rem;color:#5b7bb4;font-weight:700;'
                        f'text-transform:uppercase;letter-spacing:0.4px;">Next Month Forecast</span></div>'
                        f'<div style="display:flex;align-items:baseline;gap:6px;">'
                        f'<span style="font-size:1.15rem;font-weight:800;color:#1a4a8a;">'
                        f'\\${_fc_pred:,.0f}</span>'
                        f'<span style="font-size:0.72rem;color:#7fa3d4;">'
                        f'\\${_fc_low:,.0f} – \\${_fc_high:,.0f}</span></div></div>',
                        unsafe_allow_html=True,
                    )

                # Top merchants
                _merchs = _merchant_data.get(_cat_name, [])
                if _merchs:
                    st.markdown(
                        '<div style="font-size:0.65rem;color:#bbb;font-weight:700;'
                        'text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px;">'
                        'Where It Went</div>',
                        unsafe_allow_html=True,
                    )
                    for _m in _merchs:
                        st.markdown(
                            f'<div style="display:flex;justify-content:space-between;'
                            f'padding:4px 0;border-bottom:1px solid #f5f3ef;font-size:0.82rem;">'
                            f'<span style="color:#555;">{escape_dollars(_m["name"])}</span>'
                            f'<span style="font-weight:700;color:#1a1a2e;">\\${_m["amount"]:,.0f}</span></div>',
                            unsafe_allow_html=True,
                        )

        # Savings dip callout
        if _over_budget > 0:
            st.markdown(
                f'<div style="background:#fef2f2;border:1px solid #fecaca;'
                f'border-radius:10px;padding:9px 13px;margin-top:8px;'
                f'font-size:0.84rem;color:#991b1b;">'
                f'\\${_over_budget:,.0f} came from savings this month.</div>',
                unsafe_allow_html=True,
            )

    # Detailed financial breakdown
    _kero_net = _income_data.get("kero_net", 0) if isinstance(_income_data, dict) else 0
    _maggie_net = _income_data.get("maggie_net", 0) if isinstance(_income_data, dict) else 0
    if _kero_bonus_on:
        _kero_net += _kero_bonus_val
    if _maggie_bonus_on:
        _maggie_net += _maggie_bonus_val

    with st.expander("Monthly Budget Breakdown", expanded=False):
        _left, _right = st.columns(2)
        with _left:
            st.markdown("**💵 Money In**")
            _ik = list(config.INCOME.keys())
            _inc_label_1 = config.INCOME_LABELS.get(_ik[0], {}).get("label", "Primary") if _ik else "Primary"
            _inc_label_2 = config.INCOME_LABELS.get(_ik[1] if len(_ik) > 1 else "", {}).get("label", "Secondary")
            _in_html = (
                f'<table style="width:100%;font-size:0.9rem;border-collapse:collapse;">'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:4px 0;">{_inc_label_1}</td><td style="text-align:right;font-weight:600;">${_kero_net:,.0f}</td></tr>'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:4px 0;">{_inc_label_2}</td><td style="text-align:right;font-weight:600;">${_maggie_net:,.0f}</td></tr>'
                f'<tr style="border-bottom:2px solid #1a1a2e;"><td style="padding:6px 0;font-weight:700;">Total Income</td><td style="text-align:right;font-weight:700;font-size:1rem;">${_monthly_income:,.0f}</td></tr>'
                f'</table>'
            )
            st.markdown(_in_html, unsafe_allow_html=True)

            st.markdown("")
            st.markdown("**🏠 Fixed Monthly Bills**")
            _fixed_groups = {}
            for _group_label, _expense_keys in config.FIXED_BILL_GROUPS.items():
                _group_total = sum(config.FIXED_MONTHLY_EXPENSES.get(k, 0) for k in _expense_keys)
                if _group_total > 0:
                    _fixed_groups[_group_label] = _group_total
            _all_grouped = {k for keys in config.FIXED_BILL_GROUPS.values() for k in keys}
            for _k, _v in config.FIXED_MONTHLY_EXPENSES.items():
                if _k not in _all_grouped and _v > 0:
                    _fixed_groups[_k.split("(")[0].strip()] = _v
            _bills_html = '<table style="width:100%;font-size:0.85rem;border-collapse:collapse;">'
            for label, amt in _fixed_groups.items():
                _bills_html += f'<tr style="border-bottom:1px solid #f3f4f6;"><td style="padding:3px 0;color:#6b7280;">{label}</td><td style="text-align:right;">${amt:,.0f}</td></tr>'
            _bills_html += f'<tr style="border-top:2px solid #1a1a2e;"><td style="padding:5px 0;font-weight:700;">Total Fixed</td><td style="text-align:right;font-weight:700;">${_effective_fixed:,.0f}</td></tr>'
            _bills_html += '</table>'
            st.markdown(_bills_html, unsafe_allow_html=True)

        with _right:
            st.markdown("**🧮 The Math**")
            _math_html = (
                f'<table style="width:100%;font-size:0.9rem;border-collapse:collapse;">'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:5px 0;">Income</td><td style="text-align:right;font-weight:600;">${_monthly_income:,.0f}</td></tr>'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:5px 0;">− Fixed bills</td><td style="text-align:right;color:#ef4444;">−${_effective_fixed:,.0f}</td></tr>'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:5px 0;">− Savings target</td><td style="text-align:right;color:#7c3aed;">−${savings_target:,.0f}</td></tr>'
                f'<tr style="border-bottom:2px solid #1a1a2e;background:#f0fdf4;"><td style="padding:6px 0;font-weight:700;">= Discretionary budget</td><td style="text-align:right;font-weight:700;font-size:1.05rem;">${_disc_budget:,.0f}</td></tr>'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:5px 0;">− Spent this month</td><td style="text-align:right;color:#ef4444;">−${_txn_discretionary:,.0f}</td></tr>'
                f'<tr style="background:{"#f0fdf4" if _discretionary_left > 0 else "#fef2f2"};"><td style="padding:6px 0;font-weight:700;">= Still available</td>'
                f'<td style="text-align:right;font-weight:700;font-size:1.1rem;color:{"#22c55e" if _discretionary_left > 0 else "#ef4444"};">${_discretionary_left:,.0f}</td></tr>'
                f'</table>'
            )
            st.markdown(_math_html, unsafe_allow_html=True)

            st.markdown("")
            st.markdown("**📊 Summary**")
            _s1, _s2 = st.columns(2)
            _s1.metric("Saved", f"${_saved:,.0f}")
            _s2.metric("Target", f"${savings_target:,}")
            st.metric("Gap to Target", f"${_gap:+,.0f}", delta_color="normal" if _gap >= 0 else "inverse")

    # ── 4. ANALYTICS CACHE CHECK ──────────────────────────────────────
    _cache_stale = analytics_cache.is_stale(conn)
    if _cache_stale:
        st.warning(
            "Analytics cache is stale (last refreshed: "
            f"{analytics_cache.get_last_refresh_display(conn)}). "
            "Hit **Refresh Analytics** below to update trend data."
        )
    if st.button("Refresh Analytics", type="secondary" if not _cache_stale else "primary"):
        with st.spinner("Refreshing analytics cache (trends, forecasts, merchants)..."):
            analytics_cache.refresh_all(conn)
        st.rerun()

    # ── 5. CATEGORY BAR CHART (severity colored) ─────────────────────
    cats = [c["category"] for c in month_breakdown]
    vals = [abs(c["total"]) for c in month_breakdown]

    trend_results = {}
    for cat in cats:
        cached_t = analytics_cache.get_cached_trend(conn, cat)
        if cached_t:
            trend_results[cat] = cached_t
        else:
            trend_results[cat] = {**DEFAULT_TREND_DICT, "category": cat}

    bar_colors = [
        SEVERITY_MAP.get(trend_results.get(c, DEFAULT_TREND_DICT).get("severity", "normal"),
                         SEVERITY_MAP["normal"])["color"]
        for c in cats
    ]

    fig = go.Figure(go.Bar(
        x=vals, y=cats, orientation="h",
        marker_color=bar_colors, marker_line_width=0,
        text=[f"${v:,.0f}" for v in vals],
        textposition="auto", textfont_size=11,
        hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(**CHART_LAYOUT, height=max(350, len(cats) * 38 + 80),
                     showlegend=False, yaxis=dict(autorange="reversed"),
                     xaxis=dict(title="Amount ($)", gridcolor="#f3f4f6", tickformat="$,.0f"))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.caption("Bar color: 🔴 needs action | 🟠 watch | 🟢 on track (based on statistical trend analysis)")

    # ── 6. CHAT (merged from Dashboard + AI Advisor) ─────────────────
    if "dashboard_chat_history" not in st.session_state:
        st.session_state.dashboard_chat_history = []
    if "dashboard_chat_month" not in st.session_state:
        st.session_state.dashboard_chat_month = ""
    if st.session_state.dashboard_chat_month != selected_month:
        st.session_state.dashboard_chat_history = []
        st.session_state.dashboard_chat_month = selected_month

    # Quick action buttons — 2x2 grid for mobile
    st.divider()
    st.markdown("#### 💬 Ask Your Advisor")
    _quick_actions = {
        "Savings Check": "Am I on track to meet my savings target? Show me the numbers.",
        "Save This Week": "What are 3 specific things I can do THIS WEEK to save money?",
        "Spending Check": "Compare this month to our average. What's over budget?",
        "Where to Cut": "Where are the easiest $300/month in cuts?",
    }

    def _ask_quick(question):
        st.session_state.dashboard_chat_history.append({"role": "user", "content": question})

    _qi = list(_quick_actions.items())
    _r1c1, _r1c2 = st.columns(2)
    _r1c1.button(_qi[0][0], use_container_width=True, key="quick_0", on_click=_ask_quick, args=(_qi[0][1],))
    _r1c2.button(_qi[1][0], use_container_width=True, key="quick_1", on_click=_ask_quick, args=(_qi[1][1],))
    _r2c1, _r2c2 = st.columns(2)
    _r2c1.button(_qi[2][0], use_container_width=True, key="quick_2", on_click=_ask_quick, args=(_qi[2][1],))
    _r2c2.button(_qi[3][0], use_container_width=True, key="quick_3", on_click=_ask_quick, args=(_qi[3][1],))

    # Display chat history
    for msg in st.session_state.dashboard_chat_history:
        with st.chat_message(msg["role"]):
            display_text = escape_dollars(msg["content"]) if msg["role"] == "assistant" else msg["content"]
            st.markdown(display_text)

    # Check for pending response
    needs_response = (
        st.session_state.dashboard_chat_history
        and st.session_state.dashboard_chat_history[-1]["role"] == "user"
    )

    if needs_response:
        pending_msg = st.session_state.dashboard_chat_history[-1]["content"]
        _all_txns = conn.execute(
            """SELECT date, description, amount, category FROM transactions
               WHERE strftime('%Y-%m', date) = ? ORDER BY category, date""",
            (selected_month,),
        ).fetchall()
        _txn_lines = [f"{t['date']} | {t['description']} | ${t['amount']:,.2f} | {t['category']}" for t in _all_txns]
        _txn_context = "\n".join(_txn_lines)
        _cat_summary = "\n".join(f"  {c['category']}: ${abs(c['total']):,.2f} ({c['txn_count']} txns)" for c in month_breakdown)

        _forecast_lines = ""
        for _cat in [c["category"] for c in month_breakdown[:8]]:
            _pf = analytics_cache.get_cached_prophet(conn, _cat)
            if _pf and _pf.get("forecast"):
                _next = _pf["forecast"][0]
                _forecast_lines += f"  {_cat}: ${_next['predicted']:,.0f} predicted next month\n"

        _unified_context = (
            f"DASHBOARD DATA for {month_display}:\n"
            f"- Income (no bonus): ${_monthly_income:,.0f}\n"
            f"- Fixed bills: ${_effective_fixed:,.0f}\n"
            f"- Savings target: ${savings_target:,}/mo\n"
            f"- Discretionary budget: ${_disc_budget:,.0f}\n"
            f"- Discretionary spent: ${_txn_discretionary:,.0f}\n"
            f"- Over budget by: ${_over_budget:,.0f}\n"
            f"- Days left in month: {_days_left}\n"
            f"- Saved so far: ${_saved:,.0f}\n"
            f"- Gap to target: ${_gap:+,.0f}\n"
            f"- Total tracked: ${total_spent:,.0f} ({sum(c['txn_count'] for c in month_breakdown)} txns)\n\n"
            f"CATEGORY BREAKDOWN:\n{_cat_summary}\n\n"
            f"FORECASTS FOR NEXT MONTH:\n{_forecast_lines}\n"
            f"ALL TRANSACTIONS:\n{_txn_context}\n\n"
            f"You can explain any number shown on the dashboard, break down any category, "
            f"explain any transaction, interpret any forecast, or give savings advice. "
            f"Be realistic. Items already purchased may not be returnable. "
            f"Focus on: reducing remaining spending this month, planning next month's budget, "
            f"identifying habits to change, and using forecast data to prevent future overages."
        )

        advisor = get_advisor()
        if advisor:
            with st.chat_message("assistant"):
                with st.spinner("Analyzing..."):
                    try:
                        result = advisor.get_advisor_response(
                            user_message=f"{_unified_context}\n\nUser question: {pending_msg}",
                            conversation_history=st.session_state.dashboard_chat_history[:-1],
                            financial_context={"month": selected_month, "month_display": month_display, "total_spent": total_spent, "savings_target": savings_target, "gap": _over_budget},
                            tactical_context={},
                        )
                        response = result.get("response", str(result))
                        st.markdown(escape_dollars(response))
                        st.session_state.dashboard_chat_history.append({"role": "assistant", "content": response})
                    except Exception as e:
                        st.error("Could not get a response. Please try again.")
                        st.session_state.dashboard_chat_history.append({"role": "assistant", "content": str(e)})
        else:
            with st.chat_message("assistant"):
                st.warning("Set your Anthropic API key in Settings to use the chat.")

    # ── STICKY CHAT INPUT (always at bottom of screen) ──────────────
    dash_question = st.chat_input("Ask about spending or savings...")
    if dash_question:
        st.session_state.dashboard_chat_history.append({"role": "user", "content": dash_question})
        st.rerun()

    conn.close()
