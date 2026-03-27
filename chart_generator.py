"""
Chart generation module — creates Plotly charts and exports as PNG bytes.
Used for Telegram reports and downloadable images.
Requires kaleido for static image export.
"""

from typing import Optional

import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd

import config
import models


# Consistent color palette
COLORS = {
    "green": "#2ecc71",
    "red": "#e74c3c",
    "blue": "#3498db",
    "orange": "#f39c12",
    "purple": "#9b59b6",
    "gray": "#95a5a6",
    "dark": "#2c3e50",
}

CATEGORY_COLORS = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#34495e", "#e91e63", "#00bcd4",
    "#8bc34a", "#ff9800", "#795548", "#607d8b", "#673ab7",
]


def _to_png(fig: go.Figure, width: int = 800, height: int = 500) -> bytes:
    """Convert a Plotly figure to PNG bytes."""
    return pio.to_image(fig, format="png", width=width, height=height, scale=2)


def generate_weekly_spending_chart(weekly_data: dict) -> bytes:
    """Bar chart of this week's spending by category."""
    categories = weekly_data.get("categories", {})
    if not categories:
        return _empty_chart("No spending data this week")

    cats = sorted(categories.keys(), key=lambda k: categories[k]["total"])
    values = [abs(categories[k]["total"]) for k in cats]

    fig = go.Figure(go.Bar(
        x=values,
        y=cats,
        orientation="h",
        marker_color=CATEGORY_COLORS[:len(cats)],
        text=[f"${v:,.0f}" for v in values],
        textposition="auto",
    ))
    fig.update_layout(
        title=f"This Week's Spending: ${sum(values):,.0f}",
        xaxis_title="Amount ($)",
        height=max(400, len(cats) * 35 + 100),
        margin=dict(l=150),
        font=dict(size=14),
    )
    return _to_png(fig, width=800, height=max(400, len(cats) * 35 + 100))


def generate_monthly_trend_chart(trend_data: list[dict]) -> bytes:
    """Line chart of monthly spending over time."""
    if not trend_data:
        return _empty_chart("No trend data available")

    df = pd.DataFrame(trend_data)
    df["spending"] = df["spending"].abs()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["month"], y=df["spending"],
        mode="lines+markers",
        name="Monthly Spending",
        line=dict(color=COLORS["red"], width=3),
        marker=dict(size=8),
    ))

    # Average line
    avg = df["spending"].mean()
    fig.add_hline(y=avg, line_dash="dash", line_color=COLORS["gray"],
                  annotation_text=f"Avg: ${avg:,.0f}")

    fig.update_layout(
        title="Monthly Spending Trend",
        xaxis_title="Month",
        yaxis_title="Total Spent ($)",
        height=400,
        font=dict(size=14),
    )
    return _to_png(fig)


def generate_category_pie_chart(breakdown: list[dict]) -> bytes:
    """Pie chart of spending by category."""
    if not breakdown:
        return _empty_chart("No category data")

    # Filter to expenses only, top 10
    expenses = [b for b in breakdown if b.get("total", 0) < 0]
    expenses.sort(key=lambda x: x["total"])
    top = expenses[:10]

    labels = [b["category"] for b in top]
    values = [abs(b["total"]) for b in top]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.4,
        marker_colors=CATEGORY_COLORS[:len(labels)],
        textinfo="label+percent",
        textfont_size=12,
    ))
    fig.update_layout(
        title="Spending by Category",
        height=500,
        font=dict(size=14),
    )
    return _to_png(fig, width=800, height=500)


def generate_cashflow_chart(months_ahead: int = 66) -> bytes:
    """Cash flow projection chart."""
    df = models.project_cash_flow(months_ahead=months_ahead)

    fig = go.Figure()

    # Monthly net as bars
    colors = [COLORS["red"] if x < 0 else COLORS["green"] for x in df["monthly_net"]]
    fig.add_trace(go.Bar(
        x=df["month"], y=df["monthly_net"],
        name="Monthly Net",
        marker_color=colors,
        opacity=0.7,
    ))

    # Cumulative line
    fig.add_trace(go.Scatter(
        x=df["month"], y=df["cumulative"],
        mode="lines",
        name="Cumulative Savings",
        line=dict(color=COLORS["blue"], width=3),
        yaxis="y2",
    ))

    fig.update_layout(
        title="Cash Flow Projection",
        xaxis_title="Month",
        yaxis=dict(title="Monthly Net ($)"),
        yaxis2=dict(title="Cumulative ($)", overlaying="y", side="right"),
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        font=dict(size=12),
    )
    return _to_png(fig, width=1000, height=500)


def generate_objective_progress_chart(objectives: list[dict]) -> bytes:
    """Horizontal bar chart of objective progress."""
    if not objectives:
        return _empty_chart("No objectives configured")

    labels = []
    targets = []
    currents = []

    for obj in objectives:
        target = obj.get("target", 0) or 0
        current = obj.get("current", 0) or 0
        if target > 0:
            labels.append(obj.get("label", obj.get("objective_id", "?")))
            targets.append(target)
            currents.append(min(current, target))

    if not labels:
        return _empty_chart("No measurable objectives")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=labels, x=targets, orientation="h",
        name="Target", marker_color=COLORS["gray"], opacity=0.3,
    ))
    fig.add_trace(go.Bar(
        y=labels, x=currents, orientation="h",
        name="Current", marker_color=COLORS["green"],
        text=[f"${c:,.0f} / ${t:,.0f}" for c, t in zip(currents, targets)],
        textposition="auto",
    ))

    fig.update_layout(
        title="Objective Progress",
        barmode="overlay",
        height=max(300, len(labels) * 60 + 100),
        margin=dict(l=200),
        font=dict(size=14),
    )
    return _to_png(fig, width=800, height=max(300, len(labels) * 60 + 100))


def _empty_chart(message: str) -> bytes:
    """Generate a placeholder chart with a message."""
    fig = go.Figure()
    fig.add_annotation(
        text=message, xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False, font=dict(size=20, color=COLORS["gray"]),
    )
    fig.update_layout(
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        height=300,
    )
    return _to_png(fig, width=800, height=300)
