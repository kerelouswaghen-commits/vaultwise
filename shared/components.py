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
                         txn_discretionary, spent_pct, compact=False, txn_fixed=None,
                         _day_of_month=None):
    """Render the savings goal gauge. Use compact=True for the sidebar widget."""
    if _day_of_month is None:
        from datetime import date
        _day_of_month = date.today().day
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

    # Full dashboard gauge — simplified: title, saved, progress bar, target
    save_pct = min(max(saved / savings_target * 100, 0), 100) if savings_target > 0 else 0
    html = (
        f'<div style="background:#f8f9fb;border:1px solid #e2e6ed;border-radius:14px;padding:14px 16px;margin-bottom:12px;">'
        f'<div class="gauge-header" style="margin-bottom:8px;">'
        f'<span style="font-weight:700;font-size:clamp(0.85rem,3vw,1rem);">🎯 {month_display} Savings Goal</span>'
        f'<span style="font-weight:700;font-size:clamp(0.9rem,3.5vw,1.1rem);color:{gauge_color};">{status_icon} {D}{saved:,.0f} saved</span>'
        f'</div>'
        f'<div style="height:12px;border-radius:6px;background:#e5e7eb;overflow:hidden;margin:8px 0;">'
        f'<div style="height:100%;width:{save_pct:.0f}%;background:{gauge_color};border-radius:6px;transition:width 0.3s;"></div>'
        f'</div>'
        f'<div style="color:#9ca3af;font-size:0.8rem;margin-top:2px;">Target: {D}{savings_target:,}/mo</div>'
        + (f'<div style="font-size:0.72rem;color:#b45309;margin-top:2px;">Includes {D}{effective_fixed - txn_fixed:,.0f} in fixed bills not yet posted</div>'
           if txn_fixed is not None and effective_fixed > txn_fixed else '')
        + f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_category_card(cat_data, trend_d, conn, claude_actions, selected_month,
                         expanded_default=False, override_severity=None):
    """Render a single category card with trend chart, merchants, and actions.

    override_severity: dict with {icon, color, label, bar_color, badge_text} from the
    flex bar's pace-based severity — ensures the card matches the weekly bar colors.
    """
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

    # Card severity — use override from flex bars if provided
    if override_severity:
        sev = {"icon": override_severity.get("icon", "🔵"), "color": override_severity["color"], "label": override_severity.get("badge_text", "")}
        bar_color = override_severity["color"]
        fill_pct = min(120, spent / t_mean * 100) if t_mean > 0 else 50
        # Map override badge to card class — consistent theme
        _badge = override_severity.get("badge_text", "")
        if _badge in ("way over",):
            card_class = "cat-card-critical"
        elif _badge in ("elevated",):
            card_class = "cat-card-warning"
        elif _badge in ("on pace",):
            card_class = "cat-card-pace"
        elif _badge in ("under pace", "low"):
            card_class = "cat-card-good"
        else:
            card_class = "cat-card-pace"
    else:
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

        # Defaults in case history is too short for chart
        _h_avg = t_mean
        _h_std = t_std
        _h_min = t_current
        _h_max = t_current
        _h_median = t_current
        _h_months = 0

        if len(history) >= 1:
            hist_df = pd.DataFrame(list(reversed(history)))
            hist_df["total"] = hist_df["total"].abs()

            fig = go.Figure()
            # Smooth spline curve with gradient fill
            fig.add_trace(go.Scatter(
                x=hist_df["month"], y=hist_df["total"], mode="lines+markers",
                name="Actual",
                line=dict(color=sev["color"], width=3, shape="spline", smoothing=1.2),
                marker=dict(size=7, color=sev["color"], line=dict(width=2, color="white")),
                fill="tozeroy", fillcolor=f"rgba({int(sev['color'][1:3],16)},{int(sev['color'][3:5],16)},{int(sev['color'][5:7],16)},0.08)",
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
                    fill="toself", fillcolor="rgba(139,92,246,0.10)",
                    line=dict(width=0), showlegend=True, name="80% CI",
                    hoverinfo="skip",
                ))
                fig.add_trace(go.Scatter(
                    x=fc_months, y=fc_vals, mode="lines+markers",
                    name="Prophet Forecast",
                    line=dict(color=PALETTE["purple"], width=2.5, dash="dash", shape="spline", smoothing=1.2),
                    marker=dict(size=7, symbol="diamond", color=PALETTE["purple"], line=dict(width=2, color="white")),
                    hovertemplate="<b>%{x}</b><br>Forecast: $%{y:,.0f}<extra></extra>",
                ))

            # Compute real stats from history
            _h_avg = hist_df["total"].mean()
            _h_std = hist_df["total"].std() if len(hist_df) > 1 else 0
            _h_min = hist_df["total"].min()
            _h_max = hist_df["total"].max()
            _h_median = hist_df["total"].median()

            fig.add_hline(y=_h_avg, line_dash="dot", line_color=PALETTE["gray"],
                         annotation_text=f"avg ${_h_avg:,.0f}", annotation_font_size=9)

            compact_layout = {**CHART_LAYOUT, "margin": dict(t=15, b=25, l=50, r=15)}
            fig.update_layout(**compact_layout, height=220,
                             legend=dict(orientation="h", yanchor="bottom", y=1.02, font_size=9),
                             xaxis=dict(showgrid=False),
                             yaxis=dict(gridcolor="#f3f4f6", tickformat="$,.0f"))
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

            # Descriptive stats below chart
            _pct_vs_avg = ((t_current / _h_avg) - 1) * 100 if _h_avg > 0 else 0
            _pct_color = "#ef4444" if _pct_vs_avg > 15 else ("#f59e0b" if _pct_vs_avg > 0 else "#10b981")
            _pct_sign = "+" if _pct_vs_avg > 0 else ""
            _h_months = len(hist_df)

            _stats_html = (
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin:4px 0 10px;">'
                f'<div style="text-align:center;padding:6px 4px;background:#f7f8fa;border-radius:8px;">'
                f'<div style="font-size:8px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">This Month</div>'
                f'<div style="font-size:14px;font-weight:700;color:{sev["color"]};">${t_current:,.0f}</div></div>'
                f'<div style="text-align:center;padding:6px 4px;background:#f7f8fa;border-radius:8px;">'
                f'<div style="font-size:8px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">Average</div>'
                f'<div style="font-size:14px;font-weight:700;">${_h_avg:,.0f}</div></div>'
                f'<div style="text-align:center;padding:6px 4px;background:#f7f8fa;border-radius:8px;">'
                f'<div style="font-size:8px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">vs Avg</div>'
                f'<div style="font-size:14px;font-weight:700;color:{_pct_color};">{_pct_sign}{_pct_vs_avg:.0f}%</div></div>'
                f'<div style="text-align:center;padding:6px 4px;background:#f7f8fa;border-radius:8px;">'
                f'<div style="font-size:8px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">Range</div>'
                f'<div style="font-size:11px;font-weight:600;color:#374151;">${_h_min:,.0f}–${_h_max:,.0f}</div></div>'
                f'</div>'
                f'<div style="display:flex;gap:12px;font-size:11px;color:#6b7280;margin-bottom:8px;">'
                f'<span>Median: <strong>${_h_median:,.0f}</strong></span>'
                f'<span>Std: <strong>${_h_std:,.0f}</strong></span>'
                f'<span>Months: <strong>{_h_months}</strong></span>'
                f'</div>'
            )
            st.markdown(_stats_html, unsafe_allow_html=True)

        col_info, col_action = st.columns([1, 1])

        with col_info:
            # Use real computed stats, not cached zeros
            _real_slope = abs(t_slope) if t_slope != 0 else 0
            _slope_dir = "↑" if t_slope > 0 else ("↓" if t_slope < 0 else "→")
            st.markdown(f"**Trend:** {t_direction.title()} {_slope_dir} \\${_real_slope:,.0f}/mo")
            st.markdown(f"**This month:** \\${t_current:,.0f} | **Avg:** \\${_h_avg:,.0f} ± \\${_h_std:,.0f}")

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
                    st.plotly_chart(fig_m, width="stretch", config={"displayModeBar": False})

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


# ── Category icons & emoji maps ────────────────────────────────────
CATEGORY_EMOJIS = {
    "Groceries": "🛒", "Restaurants & Bars": "🍽", "Coffee Shops": "☕",
    "Shopping": "🛍", "Online Shopping": "📦", "Clothing": "👕",
    "Entertainment & Travel": "🎭", "Electronics": "📱", "Home Improvement": "🔨",
    "Medical": "🏥", "Child Activities": "⚽", "Education": "📚",
    "Cash & ATM": "💵", "Miscellaneous": "❓", "Financial Fees": "💳",
    "Charity": "❤️", "Mortgage": "🏠", "Insurance": "🛡",
    "Gas & Electric": "⚡", "Water": "💧", "Internet & Cable": "📡",
    "Phone": "📱", "Student Loans": "🎓", "Garbage": "🗑",
    "Loan Repayment": "🏦", "Transfer": "🔄", "Credit Card Payment": "💳",
}

CATEGORY_ICON_BG = {
    "Groceries": "#dcfce7", "Restaurants & Bars": "#fef3c7", "Coffee Shops": "#fef3c7",
    "Shopping": "#e0e7ff", "Online Shopping": "#e0e7ff", "Clothing": "#e0e7ff",
    "Entertainment & Travel": "#fce7f3", "Electronics": "#dbeafe", "Home Improvement": "#fef3c7",
    "Medical": "#fee2e2", "Child Activities": "#e0e7ff", "Education": "#dbeafe",
    "Cash & ATM": "#dcfce7", "Miscellaneous": "#f3f4f6", "Financial Fees": "#fee2e2",
}


def get_category_icon(category: str) -> tuple[str, str]:
    """Return (emoji, bg_color) for a category name."""
    emoji = CATEGORY_EMOJIS.get(category, "📋")
    bg = CATEGORY_ICON_BG.get(category, "#f3f4f6")
    return emoji, bg


# ── Transaction display components ─────────────────────────────────

def render_dark_summary(title, total_spent, remaining, budget, txn_count, days_remaining):
    """Render a spending summary header card."""
    pct = min(total_spent / budget * 100, 100) if budget > 0 else 0
    bar_color = "#22c55e" if remaining > 0 else "#ef4444"
    html = (
        f'<div style="background:#1a1a2e;border-radius:14px;padding:16px;color:white;margin-bottom:12px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
        f'<span style="font-size:0.85rem;font-weight:600;opacity:0.7;">{title}</span>'
        f'<span style="font-size:1.3rem;font-weight:800;">${total_spent:,.0f}</span>'
        f'</div>'
        f'<div style="height:6px;border-radius:3px;background:rgba(255,255,255,0.15);overflow:hidden;margin-bottom:8px;">'
        f'<div style="height:100%;width:{pct:.0f}%;background:{bar_color};border-radius:3px;"></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;font-size:0.75rem;opacity:0.65;">'
        f'<span>${remaining:,.0f} remaining</span>'
        f'<span>{txn_count} transactions</span>'
        + (f'<span>{days_remaining}d left</span>' if days_remaining > 0 else '')
        + f'</div></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_txn_group(date_label, daily_total, txn_rows):
    """Render a date-grouped set of transaction cards."""
    total_str = f"${abs(daily_total):,.0f}" if daily_total != 0 else ""
    html = (
        f'<div style="margin-bottom:12px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;padding:0 4px;">'
        f'<span style="font-size:0.7rem;font-weight:700;color:#9ca3af;letter-spacing:0.8px;">{date_label}</span>'
        f'<span style="font-size:0.75rem;font-weight:600;color:#6b7280;">{total_str}</span>'
        f'</div>'
    )
    for txn in txn_rows:
        _amt = txn["amount"]
        _color = "#ef4444" if _amt < 0 else "#22c55e"
        _sign = "-" if _amt < 0 else "+"
        html += (
            f'<div style="background:var(--vw-card-bg, #fff);border:1px solid #f3f4f6;border-radius:12px;padding:10px 12px;margin-bottom:4px;display:flex;align-items:center;gap:10px;">'
            f'<div style="width:34px;height:34px;border-radius:10px;background:{txn.get("bg_color", "#f3f4f6")};display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;">{txn.get("icon", "📋")}</div>'
            f'<div style="flex:1;min-width:0;">'
            f'<div style="font-size:0.85rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{txn["name"]}</div>'
            f'<div style="font-size:0.7rem;color:#9ca3af;">{txn["category"]}</div>'
            f'</div>'
            f'<div style="text-align:right;flex-shrink:0;">'
            f'<div style="font-size:0.9rem;font-weight:700;color:{_color};">{_sign}${abs(_amt):,.2f}</div>'
            f'<div style="font-size:0.65rem;color:#9ca3af;">{txn.get("account", "")}</div>'
            f'</div></div>'
        )
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


# ── Plan / Savings Journey components ──────────────────────────────

def render_income_allocation_bar(effective_fixed, savings_target, flex_budget, monthly_income):
    """Render the income allocation stacked bar for the Plan page."""
    total = monthly_income if monthly_income > 0 else 1
    f_pct = effective_fixed / total * 100
    s_pct = savings_target / total * 100
    d_pct = max(100 - f_pct - s_pct, 0)
    html = (
        f'<div style="margin:12px 0 16px;">'
        f'<div style="display:flex;height:24px;border-radius:8px;overflow:hidden;margin-bottom:6px;">'
        f'<div style="width:{f_pct:.0f}%;background:#6b7280;"></div>'
        f'<div style="width:{s_pct:.0f}%;background:#7c3aed;"></div>'
        f'<div style="width:{d_pct:.0f}%;background:#22c55e;"></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#6b7280;">'
        f'<span>🏠 Fixed ${effective_fixed:,.0f}</span>'
        f'<span>🎯 Save ${savings_target:,.0f}</span>'
        f'<span>💳 Flex ${flex_budget:,.0f}</span>'
        f'</div></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_plan_hero(projected_savings, savings_target, year_savings=0):
    """Render the plan page projected savings hero."""
    color = "#22c55e" if projected_savings >= savings_target else "#f59e0b"
    html = (
        f'<div style="background:#f8f9fb;border:1px solid #e2e6ed;border-radius:14px;padding:16px;text-align:center;margin-bottom:12px;">'
        f'<div style="font-size:0.8rem;color:#6b7280;margin-bottom:4px;">Projected Monthly Savings</div>'
        f'<div style="font-size:2rem;font-weight:800;color:{color};">${projected_savings:,.0f}</div>'
        f'<div style="font-size:0.8rem;color:#9ca3af;">Target: ${savings_target:,}/mo</div>'
        + (f'<div style="font-size:0.75rem;color:#6b7280;margin-top:4px;">≈ ${year_savings:,.0f}/year</div>' if year_savings else '')
        + f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_year_projection(projected_savings, daycare_amount=0):
    """Render year projection cards for plan page."""
    annual = projected_savings * 12
    html = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0;">'
        f'<div style="background:#f0fdf4;border-radius:12px;padding:12px;text-align:center;">'
        f'<div style="font-size:0.75rem;color:#6b7280;">Annual Savings</div>'
        f'<div style="font-size:1.3rem;font-weight:800;color:#22c55e;">${annual:,.0f}</div>'
        f'</div>'
    )
    if daycare_amount > 0:
        post_daycare = (projected_savings + daycare_amount) * 12
        html += (
            f'<div style="background:#f0f9ff;border-radius:12px;padding:12px;text-align:center;">'
            f'<div style="font-size:0.75rem;color:#6b7280;">Post-Daycare</div>'
            f'<div style="font-size:1.3rem;font-weight:800;color:#2563eb;">${post_daycare:,.0f}/yr</div>'
            f'</div>'
        )
    else:
        html += (
            f'<div style="background:#f8f9fb;border-radius:12px;padding:12px;text-align:center;">'
            f'<div style="font-size:0.75rem;color:#6b7280;">5-Year Total</div>'
            f'<div style="font-size:1.3rem;font-weight:800;color:#374151;">${annual * 5:,.0f}</div>'
            f'</div>'
        )
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)
