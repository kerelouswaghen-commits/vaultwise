"""Chart constants and reusable chart builders."""

import plotly.graph_objects as go

CHART_LAYOUT = dict(
    margin=dict(t=40, b=35, l=55, r=30),
    font=dict(family="Inter, system-ui, sans-serif", size=12, color="#374151"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    hovermode="x unified",
    hoverlabel=dict(bgcolor="white", font_size=12, bordercolor="#e2e6ed"),
)

PALETTE = {
    "red": "#ef4444", "red_light": "#fecaca",
    "green": "#22c55e", "green_light": "#bbf7d0",
    "blue": "#3b82f6", "blue_light": "#bfdbfe",
    "amber": "#f59e0b", "amber_light": "#fde68a",
    "purple": "#8b5cf6", "purple_light": "#c4b5fd",
    "gray": "#6b7280", "gray_light": "#e5e7eb",
    "teal": "#14b8a6",
    "rose": "#f43f5e",
}

CATEGORY_PALETTE = [
    "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
    "#14b8a6", "#f43f5e", "#06b6d4", "#84cc16", "#ec4899",
    "#a855f7", "#f97316", "#0ea5e9", "#10b981", "#6366f1",
]

SEVERITY_MAP = {
    "critical": {"icon": "🔴", "color": PALETTE["red"], "label": "Needs Action"},
    "warning": {"icon": "🟠", "color": PALETTE["amber"], "label": "Watch"},
    "watch": {"icon": "🟡", "color": PALETTE["amber"], "label": "Monitor"},
    "normal": {"icon": "🟢", "color": PALETTE["green"], "label": "On Track"},
}

DIRECTION_ICONS = {"rising": "↑", "falling": "↓", "stable": "→"}

DEFAULT_TREND_DICT = {
    "category": "", "direction": "stable", "slope_per_month": 0,
    "r_squared": 0, "current": 0, "mean": 0, "std": 0,
    "pct_vs_mean": 0, "months_analyzed": 0, "forecast_next": 0,
    "severity": "normal", "action": "",
}


def make_monthly_net_chart(df, height=340, ci_low=None, ci_high=None):
    """Bar chart of monthly surplus/deficit with optional confidence bands."""
    colors = [PALETTE["red"] if x < 0 else PALETTE["green"] for x in df["monthly_net"]]
    fig = go.Figure(go.Bar(
        x=df["month"], y=df["monthly_net"], marker_color=colors,
        marker_line_width=0,
        hovertemplate="<b>%{x}</b><br>Net: %{y:$,.0f}<extra></extra>",
    ))
    fig.add_hline(y=0, line_color=PALETTE["gray_light"], line_width=1)
    fig.update_layout(**CHART_LAYOUT, height=height, showlegend=False,
                     yaxis=dict(title="Monthly Net ($)", gridcolor="#f3f4f6", zeroline=False,
                               tickformat="$,.0f"),
                     xaxis=dict(gridcolor="#f3f4f6", dtick="M6"))
    return fig


def make_cumulative_chart(df, height=370, ci_low=None, ci_high=None):
    """Line chart of cumulative savings with optional confidence bands."""
    fig = go.Figure()

    if ci_low and ci_high:
        fig.add_trace(go.Scatter(
            x=list(df["month"]) + list(df["month"])[::-1],
            y=ci_high + ci_low[::-1],
            fill="toself", fillcolor="rgba(59,130,246,0.08)",
            line=dict(width=0), showlegend=True, name="80% confidence band",
            hoverinfo="skip",
        ))

    fig.add_trace(go.Scatter(
        x=df["month"], y=df["cumulative"], mode="lines",
        line=dict(color=PALETTE["blue"], width=3),
        fill="tozeroy" if not ci_low else None,
        fillcolor="rgba(59,130,246,0.04)" if not ci_low else None,
        hovertemplate="<b>%{x}</b><br>Savings: $%{y:,.0f}<extra></extra>",
        name="Projected savings",
    ))

    fig.add_hline(y=0, line_color=PALETTE["red"], line_width=1, line_dash="dot",
                  annotation_text="Break-even line", annotation_font=dict(size=9, color=PALETTE["red"]),
                  annotation_position="bottom right")

    min_idx = df["cumulative"].idxmin()
    fig.add_annotation(
        x=df.loc[min_idx, "month"], y=df.loc[min_idx, "cumulative"],
        text=f"<b>Lowest: ${df.loc[min_idx, 'cumulative']:,.0f}</b>",
        showarrow=True, arrowhead=2, arrowcolor=PALETTE["red"],
        font=dict(color=PALETTE["red"], size=11),
        bgcolor="white", bordercolor=PALETTE["red"], borderwidth=1, borderpad=4,
    )
    last_row = df.iloc[-1]
    fig.add_annotation(
        x=last_row["month"], y=last_row["cumulative"],
        text=f"<b>Final: ${last_row['cumulative']:,.0f}</b>",
        showarrow=True, arrowhead=2, arrowcolor=PALETTE["green"],
        font=dict(color=PALETTE["green"], size=11),
        bgcolor="white", bordercolor=PALETTE["green"], borderwidth=1, borderpad=4,
    )

    fig.update_layout(**CHART_LAYOUT, height=height,
                     legend=dict(orientation="h", yanchor="bottom", y=1.02, font_size=10),
                     yaxis=dict(title="Cumulative Savings ($)", gridcolor="#f3f4f6",
                               zeroline=False, tickformat="$,.0f"),
                     xaxis=dict(gridcolor="#f3f4f6", dtick="M6"))
    return fig
