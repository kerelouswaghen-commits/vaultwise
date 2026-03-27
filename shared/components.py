"""Reusable UI components: gauge, category cards, gap closer."""

import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analytics_cache
import database
from shared.charts import CHART_LAYOUT, PALETTE, SEVERITY_MAP, DIRECTION_ICONS, DEFAULT_TREND_DICT
from shared.state import escape_dollars, get_conn


def render_savings_gauge(month_display, saved, gauge_color, status_icon, status_text,
                         total_outflow, budget_limit, savings_target, effective_fixed,
                         txn_discretionary, spent_pct, compact=False):
    """Render the savings goal gauge. Use compact=True for the sidebar widget."""
    D = "$"
    if compact:
        # Sidebar mini widget
        if saved >= savings_target:
            bar_color = "#22c55e"
            label = "ON TRACK"
        elif saved > 0:
            bar_color = "#f59e0b"
            label = "AT RISK"
        else:
            bar_color = "#ef4444"
            label = "OVER BUDGET"
        pct = min(saved / savings_target * 100, 100) if savings_target > 0 else 0
        html = (
            f'<div style="background:#f8f9fb;border:1px solid #e2e6ed;border-radius:10px;padding:10px 12px;margin:4px 0;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
            f'<span style="font-size:0.78rem;font-weight:600;color:#374151;">{month_display}</span>'
            f'<span style="font-size:0.7rem;font-weight:700;color:{bar_color};">{label}</span>'
            f'</div>'
            f'<div style="font-weight:700;font-size:0.95rem;color:{bar_color};margin-bottom:4px;">{D}{saved:,.0f} saved</div>'
            f'<div style="height:6px;border-radius:3px;background:#e5e7eb;overflow:hidden;">'
            f'<div style="height:100%;width:{max(pct, 0):.0f}%;background:{bar_color};border-radius:3px;"></div>'
            f'</div>'
            f'<div style="font-size:0.7rem;color:#9ca3af;margin-top:2px;">Target: {D}{savings_target:,}/mo</div>'
            f'</div>'
        )
        st.markdown(html, unsafe_allow_html=True)
        return

    # Full dashboard gauge
    html = (
        f'<div style="background:#f8f9fb;border:1px solid #e2e6ed;border-radius:14px;padding:14px 16px;margin-bottom:16px;">'
        f'<div class="gauge-header" style="margin-bottom:8px;">'
        f'<span style="font-weight:700;font-size:clamp(0.85rem,3vw,1rem);">🎯 {month_display} Savings Goal</span>'
        f'<span style="font-weight:700;font-size:clamp(0.9rem,3.5vw,1.1rem);color:{gauge_color};">{status_icon} {D}{saved:,.0f} saved</span>'
        f'</div>'
        f'<div style="height:12px;border-radius:6px;background:#e5e7eb;overflow:hidden;margin:8px 0;">'
        f'<div style="height:100%;width:{min(spent_pct, 100):.0f}%;background:{gauge_color};border-radius:6px;transition:width 0.3s;"></div>'
        f'</div>'
        f'<div class="gauge-footer gauge-detail" style="color:#6b7280;margin-top:4px;">'
        f'<span>{D}{total_outflow:,.0f} of {D}{budget_limit:,.0f} budget</span>'
        f'<span>Target: {D}{savings_target:,}/mo</span>'
        f'</div>'
        f'<div class="gauge-detail" style="color:#9ca3af;margin-top:2px;">Fixed: {D}{effective_fixed:,.0f} · Disc: {D}{txn_discretionary:,.0f}</div>'
        f'<div style="font-size:clamp(0.75rem,2.5vw,0.85rem);color:{gauge_color};font-weight:600;margin-top:6px;">{status_text}</div>'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_category_card(cat_data, trend_d, conn, claude_actions, selected_month, expanded_default=False):
    """Render a single category card with trend chart, merchants, and actions."""
    cat = cat_data["category"]
    spent = abs(cat_data["total"])
    count = cat_data["txn_count"]
    t_direction = trend_d.get("direction", "stable")
    t_current = spent
    t_mean = float(trend_d.get("mean", 0))
    t_std = float(trend_d.get("std", 0))
    t_slope = float(trend_d.get("slope_per_month", 0))
    t_pct = ((t_current / t_mean) - 1) * 100 if t_mean > 0 else 0
    t_action = trend_d.get("action", "")

    direction_icon = DIRECTION_ICONS.get(t_direction, "→")
    pct_str = f"+{t_pct:.0f}%" if t_pct > 0 else f"{t_pct:.0f}%"

    # Card class, icon, and bar color
    fill_pct = min(120, spent / t_mean * 100) if t_mean > 0 else 50
    if fill_pct > 115:
        card_class = "cat-card-critical"
        sev = SEVERITY_MAP["critical"]
        bar_color = PALETTE["red"]
    elif fill_pct > 100:
        card_class = "cat-card-warning"
        sev = SEVERITY_MAP["warning"]
        bar_color = PALETTE["amber"]
    else:
        card_class = "cat-card-good"
        sev = {"icon": "🟢", "color": PALETTE["green"], "label": "On Track"}
        bar_color = PALETTE["green"]

    # Prophet forecast inline
    prophet_line = ""
    cached_pf = analytics_cache.get_cached_prophet(conn, cat)
    if cached_pf and cached_pf.get("forecast"):
        next_mo = cached_pf["forecast"][0]
        fc_icon = "↑" if next_mo["predicted"] > t_current else "↓"
        prophet_line = f'<div style="font-size:0.78rem; color:#7c3aed; margin-top:3px;">🔮 Forecast: <b>${next_mo["predicted"]:,.0f}</b> next month {fc_icon}</div>'

    card_html = (
        f'<div class="cat-card {card_class}">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
        f'<span style="font-weight:700;font-size:1rem;">{sev["icon"]} {cat}</span>'
        f'<span style="font-weight:700;font-size:1.1rem;color:{sev["color"]};">${spent:,.0f}</span>'
        f'</div>'
        f'<div class="budget-bar"><div class="budget-fill" style="width:{min(fill_pct, 100):.0f}%;background:{bar_color};"></div></div>'
        f'<div style="display:flex;justify-content:space-between;font-size:0.8rem;color:#6b7280;margin-top:2px;">'
        f'<span>{direction_icon} {pct_str} vs avg (${t_mean:,.0f})</span>'
        f'<span>{count} transactions</span>'
        f'</div>'
        f'{prophet_line}'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)

    # Expandable details — collapsed by default
    with st.expander("Trend, Forecast & Action Plan", expanded=expanded_default):
        history = database.get_category_monthly_history(conn, cat, months=12)

        if len(history) >= 2:
            hist_df = pd.DataFrame(list(reversed(history)))
            hist_df["total"] = hist_df["total"].abs()

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hist_df["month"], y=hist_df["total"], mode="lines+markers",
                name="Actual", line=dict(color=sev["color"], width=2.5),
                marker=dict(size=7, color=sev["color"]),
                hovertemplate="<b>%{x}</b><br>Actual: $%{y:,.0f}<extra></extra>",
            ))

            if cached_pf and cached_pf.get("forecast"):
                last_actual_month = hist_df["month"].iloc[-1]
                last_actual_val = hist_df["total"].iloc[-1]
                fc_months = [last_actual_month] + [f["month"] for f in cached_pf["forecast"]]
                fc_vals = [last_actual_val] + [f["predicted"] for f in cached_pf["forecast"]]
                fc_lower = [last_actual_val] + [f["lower"] for f in cached_pf["forecast"]]
                fc_upper = [last_actual_val] + [f["upper"] for f in cached_pf["forecast"]]

                fig.add_trace(go.Scatter(
                    x=fc_months + fc_months[::-1],
                    y=fc_upper + fc_lower[::-1],
                    fill="toself", fillcolor="rgba(139,92,246,0.12)",
                    line=dict(width=0), showlegend=True, name="80% CI",
                    hoverinfo="skip",
                ))
                fig.add_trace(go.Scatter(
                    x=fc_months, y=fc_vals, mode="lines+markers",
                    name="Prophet Forecast",
                    line=dict(color=PALETTE["purple"], width=2, dash="dash"),
                    marker=dict(size=7, symbol="diamond", color=PALETTE["purple"]),
                    hovertemplate="<b>%{x}</b><br>Forecast: $%{y:,.0f}<extra></extra>",
                ))

            avg = hist_df["total"].mean()
            fig.add_hline(y=avg, line_dash="dot", line_color=PALETTE["gray"],
                         annotation_text=f"avg ${avg:,.0f}", annotation_font_size=9)

            compact_layout = {**CHART_LAYOUT, "margin": dict(t=15, b=25, l=50, r=15)}
            fig.update_layout(**compact_layout, height=220,
                             legend=dict(orientation="h", yanchor="bottom", y=1.02, font_size=9),
                             xaxis=dict(showgrid=False),
                             yaxis=dict(gridcolor="#f3f4f6", tickformat="$,.0f"))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        col_info, col_action = st.columns([1, 1])

        with col_info:
            st.markdown(f"**Trend:** {t_direction.title()} at \\${abs(t_slope):,.0f}/mo")
            st.markdown(f"**This month:** \\${t_current:,.0f} | **Avg:** \\${t_mean:,.0f} ± \\${t_std:,.0f}")

            # Merchant impact
            _month_merchants = database.get_merchant_breakdown_for_month(conn, cat, selected_month, limit=6)
            if _month_merchants:
                m_entries = []
                for _fbm in _month_merchants:
                    name = _fbm["name"] or ""
                    name = re.sub(r'[A-Z0-9]{8,}', '', name).strip()
                    name = re.sub(r'\s+', ' ', name).strip().rstrip(',').strip()
                    if name and len(name) > 2:
                        name = name.title() if name.isupper() else name
                        m_entries.append((name[:25], abs(_fbm["total"])))
                if m_entries:
                    m_names = [e[0] for e in m_entries]
                    m_vals = [e[1] for e in m_entries]
                    _vibrant = ["#7c3aed", "#2563eb", "#059669", "#d97706", "#dc2626", "#ec4899"]
                    m_colors = [_vibrant[i % len(_vibrant)] for i in range(len(m_names))]
                    st.markdown("**Top merchants this month:**")
                    fig_m = go.Figure(go.Bar(
                        x=m_vals[::-1], y=m_names[::-1], orientation="h",
                        marker_color=m_colors[::-1],
                        text=[f"${v:,.0f}" for v in m_vals[::-1]],
                        textposition="auto", textfont=dict(color="white", size=11),
                        hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
                    ))
                    fig_m.update_layout(
                        margin=dict(t=5, b=5, l=5, r=5), height=max(80, len(m_names) * 30 + 20),
                        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                        yaxis=dict(autorange=True),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(size=11),
                    )
                    st.plotly_chart(fig_m, use_container_width=True, config={"displayModeBar": False})

            # Advanced analytics
            cached_adv = analytics_cache.get_cached_advanced(conn, cat)
            if cached_adv:
                mk = cached_adv.get("mann_kendall", {})
                mk_trend = mk.get("trend", "")
                mk_strength = mk.get("strength", "none")

                if mk_trend and mk_trend != "insufficient_data" and mk_strength != "none":
                    if mk_strength == "strong":
                        trend_desc = f"Spending is **clearly {'rising' if mk_trend == 'increasing' else 'falling'}** over recent months"
                    elif mk_strength == "moderate":
                        trend_desc = f"Spending shows a **moderate {'upward' if mk_trend == 'increasing' else 'downward'}** trend"
                    else:
                        trend_desc = f"There's a **slight {'upward' if mk_trend == 'increasing' else 'downward'}** tendency"
                    st.caption(trend_desc)

                seas = cached_adv.get("seasonality", {})
                if seas.get("has_seasonality") and seas.get("strength", 0) > 0.1:
                    s_period = seas.get("period", 0)
                    if s_period == 3:
                        st.caption("This category has a **quarterly spending pattern**")
                    elif s_period == 12:
                        st.caption("This category follows a **yearly cycle**")
                    else:
                        st.caption(f"This category shows a **repeating pattern** every ~{s_period} months")

        with col_action:
            ca = claude_actions.get(cat)
            if ca:
                sev_icon = {"critical": "🔴", "warning": "🟠", "good": "🟢"}.get(ca.get("severity", "stable"), "🔵")
                st.markdown(escape_dollars(f"**{sev_icon} {ca.get('headline', '')}**"))

                if ca.get("severity") in ("critical", "warning"):
                    st.error(escape_dollars(ca.get("action", "")))
                elif ca.get("severity") == "good":
                    st.success(escape_dollars(ca.get("action", "")))
                else:
                    st.info(escape_dollars(ca.get("action", "")))

                if ca.get("forecast_note"):
                    st.caption(escape_dollars(f"🔮 {ca['forecast_note']}"))

                impact = ca.get("impact", 0)
                if impact:
                    st.markdown(f"**Impact:** \\${impact:,.0f}/mo toward your savings target")
            else:
                if t_action:
                    st.info(f"**{t_action}**")
                if cached_pf and cached_pf.get("forecast"):
                    next_p = cached_pf["forecast"][0]["predicted"]
                    st.caption(f"🔮 Forecast: \\${next_p:,.0f} next month")
