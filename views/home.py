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
import budget_coach
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

    # Apply merchant category overrides (fixes merchants in wrong categories)
    _overrides = getattr(config, 'MERCHANT_CATEGORY_OVERRIDES', {})
    if _overrides:
        for _pattern, _target_cat in _overrides.items():
            conn.execute(
                "UPDATE transactions SET category = ? "
                "WHERE strftime('%Y-%m', date) = ? "
                "AND LOWER(description) LIKE ? AND category != ?",
                (_target_cat, selected_month, f"%{_pattern.lower()}%", _target_cat),
            )
        conn.commit()

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
    _muted_cats = set(getattr(config, 'MUTED_CATEGORIES', []))

    # Merge categories (e.g., "Education" into "Childcare & Education")
    _merges = getattr(config, 'CATEGORY_MERGES', {})
    _merge_sources = set()
    for _sources in _merges.values():
        _merge_sources.update(_sources)

    # Actually combine merged source amounts into their target category
    for _target, _sources in _merges.items():
        _target_entry = next((c for c in month_breakdown if c["category"] == _target), None)
        for _src in _sources:
            _src_entry = next((c for c in month_breakdown if c["category"] == _src), None)
            if _src_entry:
                if _target_entry:
                    _target_entry["total"] += _src_entry["total"]
                    _target_entry["txn_count"] += _src_entry["txn_count"]
                else:
                    # Target doesn't exist yet — rename the source entry
                    _src_entry["category"] = _target
                    _target_entry = _src_entry
                    _merge_sources.discard(_src)  # keep it since it became the target

    # CRITICAL: Filter month_breakdown BEFORE any math
    # Remove muted categories and merge sources (whose amounts are now in the target)
    month_breakdown = [
        c for c in month_breakdown
        if c["category"] not in _muted_cats
        and c["category"] not in _merge_sources
    ]

    # Recalculate total_spent WITHOUT muted categories
    total_spent = sum(abs(c["total"]) for c in month_breakdown)

    # Compute fixed vs discretionary from the already-filtered breakdown
    _txn_fixed = sum(
        abs(c["total"]) for c in month_breakdown
        if c["category"] in _fixed_cats
    )
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
        txn_fixed=_txn_fixed,
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

    # ── 3. SPENDING COACH — Claude-driven summary + category cards ────
    budget_coach.render(
        conn=conn,
        selected_month=selected_month,
        sel_year=_sel_year,
        sel_month=_sel_month,
        monthly_income=_monthly_income,
        effective_fixed=_effective_fixed,
        savings_target=savings_target,
        disc_budget=_disc_budget,
        txn_discretionary=_txn_discretionary,
        discretionary_left=_discretionary_left,
        over_budget=_over_budget,
        days_left=_days_left,
        days_in_month=_days_in_month,
        fixed_cats=_fixed_cats,
        get_advisor_fn=get_advisor,
        escape_fn=escape_dollars,
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
    _chart_cats = [
        c for c in month_breakdown
        if c["category"] not in _fixed_cats
        and c["category"] not in _muted_cats
    ]
    cats = [c["category"] for c in _chart_cats]
    vals = [abs(c["total"]) for c in _chart_cats]

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
