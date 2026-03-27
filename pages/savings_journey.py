"""Savings Journey — Forward-looking narrative.
Trajectory, scenarios, goals, AI advisor — all in one scrollable story.
"""

from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

import analytics
import analytics_cache
import config
import database
import models
from shared.charts import CHART_LAYOUT, PALETTE, make_monthly_net_chart, make_cumulative_chart
from shared.state import get_conn, get_advisor, escape_dollars


def savings_journey_page():
    st.markdown("## Savings Journey")
    conn = get_conn()

    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))
    savings_status = models.compute_savings_status(conn, savings_target)

    # ── Section 1: Where You Are ──────────────────────────────────────
    st.markdown("### Where You Are")
    st.caption("Your actual savings performance based on recent transaction data.")

    _r1c1, _r1c2 = st.columns(2)
    _r1c1.metric("Savings Target", f"\\${savings_target:,}/mo")
    _r1c2.metric("Current Avg Net", f"\\${savings_status['actual_avg_net']:,.0f}/mo",
              delta="Hitting your target" if savings_status["on_track"] else f"\\${savings_status['current_gap']:,.0f} short",
              delta_color="normal" if savings_status["on_track"] else "inverse")
    _r2c1, _r2c2 = st.columns(2)
    _r2c1.metric("Projected Avg Net", f"\\${savings_status['projected_avg_net']:,.0f}/mo")
    _r2c2.metric("Months Analyzed", savings_status["months_analyzed"])

    df = models.project_cash_flow()
    st.plotly_chart(make_monthly_net_chart(df, height=300), use_container_width=True, config={"displayModeBar": False})
    st.plotly_chart(make_cumulative_chart(df, height=370), use_container_width=True, config={"displayModeBar": False})

    st.divider()

    # ── Section 2: Where You're Going ─────────────────────────────────
    st.markdown("### Where You're Going")
    st.caption("Prophet ML forecasts based on your spending history.")

    forecast_conn = get_conn()
    try:
        prophet_result = analytics.prophet_forecast_total_spending(forecast_conn, periods=6)
        if prophet_result:
            hist_rows = forecast_conn.execute("""
                SELECT strftime('%Y-%m', date) as month,
                       SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) as spending
                FROM transactions GROUP BY month ORDER BY month
            """).fetchall()
            hist_months = [r["month"] for r in hist_rows]
            hist_vals = [abs(r["spending"]) for r in hist_rows if r["spending"]]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hist_months, y=hist_vals, mode="lines+markers",
                name="Actual", line=dict(color=PALETTE["blue"], width=2),
                marker=dict(size=6),
                hovertemplate="<b>%{x}</b><br>Actual: $%{y:,.0f}<extra></extra>",
            ))

            last_hist_month = hist_months[-1] if hist_months else None
            last_hist_val = hist_vals[-1] if hist_vals else 0

            fc_months = ([last_hist_month] if last_hist_month else []) + [f["month"] for f in prophet_result["forecast"]]
            fc_vals = ([last_hist_val] if last_hist_month else []) + [f["predicted"] for f in prophet_result["forecast"]]
            fc_lower = ([last_hist_val] if last_hist_month else []) + [f["lower"] for f in prophet_result["forecast"]]
            fc_upper = ([last_hist_val] if last_hist_month else []) + [f["upper"] for f in prophet_result["forecast"]]

            fig.add_trace(go.Scatter(
                x=fc_months + fc_months[::-1],
                y=fc_upper + fc_lower[::-1],
                fill="toself", fillcolor="rgba(139,92,246,0.12)",
                line=dict(width=0), showlegend=True, name="80% confidence",
                hoverinfo="skip",
            ))
            fig.add_trace(go.Scatter(
                x=fc_months, y=fc_vals, mode="lines+markers",
                name="Prophet Forecast", line=dict(color=PALETTE["purple"], width=2.5, dash="dash"),
                marker=dict(size=7, symbol="diamond"),
                hovertemplate="<b>%{x}</b><br>Forecast: $%{y:,.0f}<extra></extra>",
            ))

            avg = prophet_result["historical_avg"]
            fig.add_hline(y=avg, line_dash="dot", line_color=PALETTE["gray"],
                         annotation_text=f"Historical avg: ${avg:,.0f}", annotation_font_size=9)

            fig.update_layout(**CHART_LAYOUT, height=360,
                             legend=dict(orientation="h", yanchor="bottom", y=1.02, font_size=10),
                             yaxis=dict(title="Monthly Spending ($)", gridcolor="#f3f4f6", tickformat="$,.0f"),
                             xaxis=dict(gridcolor="#f3f4f6"))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            # Confidence level badge
            mape = prophet_result['mape']
            if mape < 10:
                confidence = "HIGH"
                conf_color = "#22c55e"
            elif mape < 20:
                confidence = "MEDIUM"
                conf_color = "#f59e0b"
            else:
                confidence = "LOW"
                conf_color = "#ef4444"

            c1, c2, c3 = st.columns(3)
            c1.metric("Model Accuracy (MAPE)", f"{mape:.1f}%")
            c2.metric("Data Points", prophet_result["data_points"])
            next_fc = prophet_result["forecast"][0]
            c3.metric(f"Next Month ({next_fc['month']})",
                      f"${next_fc['predicted']:,.0f}",
                      delta=f"${next_fc['predicted'] - avg:+,.0f} vs avg")

            st.markdown(
                f'<div style="display:inline-block;background:{conf_color};color:white;'
                f'padding:4px 12px;border-radius:20px;font-size:0.8rem;font-weight:700;">'
                f'{confidence} CONFIDENCE</div>'
                f' <span style="color:#6b7280;font-size:0.82rem;">Based on {prophet_result["data_points"]} months of data, {mape:.1f}% error rate</span>',
                unsafe_allow_html=True,
            )
        else:
            st.info("Need at least 4 months of data for Prophet forecasting. Upload more statements.")
    except Exception as e:
        st.caption(f"Prophet forecast unavailable: {e}")
    forecast_conn.close()

    st.divider()

    # ── Section 3: Your Goals (BUG FIX #1: actual progress) ──────────
    st.markdown("### Your Goals")
    st.caption("Track progress toward your financial objectives.")

    goals_conn = get_conn()
    objectives = database.get_active_objectives(goals_conn)

    if objectives:
        for obj in objectives:
            target = obj["target"] or 0
            if target > 0:
                # BUG FIX #1: Pull actual current_amount instead of hardcoded 0
                obj_history = database.get_objective_history(goals_conn, obj["objective_id"])
                if obj_history:
                    current = obj_history[-1]["current_amount"]
                else:
                    # Fall back to cumulative net from savings status
                    current = max(savings_status["actual_avg_net"] * savings_status["months_analyzed"], 0)

                pct = min(1.0, max(0.0, current / target)) if target > 0 else 0
                st.progress(pct, text=f"**{obj['label']}**: \\${current:,.0f} / \\${target:,.0f} ({pct*100:.0f}%)")

                # ETA calculation
                monthly_net = savings_status["actual_avg_net"]
                if monthly_net > 0 and current < target:
                    months_to_goal = (target - current) / monthly_net
                    eta = date.today() + timedelta(days=int(months_to_goal * 30))
                    st.caption(f"At your current pace, you'll reach this goal by **{eta.strftime('%B %Y')}**")
                elif current >= target:
                    st.caption("🎉 **Goal reached!**")

                # Manual progress update
                with st.expander("Update Progress", expanded=False):
                    new_amount = st.number_input(
                        f"Current amount for {obj['label']}",
                        value=int(current), step=100,
                        key=f"goal_update_{obj['objective_id']}"
                    )
                    if st.button("Save", key=f"goal_save_{obj['objective_id']}"):
                        database.snapshot_objective(goals_conn, obj["objective_id"], new_amount, date.today().isoformat())
                        st.success("Progress updated!")
                        st.rerun()
            else:
                st.write(f"**{obj['label']}**: {obj['description'] or ''}")
    else:
        st.info("No goals set yet. Add one below.")

    st.markdown("##### Add Goal")
    with st.form("new_goal"):
        label = st.text_input("Goal name", placeholder="e.g., Emergency fund $10k")
        target = st.number_input("Target ($)", min_value=0, value=0, step=500)
        deadline = st.date_input("Deadline", value=None)
        if st.form_submit_button("Create", type="primary") and label:
            oid = label.lower().replace(" ", "_")[:30]
            database.create_objective(goals_conn, oid, label, target=target if target > 0 else None,
                                     deadline=deadline.isoformat() if deadline else None)
            st.rerun()
    goals_conn.close()

    st.divider()

    # ── Section 4: What-If (BUG FIX #2: dynamic sliders) ─────────────
    st.markdown("### What-If Scenarios")
    st.caption("Adjust the sliders to see how spending cuts change your trajectory and goal timelines.")

    scenario_df = models.project_cash_flow()

    # BUG FIX #2: Dynamic sliders from actual top discretionary categories
    _fixed_cats_scenario = {"Housing & Utilities", "Debt Payments", "Giving & Church",
                            "Family Support", "Phone & Internet", "Car Insurance",
                            "Transportation", "Childcare & Education"}

    # Get average monthly spend per category from recent months
    _recent_months = conn.execute("""
        SELECT category, AVG(monthly_total) as avg_spend FROM (
            SELECT category, strftime('%Y-%m', date) as month, ABS(SUM(amount)) as monthly_total
            FROM transactions WHERE amount < 0
            GROUP BY category, month
        )
        GROUP BY category
        ORDER BY avg_spend DESC
    """).fetchall()

    _disc_cats = [r for r in _recent_months
                  if r["category"] not in _fixed_cats_scenario
                  and r["category"] not in getattr(config, 'EXCLUDED_CATEGORIES', set())
                  and r["category"] not in {"Transfers & Payments", "Credit Card Payments"}]
    _top5 = _disc_cats[:5]

    adjustments = {}
    total_cut = 0
    if _top5:
        c1, c2 = st.columns(2)
        for i, cat_row in enumerate(_top5):
            col = c1 if i < 3 else c2
            cat_name = cat_row["category"]
            avg_spend = cat_row["avg_spend"] or 0
            max_cut = max(int(avg_spend * 0.8), 10)
            default_cut = min(int(avg_spend * 0.3), max_cut)
            with col:
                cut = st.slider(f"{cat_name} cut $/mo", 0, max_cut, default_cut, 10,
                                key=f"scenario_{cat_name}")
                adjustments[cat_name] = -cut
                total_cut += cut
    else:
        st.info("Upload more data to see scenario sliders.")

    if total_cut > 0:
        scenario_result = models.scenario_model(scenario_df, adjustments)

        new_net = savings_status["projected_avg_net"] + total_cut
        meets_target = new_net >= savings_target

        _si1, _si2 = st.columns(2)
        _si1.metric("Monthly Cuts", f"\\${total_cut:,}/mo")
        _si2.metric("New Monthly Net", f"\\${new_net:,.0f}/mo",
                  delta=f"+\\${total_cut:,} vs current")
        _si3, _si4 = st.columns(2)
        _si3.metric("Target Status", "Met" if meets_target else f"\\${savings_target - new_net:,.0f} short",
                  delta="Hitting your target" if meets_target else "Needs more cuts",
                  delta_color="normal" if meets_target else "inverse")
        annual_impact = total_cut * 12
        _si4.metric("Annual Impact", f"\\${annual_impact:,}")

        # Link to goal ETAs
        objectives = database.get_active_objectives(conn)
        for obj in objectives:
            target_val = obj["target"] or 0
            if target_val > 0 and new_net > 0:
                obj_history = database.get_objective_history(conn, obj["objective_id"])
                current_val = obj_history[-1]["current_amount"] if obj_history else 0
                if current_val < target_val:
                    months_with_cuts = (target_val - current_val) / new_net
                    months_without = (target_val - current_val) / max(savings_status["projected_avg_net"], 1) if savings_status["projected_avg_net"] > 0 else float('inf')
                    eta_with = date.today() + timedelta(days=int(months_with_cuts * 30))
                    saved_months = int(months_without - months_with_cuts) if months_without != float('inf') else 0
                    if saved_months > 0:
                        st.success(f"**{obj['label']}**: reach target by **{eta_with.strftime('%B %Y')}** — **{saved_months} months sooner**")
                    else:
                        st.info(f"**{obj['label']}**: reach target by **{eta_with.strftime('%B %Y')}**")

        # Comparison chart
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=scenario_df["month"], y=scenario_df["cumulative"], mode="lines", name="Current Path",
            line=dict(color=PALETTE["gray"], dash="dash", width=2),
            hovertemplate="Current: $%{y:,.0f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=scenario_result["month"], y=scenario_result["cumulative"], mode="lines", name="With Cuts",
            line=dict(color=PALETTE["green"], width=3),
            fill="tonexty", fillcolor="rgba(34,197,94,0.06)",
            hovertemplate="Scenario: $%{y:,.0f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_color=PALETTE["gray_light"], line_width=1)
        fig.update_layout(**CHART_LAYOUT, height=420,
                         legend=dict(orientation="h", yanchor="bottom", y=1.02),
                         yaxis=dict(title="Cumulative Savings ($)", gridcolor="#f3f4f6", tickformat="$,.0f"),
                         xaxis=dict(gridcolor="#f3f4f6", dtick="M6"))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    conn.close()
