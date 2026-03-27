"""Settings page — One-time configuration.
Reordered by change frequency: Savings Target > Income > Fixed > Categories > API > Telegram > Monarch > DB.
"""

import json
import os
from collections import Counter
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analytics
import analytics_cache
import category_engine
import config
import database
import reports
from shared.charts import CHART_LAYOUT, PALETTE, CATEGORY_PALETTE
from shared.state import get_conn, get_advisor, escape_dollars


def settings_page():
    st.markdown("## Settings")
    conn = get_conn()

    # ── 1. Savings Target (most frequently changed) ──────────────────
    st.markdown("#### Savings Target")
    _set_c1, _set_c2 = st.columns(2)
    _cur_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))
    _new_target = _set_c1.number_input("Monthly Savings Target ($/mo)", min_value=0, max_value=10000, value=_cur_target, step=100, key="settings_savings_target")
    if _new_target != _cur_target:
        database.set_setting(conn, "monthly_savings_target", str(_new_target))

    _period_opts = ["weekly", "biweekly", "monthly"]
    _cur_period = database.get_setting(conn, "report_period", "weekly")
    _p_idx = _period_opts.index(_cur_period) if _cur_period in _period_opts else 0
    _new_period = _set_c2.selectbox("Report Frequency", _period_opts, index=_p_idx,
        format_func=lambda x: {"weekly": "Every Week", "biweekly": "Every 2 Weeks", "monthly": "Monthly"}[x], key="settings_report_period")
    if _new_period != _cur_period:
        database.set_setting(conn, "report_period", _new_period)

    st.divider()

    # ── 2. Income ─────────────────────────────────────────────────────
    st.markdown("#### Income")
    _inc_c1, _inc_c2 = st.columns(2)

    with _inc_c1:
        st.markdown("**Kero (Premera)**")
        _k_bi = st.number_input("Biweekly take-home", value=config.INCOME["kero"]["biweekly_net"], step=50, key="kero_biweekly")
        _k_bonus = st.number_input("Annual bonus (after tax)", value=config.INCOME["kero"]["bonus_annual_after_tax"], step=500, key="kero_bonus_annual")

    with _inc_c2:
        st.markdown("**Maggie (Boeing)**")
        _m_bi = st.number_input("Biweekly take-home", value=config.INCOME["maggie"]["biweekly_net"], step=50, key="maggie_biweekly")
        _m_bonus = st.number_input("Annual bonus (after tax)", value=config.INCOME["maggie"]["bonus_annual_after_tax"], step=500, key="maggie_bonus_annual")

    _k_monthly = round(_k_bi * 26 / 12)
    _m_monthly = round(_m_bi * 26 / 12)
    _k_bonus_spread = round(_k_bonus / 12)
    _m_bonus_spread = round(_m_bonus / 12)
    _combined = _k_monthly + _k_bonus_spread + _m_monthly + _m_bonus_spread
    st.caption(f"Monthly: Kero ${_k_monthly:,} + ${_k_bonus_spread:,} bonus | Maggie ${_m_monthly:,} + ${_m_bonus_spread:,} bonus | **Combined: ${_combined:,}/mo**")

    if st.button("Save Income Changes", key="save_income"):
        config.INCOME["kero"]["biweekly_net"] = _k_bi
        config.INCOME["kero"]["monthly_net"] = _k_monthly
        config.INCOME["kero"]["bonus_annual_after_tax"] = _k_bonus
        config.INCOME["kero"]["bonus_spread_monthly"] = _k_bonus_spread
        config.INCOME["maggie"]["biweekly_net"] = _m_bi
        config.INCOME["maggie"]["monthly_net"] = _m_monthly
        config.INCOME["maggie"]["bonus_annual_after_tax"] = _m_bonus
        config.INCOME["maggie"]["bonus_spread_monthly"] = _m_bonus_spread
        config.INCOME["combined_monthly_take_home"] = _combined
        database.set_setting(conn, "income_config", json.dumps(config.INCOME))
        st.success(f"Income updated! Combined: ${_combined:,}/mo")

    st.divider()

    # ── 3. Fixed Monthly Expenses ─────────────────────────────────────
    st.markdown("#### Fixed Monthly Expenses")

    def _remove_expense(label):
        config.FIXED_MONTHLY_EXPENSES.pop(label, None)
        _conn_r = get_conn()
        database.set_setting(_conn_r, "fixed_expenses_config", json.dumps(config.FIXED_MONTHLY_EXPENSES))
        _conn_r.close()

    _exp_changes = {}
    _exp_cols = st.columns(2)
    _items = list(config.FIXED_MONTHLY_EXPENSES.items())
    _half = (len(_items) + 1) // 2
    for col_idx, col in enumerate(_exp_cols):
        with col:
            _slice = _items[col_idx * _half:(col_idx + 1) * _half]
            for _label, _amt in _slice:
                _short = _label.split("(")[0].strip()[:30]
                _inp_col, _del_col = st.columns([4, 1])
                _new_val = _inp_col.number_input(_short, value=_amt, step=10, key=f"fixed_{_label}")
                _del_col.button("✕", key=f"del_{_label}", help=f"Remove {_short}",
                                on_click=_remove_expense, args=(_label,))
                if _new_val != _amt:
                    _exp_changes[_label] = _new_val

    _new_fixed_total = sum(_exp_changes.get(k, v) for k, v in config.FIXED_MONTHLY_EXPENSES.items())
    st.caption(f"**Total fixed: ${_new_fixed_total:,}/mo** (+ ~${getattr(config, 'CC_MONTHLY_AVERAGE', 5894):,} credit card avg)")

    if _exp_changes and st.button("Save Expense Changes", key="save_expenses"):
        for _label, _val in _exp_changes.items():
            config.FIXED_MONTHLY_EXPENSES[_label] = _val
        database.set_setting(conn, "fixed_expenses_config", json.dumps(config.FIXED_MONTHLY_EXPENSES))
        _new_fixed_total = sum(config.FIXED_MONTHLY_EXPENSES.values())
        st.success(f"Expenses updated! Total fixed: ${_new_fixed_total:,}/mo")
        st.rerun()

    with st.expander("Add New Expense", expanded=False):
        _add_c1, _add_c2 = st.columns([3, 1])
        _new_exp_name = _add_c1.text_input("Expense name", placeholder="e.g. Gym Membership", key="new_exp_name")
        _new_exp_amt = _add_c2.number_input("$/mo", value=0, step=10, min_value=0, key="new_exp_amt")
        if st.button("Add Expense", key="add_expense") and _new_exp_name and _new_exp_amt > 0:
            config.FIXED_MONTHLY_EXPENSES[_new_exp_name] = _new_exp_amt
            database.set_setting(conn, "fixed_expenses_config", json.dumps(config.FIXED_MONTHLY_EXPENSES))
            st.success(f"Added {_new_exp_name}: ${_new_exp_amt:,}/mo")
            st.rerun()

    st.divider()

    # ── 4. Categories (moved from Transactions) ──────────────────────
    st.markdown("#### Categories")

    if "recat_proposals" not in st.session_state:
        st.session_state.recat_proposals = None
    if "recat_applied" not in st.session_state:
        st.session_state.recat_applied = None

    st.markdown("##### Current Categories")
    st.caption("Edit names, add rows, or delete rows. Changes take effect when you click 'Save Categories'.")

    current_cats = category_engine.get_active_categories(conn)
    cat_hierarchy = category_engine.get_category_hierarchy(conn)
    edit_data = []
    for c in current_cats:
        info = cat_hierarchy.get(c, {})
        edit_data.append({"Category": c, "Description": info.get("description", ""), "Keep": True})

    edit_df = pd.DataFrame(edit_data)
    edited = st.data_editor(
        edit_df, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "Category": st.column_config.TextColumn("Category", width="medium"),
            "Description": st.column_config.TextColumn("Description", width="large"),
            "Keep": st.column_config.CheckboxColumn("Keep", default=True, width="small"),
        },
    )

    col_save, col_reset = st.columns(2)
    with col_save:
        if st.button("Save Categories", type="primary"):
            kept = edited[edited["Keep"] == True]
            saved_count = 0
            for _, row in kept.iterrows():
                name = str(row["Category"]).strip()
                desc = str(row["Description"]).strip() if pd.notna(row["Description"]) else ""
                if name:
                    database.upsert_category_definition(conn, name=name, description=desc, sort_order=saved_count + 1)
                    saved_count += 1
            removed = edited[edited["Keep"] == False]
            for _, row in removed.iterrows():
                name = str(row["Category"]).strip()
                if name:
                    conn.execute("UPDATE category_definitions SET is_active = 0 WHERE name = ?", (name,))
            conn.commit()
            analytics_cache.invalidate(conn)
            st.success(f"Saved {saved_count} categories.")
            st.rerun()

    with col_reset:
        if st.button("Reset to Default"):
            conn.execute("DELETE FROM category_definitions")
            conn.commit()
            analytics_cache.invalidate(conn)
            st.success("Reset to default categories.")
            st.rerun()

    st.markdown("##### Ask Claude for Suggestions")
    st.caption("Claude will analyze your spending patterns and suggest an optimal category structure.")

    guide_text = st.text_area(
        "Guide Claude (optional)",
        placeholder="e.g., I don't want Transfers & Payments. Split Costco into groceries vs non-food.",
        height=80,
    )

    if st.button("Get Suggestions from Claude"):
        advisor = get_advisor()
        if advisor is None:
            st.error("Claude API key not configured.")
        else:
            with st.spinner("Claude is analyzing your transactions..."):
                try:
                    result = category_engine.generate_categories(conn, advisor, user_guidance=guide_text)
                    if guide_text:
                        result["user_guidance"] = guide_text
                    st.session_state.recat_proposals = result
                    st.session_state.recat_applied = None
                except Exception as e:
                    st.error(f"Failed: {e}")

    if st.session_state.recat_proposals is not None:
        result = st.session_state.recat_proposals
        if result.get("changes_summary"):
            st.info(f"**Claude's suggestion:** {result['changes_summary']}")
        proposed = result.get("proposed_categories", [])
        if proposed:
            st.markdown(f"**Proposed ({len(proposed)} categories):**")
            prop_df = pd.DataFrame(proposed)
            display_cols = [c for c in ["name", "description"] if c in prop_df.columns]
            if display_cols:
                st.dataframe(
                    prop_df[display_cols].rename(columns={"name": "Category", "description": "Description"}),
                    use_container_width=True, hide_index=True,
                )
        rename_mapping = result.get("rename_mapping", {})
        if rename_mapping:
            st.markdown(f"**Renames:** {len(rename_mapping)} categories")
            for old, new in rename_mapping.items():
                st.caption(f"{old} → **{new}**")
        tags = result.get("subcategory_tags", [])
        if tags:
            st.caption(f"Suggested tags: {', '.join(tags)}")

        col_apply, col_clear = st.columns(2)
        with col_apply:
            if st.session_state.recat_applied is None:
                if st.button("Apply Claude's Suggestions", type="primary"):
                    with st.spinner("Applying..."):
                        applied = category_engine.apply_recategorization(conn, result)
                        st.session_state.recat_applied = applied
                    st.rerun()
            else:
                st.success(
                    f"Applied! {st.session_state.recat_applied['categories_created']} categories created, "
                    f"{st.session_state.recat_applied['transactions_updated']} transactions updated."
                )
        with col_clear:
            if st.button("Dismiss"):
                st.session_state.recat_proposals = None
                st.session_state.recat_applied = None
                st.rerun()

    st.divider()

    # ── 5. Claude Auto-Update ─────────────────────────────────────────
    st.markdown("#### Auto-Update with Claude")
    st.caption("Claude will analyze your recent transactions and suggest updates to income and expenses.")
    if st.button("Ask Claude to Review My Settings", key="claude_auto_settings"):
        advisor = get_advisor()
        if advisor:
            with st.spinner("Claude is analyzing your transactions..."):
                _recent_txns = conn.execute("""
                    SELECT date, description, amount, category FROM transactions
                    WHERE date >= date('now', '-90 days') ORDER BY date DESC
                """).fetchall()
                _txn_text = "\n".join(f"{t['date']} | {t['description']} | ${t['amount']:,.2f} | {t['category']}" for t in _recent_txns[:200])

                _prompt = (
                    f"Analyze my last 90 days of transactions and tell me if my budget config is accurate.\n\n"
                    f"CURRENT CONFIG:\n"
                    f"- Kero biweekly: ${config.INCOME['kero']['biweekly_net']:,}\n"
                    f"- Maggie biweekly: ${config.INCOME['maggie']['biweekly_net']:,}\n"
                    f"- Fixed expenses total: ${sum(config.FIXED_MONTHLY_EXPENSES.values()):,}/mo\n\n"
                    f"RECENT TRANSACTIONS:\n{_txn_text}\n\n"
                    f"For each config value, tell me: is it correct based on the data? If not, what should it be?"
                )
                try:
                    result = advisor.get_advisor_response(
                        user_message=_prompt,
                        conversation_history=[],
                        financial_context={"month": "settings_review"},
                        tactical_context={},
                    )
                    response = result.get("response", str(result))
                    st.markdown(escape_dollars(response))
                except Exception as e:
                    st.error(f"Failed: {e}")
        else:
            st.warning("Set your API key above first.")

    st.divider()

    # ── 6. Claude API ─────────────────────────────────────────────────
    st.markdown("#### Claude API")
    current_key = os.environ.get("ANTHROPIC_API_KEY", "") or database.get_setting(conn, "anthropic_api_key")
    if current_key:
        st.success(f"API key: ...{current_key[-8:]}")
        if st.button("Clear API Key"):
            database.delete_setting(conn, "anthropic_api_key")
            os.environ.pop("ANTHROPIC_API_KEY", None)
            st.session_state.advisor = None
            st.rerun()
    else:
        new_key = st.text_input("Anthropic API Key", type="password")
        if st.button("Save Key") and new_key:
            database.set_setting(conn, "anthropic_api_key", new_key)
            os.environ["ANTHROPIC_API_KEY"] = new_key
            st.session_state.advisor = None
            st.rerun()

    st.divider()

    # ── 7. Weekly Reports & Telegram ──────────────────────────────────
    st.markdown("#### Weekly Reports & Telegram")

    with st.expander("Weekly Report", expanded=False):
        import analytics as _rpt_analytics

        _rpt_advisor = get_advisor()
        data = reports.gather_report_data(conn)
        week_total = abs(data["week_spending_total"])
        week_txns = data["week_transactions"]

        if not week_txns:
            st.info("No transactions this week.")
        else:
            from calendar import month_name as _mname
            today = date.today()
            st.markdown(f"### Week of {data['week_start']} to {data['report_date']}")

            _rpt_savings_target = int(database.get_setting(conn, "monthly_savings_target", "1000"))

            last_week_txns = database.get_transactions(
                conn,
                start_date=(date.today() - timedelta(days=14)).isoformat(),
                end_date=(date.today() - timedelta(days=7)).isoformat(),
            )
            last_week_total = abs(sum(t["amount"] for t in last_week_txns if t["amount"] < 0))
            wow_change = week_total - last_week_total if last_week_total > 0 else 0

            _wc1, _wc2 = st.columns(2)
            _wc1.metric("Total Spent", f"\\${week_total:,.0f}")
            _wc2.metric("vs Last Week", f"\\${abs(wow_change):,.0f}",
                      delta=f"{'↑' if wow_change > 0 else '↓'} \\${abs(wow_change):,.0f}",
                      delta_color="inverse" if wow_change > 0 else "normal")
            _wc3, _wc4 = st.columns(2)
            _wc3.metric("Transactions", len(week_txns))
            _wc4.metric("Avg per Txn", f"\\${week_total / max(len(week_txns), 1):,.0f}")

            # Spending breakdown
            st.markdown("#### Spending Breakdown")
            cat_totals = {}
            cat_counts = Counter()
            for t in week_txns:
                if t["amount"] < 0 and t["category"] in category_engine.get_active_categories(conn):
                    cat = t["category"]
                    cat_totals[cat] = cat_totals.get(cat, 0) + abs(t["amount"])
                    cat_counts[cat] += 1
            sorted_cats = sorted(cat_totals.items(), key=lambda x: -x[1])

            if sorted_cats:
                cats_list = [c[0] for c in sorted_cats[:10]]
                vals_list = [c[1] for c in sorted_cats[:10]]
                fig = go.Figure(go.Bar(
                    x=vals_list, y=cats_list, orientation="h",
                    marker_color=CATEGORY_PALETTE[:len(cats_list)],
                    text=[f"${v:,.0f}" for v in vals_list],
                    textposition="auto",
                    hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
                ))
                fig.update_layout(**CHART_LAYOUT, height=max(250, len(cats_list) * 35 + 80),
                                 showlegend=False, yaxis=dict(autorange="reversed"),
                                 xaxis=dict(title="Amount ($)", gridcolor="#f3f4f6", tickformat="$,.0f"))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            # Big charges
            big_charges = [t for t in week_txns if t["amount"] < -150]
            if big_charges:
                st.markdown("#### Notable Charges (> \\$150)")
                for t in sorted(big_charges, key=lambda x: x["amount"]):
                    st.markdown(f"- **\\${abs(t['amount']):,.0f}** — {t['description']} ({t['category']}) on {t['date']}")

            # Prophet forecasts
            st.divider()
            st.markdown("#### Next Month Preview")
            forecast_cats = sorted_cats[:8] if sorted_cats else []
            rising_forecasts = []
            falling_forecasts = []

            for cat_name, cat_spent in forecast_cats:
                try:
                    pf = _rpt_analytics.prophet_forecast_category(conn, cat_name, periods=1)
                    if not pf or not pf["forecast"]:
                        continue
                    predicted = pf["forecast"][0]["predicted"]
                    avg = pf.get("historical_avg", 0)
                    if avg <= 0:
                        continue
                    diff = predicted - avg
                    pct_diff = (diff / avg) * 100
                    entry = {"cat": cat_name, "predicted": predicted, "avg": avg,
                             "diff": diff, "pct": pct_diff, "month": pf["forecast"][0]["month"]}
                    if pct_diff > 10:
                        rising_forecasts.append(entry)
                    elif pct_diff < -10:
                        falling_forecasts.append(entry)
                except Exception:
                    pass

            if rising_forecasts:
                for f in sorted(rising_forecasts, key=lambda x: -x["diff"]):
                    st.error(
                        f"**{f['cat']}** — Forecast: **\\${f['predicted']:,.0f}** for {f['month']} "
                        f"(\\${f['diff']:+,.0f} vs avg \\${f['avg']:,.0f}). "
                        f"**Cut back now** to prevent this."
                    )
            if falling_forecasts:
                for f in sorted(falling_forecasts, key=lambda x: x["diff"]):
                    st.success(
                        f"**{f['cat']}** — Trending down to **\\${f['predicted']:,.0f}** "
                        f"(saving \\${abs(f['diff']):,.0f}/mo vs avg). Keep it up!"
                    )
            if not rising_forecasts and not falling_forecasts:
                st.info("All categories forecast within normal range.")

            # Savings progress
            st.divider()
            st.markdown("#### Savings Target Progress")
            c1, c2, c3 = st.columns(3)
            c1.metric("Monthly Target", f"${_rpt_savings_target:,}/mo")
            c2.metric("This Week", f"${week_total:,.0f}")
            c3.metric("Transactions", len(week_txns))

            # Claude's analysis
            if _rpt_advisor:
                st.divider()
                st.markdown("#### Claude's Take")
                if st.button("Get Claude's Analysis", type="primary"):
                    with st.spinner("Claude is analyzing your week..."):
                        try:
                            stat_ctx = None
                            try:
                                stat_ctx = _rpt_analytics.build_statistical_context(conn)
                            except Exception:
                                pass

                            report_result = _rpt_advisor.generate_weekly_report(
                                week_transactions=[dict(t) for t in week_txns[:30]],
                                monthly_context=data["mtd_summary"],
                                objective_progress=data["objective_progress"],
                                alerts=data["alerts"],
                                statistical_context=stat_ctx,
                            )

                            keep = report_result.get("keep", "")
                            stop = report_result.get("stop", "")
                            start = report_result.get("start", "")
                            actions = report_result.get("action_items", [])
                            concern = report_result.get("top_concern", "")
                            win = report_result.get("top_win", "")

                            if keep or stop or start:
                                k_col, s_col, st_col = st.columns(3)
                                with k_col:
                                    st.success(f"**KEEP**\n\n{keep}")
                                with s_col:
                                    st.error(f"**STOP**\n\n{stop}")
                                with st_col:
                                    st.info(f"**START**\n\n{start}")

                            if actions:
                                st.markdown("**This Week's Action Items:**")
                                for i, action in enumerate(actions[:3], 1):
                                    st.markdown(f"{i}. {action}")

                            if concern:
                                st.warning(f"**Top concern:** {concern}")
                            if win:
                                st.success(f"**Top win:** {win}")

                            plain = report_result.get("plain_text", "")
                            if plain:
                                database.save_weekly_report(
                                    conn, date.today().isoformat(),
                                    report_result.get("subject", "Weekly Report"),
                                    report_result.get("html_body", ""), plain,
                                )
                        except Exception as e:
                            st.error(f"Claude analysis failed: {e}")

            # Send to Telegram
            st.divider()
            bot_token = database.get_setting(conn, "telegram_bot_token")
            chat_id = database.get_setting(conn, "telegram_chat_id")
            if bot_token and chat_id:
                if st.button("Send Report to Telegram"):
                    with st.spinner("Generating report..."):
                        try:
                            from telegram_bot import TelegramReporter, format_weekly_report_html
                            import chart_generator

                            data["preventive_actions"] = []
                            _active = category_engine.get_active_categories(conn)
                            for cat_name in _active[:10]:
                                try:
                                    pf = _rpt_analytics.prophet_forecast_category(conn, cat_name, periods=1)
                                    if pf and pf["forecast"]:
                                        predicted = pf["forecast"][0]["predicted"]
                                        avg = pf.get("historical_avg", 0)
                                        if avg > 0:
                                            diff = predicted - avg
                                            data["preventive_actions"].append({
                                                "category": cat_name, "predicted": predicted,
                                                "avg": avg, "diff": diff,
                                                "forecast": f"${predicted:,.0f} (avg ${avg:,.0f})",
                                            })
                                except Exception:
                                    pass

                            _current_month = date.today().strftime("%Y-%m")
                            _mb = database.get_monthly_category_breakdown(conn, _current_month)
                            _active_for_report = category_engine.get_active_categories(conn)
                            _mb = [c for c in _mb if c["category"] in _active_for_report]

                            red_cards = []
                            for cd in _mb:
                                cat = cd["category"]
                                spent = abs(cd["total"])
                                t = analytics_cache.get_cached_trend(conn, cat)
                                if t:
                                    avg = float(t.get("mean", 0))
                                    if avg > 0 and spent > avg * 1.15:
                                        red_cards.append({
                                            "category": cat, "spent": spent, "avg": avg,
                                            "pct_above": (spent / avg - 1) * 100,
                                        })
                            red_cards.sort(key=lambda x: -x["pct_above"])

                            charts = []
                            for rc in red_cards[:3]:
                                try:
                                    cat = rc["category"]
                                    history = database.get_category_monthly_history(conn, cat, months=12)
                                    if len(history) >= 3:
                                        import plotly.graph_objects as _go
                                        hist_months = [h["month"] for h in reversed(history)]
                                        hist_vals = [abs(h["total"]) for h in reversed(history)]
                                        fig_rc = _go.Figure()
                                        fig_rc.add_trace(_go.Scatter(
                                            x=hist_months, y=hist_vals, mode="lines+markers",
                                            line=dict(color="#ef4444", width=3),
                                            marker=dict(size=8, color="#ef4444"),
                                        ))
                                        avg = rc["avg"]
                                        fig_rc.add_hline(y=avg, line_dash="dot", line_color="#94a3b8",
                                                        annotation_text=f"avg ${avg:,.0f}")
                                        fig_rc.update_layout(
                                            title=f"{cat}: ${rc['spent']:,.0f} (+{rc['pct_above']:.0f}% above avg)",
                                            title_font=dict(size=16, color="#ef4444"),
                                            margin=dict(t=50, b=30, l=50, r=30),
                                            height=300, width=600,
                                            yaxis=dict(tickformat="$,.0f"),
                                            paper_bgcolor="white", plot_bgcolor="white",
                                            font=dict(size=12),
                                        )
                                        import plotly.io as _pio
                                        png = _pio.to_image(fig_rc, format="png", width=600, height=300, scale=2)
                                        charts.append((png, f"{cat}: ${rc['spent']:,.0f}"))
                                except Exception:
                                    pass

                            _cached = analytics_cache.get_cached(conn)
                            _tg_report = None
                            try:
                                _tg_advisor = get_advisor()
                                if _tg_advisor:
                                    _tg_report = _tg_advisor.generate_weekly_report(
                                        week_transactions=data.get("week_transactions", []),
                                        monthly_context=data.get("mtd_summary"),
                                        objective_progress=data.get("objective_progress", {}),
                                        alerts=data.get("alerts", []),
                                    )
                            except Exception:
                                pass
                            summary = (_tg_report.get("plain_text", "") if _tg_report else "") or format_weekly_report_html(data, cached_analytics=_cached, red_cards=red_cards)
                            telegram = TelegramReporter(bot_token, chat_id)
                            telegram.send_weekly_report(summary, charts)
                            maggie_chat = database.get_setting(conn, "telegram_chat_id_maggie")
                            if maggie_chat and maggie_chat != chat_id:
                                TelegramReporter(bot_token, maggie_chat).send_weekly_report(summary, charts)
                            st.success("Sent to Kero & Maggie!")
                        except Exception as e:
                            st.error(f"Failed: {e}")

        past = database.get_weekly_reports(conn)
        if past:
            st.divider()
            st.markdown("#### Past Reports")
            for r in past:
                with st.expander(f"{r['report_date']} — {r['subject'] or 'Weekly Report'}"):
                    st.markdown(r["plain_text"] or "")

    # Telegram setup
    st.markdown("##### Telegram Bot Setup")
    st.markdown("""
    1. Open Telegram, search **@BotFather**, send `/newbot`
    2. Copy the **bot token**
    3. Start a chat with your bot, send any message
    4. Get your chat ID: `https://api.telegram.org/bot<TOKEN>/getUpdates`
    """)

    token = st.text_input("Bot Token", value=database.get_setting(conn, "telegram_bot_token"), type="password")
    chat = st.text_input("Chat ID", value=database.get_setting(conn, "telegram_chat_id"))

    c1, c2 = st.columns(2)
    if c1.button("Save", key="save_telegram"):
        if token and chat:
            database.set_setting(conn, "telegram_bot_token", token)
            database.set_setting(conn, "telegram_chat_id", chat)
            st.success("Saved!")
    if c2.button("Test Connection", key="test_telegram"):
        if token:
            try:
                from telegram_bot import TelegramReporter
                bot = TelegramReporter(token, chat or "test")
                info = bot.test_connection()
                if info.get("ok"):
                    st.success(f"Connected: @{info['result']['username']}")
                    if chat:
                        bot.send_message("Connected! Your Budget Tracker is ready.")
            except Exception as e:
                st.error(f"Failed: {e}")

    st.divider()

    # ── 8. Monarch Money ──────────────────────────────────────────────
    st.markdown("#### Monarch Money")
    import monarch_sync

    _mm_enabled = database.get_setting(conn, "monarch_enabled", "0") == "1"
    _mm_stats = monarch_sync.get_sync_stats(conn)

    if _mm_enabled and _mm_stats["last_sync"]:
        _sync_ago = ""
        try:
            _sync_dt = datetime.fromisoformat(_mm_stats["last_sync"])
            _sync_delta = datetime.now() - _sync_dt
            if _sync_delta.days > 0:
                _sync_ago = f"{_sync_delta.days}d ago"
            elif _sync_delta.seconds >= 3600:
                _sync_ago = f"{_sync_delta.seconds // 3600}h ago"
            else:
                _sync_ago = f"{_sync_delta.seconds // 60}m ago"
        except (ValueError, TypeError):
            _sync_ago = "unknown"
        st.success(f"Connected — {_mm_stats['transaction_count']:,} transactions synced (last: {_sync_ago})")
    elif _mm_enabled:
        st.info("Connected — no sync yet. Click **Sync Now** below.")
    else:
        st.info("Connect your Monarch Money account to auto-import transactions.")

    with st.expander("Credentials", expanded=not _mm_enabled):
        _mm_email = database.get_setting(conn, "monarch_email", "")
        _mm_password = database.get_setting(conn, "monarch_password", "")
        _new_email = st.text_input("Monarch Email", value=_mm_email, key="mm_email")
        _new_password = st.text_input("Monarch Password", type="password",
                                       value=_mm_password if _mm_password else "",
                                       key="mm_password")
        _mm_device_uuid = database.get_setting(conn, "monarch_device_uuid", "")
        _new_device_uuid = st.text_input(
            "Device UUID", value=_mm_device_uuid, key="mm_device_uuid",
            help="Required: Open Monarch in browser → DevTools Console → run: localStorage.getItem('monarchDeviceUUID')",
        )
        if _new_device_uuid != _mm_device_uuid and _new_device_uuid:
            database.set_setting(conn, "monarch_device_uuid", _new_device_uuid)

        _mm_c1, _mm_c2 = st.columns(2)
        if _mm_c1.button("Connect to Monarch", key="mm_connect"):
            if _new_email and _new_password:
                database.set_setting(conn, "monarch_email", _new_email)
                database.set_setting(conn, "monarch_password", _new_password)
                with st.spinner("Authenticating..."):
                    try:
                        _mm_client = monarch_sync.get_client(conn)
                        database.set_setting(conn, "monarch_enabled", "1")
                        st.success("Connected to Monarch Money!")
                        _mm_accounts = monarch_sync.fetch_accounts(_mm_client)
                        _suggested = monarch_sync.auto_suggest_mapping(_mm_accounts)
                        if _suggested:
                            monarch_sync.set_account_mapping(conn, _suggested)
                        _mm_cats = monarch_sync.fetch_categories(_mm_client)
                        _default_cat_map = monarch_sync.build_default_category_mapping(_mm_cats)
                        monarch_sync.set_category_mapping(conn, _default_cat_map)
                        st.rerun()
                    except monarch_sync.MonarchEmailOTPRequired:
                        st.session_state.mm_email_otp_needed = True
                        st.rerun()
                    except monarch_sync.MonarchMFARequired:
                        st.session_state.mm_mfa_needed = True
                        st.rerun()
                    except monarch_sync.MonarchAuthFailed as e:
                        st.error(f"Authentication failed: {e}")
                    except Exception as e:
                        st.error(f"Connection error: {e}")
            else:
                st.warning("Enter both email and password.")

        if _mm_c2.button("Disconnect", key="mm_disconnect", disabled=not _mm_enabled):
            monarch_sync.disconnect()
            database.set_setting(conn, "monarch_enabled", "0")
            database.set_setting(conn, "monarch_email", "")
            database.set_setting(conn, "monarch_password", "")
            database.set_setting(conn, "monarch_last_sync", "")
            database.set_setting(conn, "monarch_account_map", "{}")
            database.set_setting(conn, "monarch_category_map", "{}")
            st.session_state.monarch_synced = False
            st.success("Disconnected from Monarch Money.")
            st.rerun()

        if st.session_state.get("mm_email_otp_needed", False):
            st.warning("Monarch sent a verification code to your email.")
            _otp_code = st.text_input("Email Verification Code", key="mm_email_otp_code", max_chars=6)
            if st.button("Verify Code", key="mm_email_otp_verify"):
                if _otp_code:
                    try:
                        _mm_client = monarch_sync.complete_email_otp(conn, _otp_code)
                        database.set_setting(conn, "monarch_enabled", "1")
                        st.session_state.mm_email_otp_needed = False
                        _mm_accounts = monarch_sync.fetch_accounts(_mm_client)
                        _suggested = monarch_sync.auto_suggest_mapping(_mm_accounts)
                        if _suggested:
                            monarch_sync.set_account_mapping(conn, _suggested)
                        _mm_cats = monarch_sync.fetch_categories(_mm_client)
                        _default_cat_map = monarch_sync.build_default_category_mapping(_mm_cats)
                        monarch_sync.set_category_mapping(conn, _default_cat_map)
                        st.success("Verified! Connected to Monarch Money.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Verification failed: {e}")

        if st.session_state.get("mm_mfa_needed", False):
            st.warning("Monarch Money requires a multi-factor authentication code.")
            _mfa_code = st.text_input("Enter MFA Code", key="mm_mfa_code", max_chars=6)
            if st.button("Verify MFA", key="mm_mfa_verify"):
                if _mfa_code:
                    try:
                        _mm_client = monarch_sync.complete_mfa(conn, _mfa_code)
                        database.set_setting(conn, "monarch_enabled", "1")
                        st.session_state.mm_mfa_needed = False
                        _mm_accounts = monarch_sync.fetch_accounts(_mm_client)
                        _suggested = monarch_sync.auto_suggest_mapping(_mm_accounts)
                        if _suggested:
                            monarch_sync.set_account_mapping(conn, _suggested)
                        _mm_cats = monarch_sync.fetch_categories(_mm_client)
                        _default_cat_map = monarch_sync.build_default_category_mapping(_mm_cats)
                        monarch_sync.set_category_mapping(conn, _default_cat_map)
                        st.success("MFA verified! Connected to Monarch Money.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"MFA verification failed: {e}")

    if _mm_enabled:
        with st.expander("Account Mapping"):
            _acct_map = monarch_sync.get_account_mapping(conn)
            _vw_options = ["-- Skip --"] + list(config.ACCOUNTS.keys())
            _vw_labels = {"-- Skip --": "-- Skip --"}
            for k, v in config.ACCOUNTS.items():
                _vw_labels[k] = f"{v['label']} ({v['owner']})"

            try:
                _mm_client = monarch_sync.get_client(conn)
                _mm_accounts = monarch_sync.fetch_accounts(_mm_client)
            except Exception:
                _mm_accounts = []
                st.warning("Could not fetch Monarch accounts.")

            if _mm_accounts:
                _new_map = {}
                for macct in _mm_accounts:
                    _current = _acct_map.get(macct["id"], "-- Skip --")
                    _idx = _vw_options.index(_current) if _current in _vw_options else 0
                    _label = f"{macct['institution']} — {macct['name']}"
                    if macct["mask"]:
                        _label += f" (...{macct['mask']})"
                    _label += f"  |  bal: ${macct['balance']:,.0f}"
                    _selected = st.selectbox(
                        _label, _vw_options, index=_idx,
                        format_func=lambda x: _vw_labels.get(x, x),
                        key=f"mm_acct_{macct['id']}",
                    )
                    if _selected != "-- Skip --":
                        _new_map[macct["id"]] = _selected
                if st.button("Save Account Mapping", key="mm_save_acct_map"):
                    monarch_sync.set_account_mapping(conn, _new_map)
                    st.success(f"Mapped {len(_new_map)} accounts.")

        with st.expander("Category Mapping"):
            _cat_map = monarch_sync.get_category_mapping(conn)
            _vw_cats = config.CATEGORIES
            if _cat_map:
                _new_cat_map = {}
                for mcat, vcat in sorted(_cat_map.items()):
                    _idx = _vw_cats.index(vcat) if vcat in _vw_cats else _vw_cats.index("Other")
                    _selected = st.selectbox(mcat, _vw_cats, index=_idx, key=f"mm_cat_{mcat}")
                    _new_cat_map[mcat] = _selected
                if st.button("Save Category Mapping", key="mm_save_cat_map"):
                    monarch_sync.set_category_mapping(conn, _new_cat_map)
                    st.success("Category mapping saved.")
            else:
                st.info("Connect and sync to see Monarch categories.")

        _sync_c1, _sync_c2 = st.columns(2)
        if _sync_c1.button("Sync Now", key="mm_sync_now"):
            with st.spinner("Syncing transactions from Monarch..."):
                try:
                    _result = monarch_sync.sync_transactions(conn)
                    if _result["new"] > 0:
                        st.success(f"Imported {_result['new']} new transactions!")
                        st.session_state.monarch_synced = True
                    elif _result["errors"]:
                        st.warning(f"Sync issue: {_result['errors'][0]}")
                    else:
                        st.info(f"Already up to date ({_result['skipped']} duplicates skipped)")
                except Exception as e:
                    st.error(f"Sync failed: {e}")

        if _sync_c2.button("Full Re-sync", key="mm_full_sync"):
            with st.spinner("Full re-sync from Monarch..."):
                try:
                    _result = monarch_sync.sync_transactions(conn, force_full=True)
                    if _result["new"] > 0:
                        st.success(f"Imported {_result['new']} new transactions!")
                    else:
                        st.info(f"No new transactions ({_result['skipped']} duplicates skipped)")
                except Exception as e:
                    st.error(f"Full sync failed: {e}")

    st.divider()

    # ── 9. Database ───────────────────────────────────────────────────
    st.markdown("#### Database")
    txn_count = database.get_transaction_count(conn)
    stmts = database.get_all_statements(conn)
    from shared.state import DB_PATH
    st.write(f"**{txn_count:,}** transactions | **{len(stmts)}** statements | `{DB_PATH}`")

    if stmts:
        stmt_data = [{"Account": config.ACCOUNTS.get(s["account_id"], {}).get("label", s["account_id"]),
                      "Period": f"{s['period_start']} — {s['period_end']}",
                      "Txns": s["transaction_count"], "File": s["filename"]} for s in stmts]
        st.dataframe(pd.DataFrame(stmt_data), use_container_width=True, hide_index=True)

    st.divider()

    # ── 10. API Usage ─────────────────────────────────────────────────
    advisor = get_advisor()
    if advisor:
        st.markdown("#### API Usage (this session)")
        usage = advisor.get_usage()
        c1, c2, c3 = st.columns(3)
        c1.metric("Input Tokens", f"{usage['total_input_tokens']:,}")
        c2.metric("Output Tokens", f"{usage['total_output_tokens']:,}")
        c3.metric("Cost", f"${usage['estimated_cost']:.4f}")

    conn.close()
