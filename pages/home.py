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
from shared.components import render_savings_gauge, render_category_card
from shared.state import get_conn, get_advisor, escape_dollars


def home_page():
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
        _kero_bonus_on = _bonus_col1.checkbox("Include Kero bonus ($1,500/mo)", value=False, key="dash_kero_bonus")
        _maggie_bonus_on = _bonus_col2.checkbox("Include Maggie bonus ($417/mo)", value=False, key="dash_maggie_bonus")
    _kero_bonus_val = _income_data.get("kero_bonus", 0) if isinstance(_income_data, dict) else 0
    _maggie_bonus_val = _income_data.get("maggie_bonus", 0) if isinstance(_income_data, dict) else 0
    if not _kero_bonus_on:
        _monthly_income -= _kero_bonus_val
    if not _maggie_bonus_on:
        _monthly_income -= _maggie_bonus_val

    _fixed_costs = sum(config.FIXED_MONTHLY_EXPENSES.values())
    _fixed_cats = {"Housing & Utilities", "Debt Payments", "Giving & Church", "Family Support",
                   "Transportation", "Childcare & Education", "Phone & Internet", "Car Insurance"}
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
    _streak = models.compute_savings_streak(conn, savings_target)
    kpi3.metric("Savings Streak", f"{_streak} mo" if _streak > 0 else "0",
                delta="consecutive months on target" if _streak > 0 else "Build your streak!",
                delta_color="off")

    # Daily pace banner
    if _days_left > 0:
        _daily_left = _discretionary_left / _days_left
        if _discretionary_left > 0:
            _pace_html = f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:12px 16px;margin-bottom:12px;"><span style="font-size:1.1rem;font-weight:700;color:#22c55e;">💰 ${_daily_left:,.0f}/day</span> <span style="color:#6b7280;">for the next {_days_left} days to hit your ${savings_target:,} target</span></div>'
        else:
            _pace_html = f'<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px 16px;margin-bottom:12px;"><span style="font-size:1.1rem;font-weight:700;color:#ef4444;">🛑 FREEZE spending</span> <span style="color:#6b7280;">for {_days_left} days — you\'re ${_over_budget:,.0f} over your discretionary budget</span></div>'
        st.markdown(_pace_html, unsafe_allow_html=True)

    # ── 3. GAP CLOSER — Always shown (BUG FIX #3: DB cache) ─────────
    # Show even when on track (reframed as "top opportunities")
    _gap_data = None
    _gap_amount = _over_budget if _over_budget > 0 else _txn_discretionary

    # Check DB cache first (Bug fix #3)
    _gap_data = database.get_gap_closer_cache(conn, selected_month, _gap_amount)

    if _gap_data is None:
        _gap_cache_key = f"gap_closer_{selected_month}_{_gap_amount:.0f}"
        if _gap_cache_key not in st.session_state:
            st.session_state[_gap_cache_key] = None

        if st.session_state[_gap_cache_key] is None:
            advisor = get_advisor()
            if advisor:
                with st.spinner("Analyzing your spending to find savings..."):
                    try:
                        _gap_txns = conn.execute(
                            """SELECT date, description, amount, category FROM transactions
                               WHERE strftime('%Y-%m', date) = ? AND amount < 0 ORDER BY amount ASC""",
                            (selected_month,),
                        ).fetchall()
                        _gap_txn_text = "\n".join(f"{t['date']} | {t['description']} | ${t['amount']:,.2f} | {t['category']}" for t in _gap_txns)
                        _gap_cat_summary = "\n".join(f"  {c['category']}: ${abs(c['total']):,.2f} ({c['txn_count']} txns)" for c in month_breakdown)

                        _gap_result = advisor.generate_gap_closer(
                            gap=_over_budget if _over_budget > 0 else 0,
                            discretionary_spent=_txn_discretionary,
                            discretionary_budget=_disc_budget,
                            days_left=_days_left,
                            savings_target=savings_target,
                            transactions_text=_gap_txn_text,
                            category_summary=_gap_cat_summary,
                        )
                        st.session_state[_gap_cache_key] = _gap_result
                        # Persist to DB cache (Bug fix #3)
                        database.set_gap_closer_cache(conn, selected_month, _gap_amount, _gap_result)
                    except Exception as _e:
                        st.session_state[_gap_cache_key] = {"error": str(_e)}

        _gap_data = st.session_state.get(_gap_cache_key)

    if _gap_data and "actions" in _gap_data:
        if _over_budget > 0:
            st.markdown(f"#### 🔴 Close Your ${_over_budget:,.0f} Gap — Do These 3 Things")
        else:
            st.markdown("#### 💡 Your Top Opportunities This Month")

        _cumulative_recovery = 0
        for _act in _gap_data.get("actions", [])[:3]:
            _recovery = _act.get("recovery", 0)
            _cumulative_recovery += _recovery

            if _over_budget > 0:
                _gap_remaining = max(_over_budget - _cumulative_recovery, 0)
                _pct_remaining = max(_gap_remaining / _over_budget * 100, 0)
                _bar_color = "#ef4444" if _gap_remaining > 0 else "#22c55e"
                _gap_label = f"${_gap_remaining:,.0f} left" if _gap_remaining > 0 else "Closed!"
            else:
                _bar_color = "#22c55e"
                _gap_label = f"+${_cumulative_recovery:,.0f} potential"
                _pct_remaining = 0

            _recovery_text = f"Saves ${_act.get('recovery', 0):,.0f}"
            _act_html = (
                f'<div style="background:white;border:1px solid #e5e7eb;border-radius:10px;padding:12px 16px;margin-bottom:8px;">'
                f'<div style="font-weight:700;color:#1a1a2e;">{_act.get("rank", "")}. {_act.get("category", "")} — {_act.get("merchant", "")}</div>'
                f'<div style="color:#4b5563;margin:6px 0;">{_act.get("action", "")}</div>'
                f'<div style="display:flex;justify-content:space-between;font-size:0.82rem;color:#6b7280;margin-bottom:4px;"><span>{_recovery_text}</span><span>{_gap_label}</span></div>'
                f'<div style="display:flex;align-items:center;gap:10px;">'
                f'<div style="flex:1;height:8px;border-radius:4px;background:#e5e7eb;overflow:hidden;">'
                f'<div style="height:100%;width:{_pct_remaining:.0f}%;background:{_bar_color};border-radius:4px;transition:width 0.3s;"></div></div>'
                f'</div></div>'
            )
            st.markdown(_act_html, unsafe_allow_html=True)

        _total_rec = _gap_data.get("total_recovery", _cumulative_recovery)
        _msg = _gap_data.get("message", "")
        if _msg:
            _summary_color = "#22c55e" if _over_budget == 0 or _total_rec >= _over_budget else "#f59e0b"
            st.markdown(f'<div style="background:#f8f9fb;border-radius:8px;padding:10px 14px;margin-bottom:16px;color:{_summary_color};font-weight:600;">✅ {_msg}</div>', unsafe_allow_html=True)

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
            _in_html = (
                f'<table style="width:100%;font-size:0.9rem;border-collapse:collapse;">'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:4px 0;">Kero (Premera)</td><td style="text-align:right;font-weight:600;">${_kero_net:,.0f}</td></tr>'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:4px 0;">Maggie (Boeing)</td><td style="text-align:right;font-weight:600;">${_maggie_net:,.0f}</td></tr>'
                f'<tr style="border-bottom:2px solid #1a1a2e;"><td style="padding:6px 0;font-weight:700;">Total Income</td><td style="text-align:right;font-weight:700;font-size:1rem;">${_monthly_income:,.0f}</td></tr>'
                f'</table>'
            )
            st.markdown(_in_html, unsafe_allow_html=True)

            st.markdown("")
            st.markdown("**🏠 Fixed Monthly Bills**")
            _known_keys = {
                "Mortgage (Mr. Cooper 6.49%)", "Auto Loan (Chase #2102)", "Car Insurance (CCS Country)",
                "Student Loan 1", "Student Loan 2", "Church (Zelle)", "Family Support (Nermeen)",
                "Church (CC small donations)", "PSE Electric & Gas", "Water/Sewer (NUD)",
                "Internet (Comcast/Xfinity)", "Garbage & Recycling", "T-Mobile", "Mint Mobile (normalized)",
                "Gas (fuel)", "Auto Maintenance (normalized)", "Renters Insurance (AGI)",
                "Digital Subscriptions", "Affirm", "CC Interest (card 3072)",
                "Home Improvement (normalized)", "Travel (normalized)",
            }
            _fixed_groups = {
                "Mortgage": config.FIXED_MONTHLY_EXPENSES.get("Mortgage (Mr. Cooper 6.49%)", 0),
                "Car (loan + insurance)": config.FIXED_MONTHLY_EXPENSES.get("Auto Loan (Chase #2102)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Car Insurance (CCS Country)", 0),
                "Student Loans": config.FIXED_MONTHLY_EXPENSES.get("Student Loan 1", 0) + config.FIXED_MONTHLY_EXPENSES.get("Student Loan 2", 0),
                "Church & Family": config.FIXED_MONTHLY_EXPENSES.get("Church (Zelle)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Family Support (Nermeen)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Church (CC small donations)", 0),
                "Utilities & Internet": config.FIXED_MONTHLY_EXPENSES.get("PSE Electric & Gas", 0) + config.FIXED_MONTHLY_EXPENSES.get("Water/Sewer (NUD)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Internet (Comcast/Xfinity)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Garbage & Recycling", 0),
                "Phone (T-Mobile + Mint)": config.FIXED_MONTHLY_EXPENSES.get("T-Mobile", 0) + config.FIXED_MONTHLY_EXPENSES.get("Mint Mobile (normalized)", 0),
                "Other fixed": config.FIXED_MONTHLY_EXPENSES.get("Gas (fuel)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Auto Maintenance (normalized)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Renters Insurance (AGI)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Digital Subscriptions", 0) + config.FIXED_MONTHLY_EXPENSES.get("Affirm", 0) + config.FIXED_MONTHLY_EXPENSES.get("CC Interest (card 3072)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Home Improvement (normalized)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Travel (normalized)", 0),
            }
            for _k, _v in config.FIXED_MONTHLY_EXPENSES.items():
                if _k not in _known_keys and _v > 0:
                    _short_name = _k.split("(")[0].strip()
                    _fixed_groups[_short_name] = _v
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

    # Quick action buttons (merged from AI Advisor tab)
    st.divider()
    st.markdown("#### 💬 Ask Your Advisor")
    _qa1, _qa2, _qa3, _qa4 = st.columns(4)
    quick = {
        "Savings Check": "Am I on track to meet my savings target? Show me the numbers.",
        "Save This Week": "What are 3 specific things I can do THIS WEEK to save money?",
        "Spending Check": "Compare this month to our average. What's over budget?",
        "Where to Cut": "Where are the easiest $300/month in cuts?",
    }
    _quick_items = list(quick.items())
    for i, col in enumerate([_qa1, _qa2, _qa3, _qa4]):
        if col.button(_quick_items[i][0], use_container_width=True, key=f"quick_{i}"):
            st.session_state.dashboard_chat_history.append({"role": "user", "content": _quick_items[i][1]})

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
        # Build comprehensive context
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
                        st.error(f"Could not get a response: {e}")
                        st.session_state.dashboard_chat_history.append({"role": "assistant", "content": str(e)})
        else:
            with st.chat_message("assistant"):
                st.warning("Set your Anthropic API key in Settings to use the chat.")

    dash_question = st.chat_input("Ask about spending or savings...", key="dashboard_chat_input")
    if dash_question:
        st.session_state.dashboard_chat_history.append({"role": "user", "content": dash_question})
        st.rerun()

    # ── 7. CATEGORY CARDS (severity sorted, collapsed) ────────────────
    st.divider()

    # Claude preventive actions
    @st.cache_data(ttl=300, show_spinner=False)
    def _get_claude_preventive_actions(_month_key: str):
        advisor = get_advisor()
        if not advisor:
            return {}
        _conn = get_conn()
        cats_payload = []
        _mb = database.get_monthly_category_breakdown(_conn, _month_key)
        for cd in _mb:
            c = cd["category"]
            _actual_spend = abs(cd.get("total", 0))
            if _actual_spend == 0:
                continue
            t = analytics_cache.get_cached_trend(_conn, c) or DEFAULT_TREND_DICT
            _avg = float(t.get("mean", 0))
            _pct = ((_actual_spend / _avg) - 1) * 100 if _avg > 0 else 0
            entry = {
                "category": c,
                "current_spend": _actual_spend,
                "historical_avg": _avg,
                "historical_std": float(t.get("std", 0)),
                "trend_direction": t.get("direction", "stable"),
                "slope_per_month": float(t.get("slope_per_month", 0)),
                "pct_vs_mean": _pct,
                "severity": "critical" if _pct > 115 else ("warning" if _pct > 100 else t.get("severity", "normal")),
                "merchants": [],
            }
            _cur_merchants = database.get_merchant_breakdown_for_month(_conn, c, _month_key, limit=5)
            if _cur_merchants:
                entry["merchants"] = [m["name"] for m in _cur_merchants]
                entry["merchant_details"] = [
                    {"name": m["name"], "total": abs(m["total"]), "visits": m["visits"],
                     "avg_per_visit": round(abs(m["total"]) / max(m["visits"], 1), 2)}
                    for m in _cur_merchants
                ]
            cached_pf = analytics_cache.get_cached_prophet(_conn, c)
            if cached_pf and cached_pf.get("forecast"):
                entry["prophet_forecast"] = cached_pf["forecast"]
                entry["prophet_trend"] = cached_pf.get("trend_direction", "")
                entry["prophet_slope"] = cached_pf.get("trend_slope_monthly", 0)
            cached_adv = analytics_cache.get_cached_advanced(_conn, c)
            if cached_adv:
                mk = cached_adv.get("mann_kendall", {})
                entry["mann_kendall_trend"] = mk.get("trend", "")
                entry["mann_kendall_strength"] = mk.get("strength", "")
                entry["mann_kendall_p"] = mk.get("p_value", 1.0)
                seas = cached_adv.get("seasonality", {})
                entry["seasonal"] = seas.get("has_seasonality", False)
                entry["seasonal_strength"] = seas.get("seasonal_strength", 0)
                entry["seasonal_period"] = seas.get("period", 0)
            cats_payload.append(entry)
        _conn.close()

        try:
            actions = advisor.generate_preventive_actions(cats_payload)
            return {a["category"]: a for a in actions if isinstance(a, dict) and "category" in a}
        except Exception:
            return {}

    claude_actions = {}
    advisor = get_advisor()
    if advisor:
        with st.spinner("Analyzing trends & generating preventive actions..."):
            claude_actions = _get_claude_preventive_actions(selected_month)

    # Three-tier card ordering — sorted by severity
    red_cats = []
    yellow_cats = []
    green_cats = []

    for cat_data in month_breakdown:
        cat = cat_data["category"]
        spent = abs(cat_data["total"])
        td = trend_results.get(cat, DEFAULT_TREND_DICT)
        t_mean = float(td.get("mean", 0))
        fill_pct = (spent / t_mean * 100) if t_mean > 0 else 50
        excess = spent - t_mean

        if fill_pct > 115:
            red_cats.append((cat_data, td, excess))
        elif fill_pct > 100:
            yellow_cats.append((cat_data, td, excess))
        else:
            green_cats.append((cat_data, td, excess))

    red_cats.sort(key=lambda x: -x[2])
    yellow_cats.sort(key=lambda x: -x[2])
    green_cats.sort(key=lambda x: -abs(x[0]["total"]))

    if red_cats:
        st.markdown("#### ⚠ Needs Attention")
        for cat_data, td, _ in red_cats:
            render_category_card(cat_data, td, conn, claude_actions, selected_month, expanded_default=False)

    if yellow_cats:
        st.markdown("#### 👀 Monitor")
        cols = st.columns(2)
        for i, (cat_data, td, _) in enumerate(yellow_cats):
            with cols[i % 2]:
                render_category_card(cat_data, td, conn, claude_actions, selected_month, expanded_default=False)

    if green_cats:
        st.markdown("#### ✅ On Track")
        cols = st.columns(2)
        for i, (cat_data, td, _) in enumerate(green_cats):
            with cols[i % 2]:
                render_category_card(cat_data, td, conn, claude_actions, selected_month, expanded_default=False)

    # Donut chart REMOVED (duplicated bar chart)

    conn.close()
