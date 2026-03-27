"""
Data models (dataclasses) and deterministic forecast / scenario logic.
Claude provides narrative interpretation; this module provides the numbers.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd

import config


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    id: Optional[int]
    date: date
    description: str
    raw_description: str
    amount: float
    category: str
    account_id: str
    statement_id: Optional[int]
    confidence: float = 1.0
    notes: str = ""


@dataclass
class Statement:
    id: Optional[int]
    filename: str
    account_id: str
    period_start: date
    period_end: date
    sha256: str
    upload_timestamp: datetime = field(default_factory=datetime.now)
    status: str = "processed"
    transaction_count: int = 0


@dataclass
class MonthlySnapshot:
    year: int
    month: int
    income: float
    total_expenses: float
    by_category: dict = field(default_factory=dict)
    net: float = 0.0
    savings_rate: float = 0.0


@dataclass
class Objective:
    id: str
    label: str
    target: Optional[float]
    target_rate_monthly: Optional[float]
    deadline: Optional[date]
    current_amount: float = 0.0
    priority: int = 99


# ---------------------------------------------------------------------------
# Income projection
# ---------------------------------------------------------------------------

def get_income_for_month(year: int, month: int) -> dict:
    """Project monthly income using verified payroll data.

    Kero:  $10,617 base ($4,900 biweekly × 26/12) → +$285/mo each March
    Maggie: $7,746 base ($3,575 biweekly × 26/12) → +$220/mo each January
    Bonuses: Kero $1,500/mo spread, Maggie $417/mo spread (always included)
    """
    # Kero net pay: base $10,617 with step-ups in March
    kero_base = config.INCOME["kero"]["monthly_net"]  # 10,617
    raise_amt = int(config.INCOME["kero"]["annual_raise"] * 0.057)  # ~$285/mo net from $5K gross
    for yr in range(2027, year + 1):
        if (year, month) >= (yr, config.INCOME["kero"]["raise_month"]):
            kero_base += raise_amt

    # Maggie net pay: base $7,746 with step-ups in January
    maggie_base = config.INCOME["maggie"]["monthly_net"]  # 7,746
    raise_amt_m = int(config.INCOME["maggie"]["annual_raise"] * 0.055)  # ~$220/mo net from $4K gross
    for yr in range(2027, year + 1):
        if (year, month) >= (yr, config.INCOME["maggie"]["raise_month"]):
            maggie_base += raise_amt_m

    kero_bonus = 1_500
    maggie_bonus = 417
    total = kero_base + maggie_base + kero_bonus + maggie_bonus

    return {
        "kero_net": kero_base,
        "maggie_net": maggie_base,
        "kero_bonus": kero_bonus,
        "maggie_bonus": maggie_bonus,
        "total_income": total,
    }


# ---------------------------------------------------------------------------
# Cash flow projection
# ---------------------------------------------------------------------------

def project_cash_flow(
    months_ahead: int = 66,
    start_year: int = 2026,
    start_month: int = 4,
    monthly_expense_override: Optional[float] = None,
    savings_adjustments: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Project month-by-month cash flow from start through months_ahead.
    Uses income growth model from config.
    """
    rows = []
    cumulative = 0.0
    # Compute dynamically from current fixed expenses + credit card average
    monthly_expenses = monthly_expense_override or (
        sum(config.FIXED_MONTHLY_EXPENSES.values()) + getattr(config, 'CC_MONTHLY_AVERAGE', 5894)
    )

    # Apply savings adjustments if provided
    adjustment = 0.0
    if savings_adjustments:
        adjustment = sum(savings_adjustments.values())

    year, month = start_year, start_month
    for i in range(months_ahead):
        income_info = get_income_for_month(year, month)

        total_income = income_info["total_income"]
        total_expenses = monthly_expenses - adjustment

        monthly_net = total_income - total_expenses
        cumulative += monthly_net

        rows.append({
            "month": f"{year:04d}-{month:02d}",
            "year": year,
            "month_num": month,
            "kero_net": income_info["kero_net"],
            "maggie_net": income_info["maggie_net"],
            "kero_bonus": income_info["kero_bonus"],
            "maggie_bonus": income_info["maggie_bonus"],
            "total_income": total_income,
            "monthly_expenses": monthly_expenses - adjustment,
            "total_expenses": total_expenses,
            "monthly_net": monthly_net,
            "cumulative": cumulative,
        })

        # Advance month
        month += 1
        if month > 12:
            month = 1
            year += 1

    return pd.DataFrame(rows)


def scenario_model(
    base_df: pd.DataFrame,
    adjustments: dict,
) -> pd.DataFrame:
    """Apply what-if adjustments to a base projection.

    adjustments can include:
      - Category expense changes: {"Dining Out": -200}
      - Income changes: {"income_change": 5000}  (annual, spread monthly)
    """
    df = base_df.copy()

    # Expense adjustments (negative = savings)
    expense_adj = sum(v for k, v in adjustments.items() if k != "income_change")
    income_adj = adjustments.get("income_change", 0) / 12

    df["monthly_expenses"] = df["monthly_expenses"] + expense_adj
    df["total_income"] = df["total_income"] + income_adj

    df["total_expenses"] = df["monthly_expenses"]
    df["monthly_net"] = df["total_income"] - df["total_expenses"]
    df["cumulative"] = df["monthly_net"].cumsum()

    return df


def detect_anomalies(monthly_summaries: list[dict], threshold_std: float = 2.0) -> list[dict]:
    """Flag categories where a month's spending exceeds threshold standard deviations."""
    if not monthly_summaries:
        return []

    # Build per-category series
    from collections import defaultdict
    cat_values = defaultdict(list)
    for summary in monthly_summaries:
        for cat, data in summary.get("categories", {}).items():
            cat_values[cat].append(abs(data.get("total", 0)))

    anomalies = []
    for cat, values in cat_values.items():
        if len(values) < 3:
            continue
        s = pd.Series(values)
        mean = s.mean()
        std = s.std()
        if std == 0:
            continue
        latest = values[-1]
        if latest > mean + threshold_std * std:
            anomalies.append({
                "category": cat,
                "latest_amount": latest,
                "average": round(mean, 2),
                "std_dev": round(std, 2),
                "z_score": round((latest - mean) / std, 2),
                "message": f"{cat} spending of ${latest:,.0f} is {(latest - mean) / std:.1f}x above average (${mean:,.0f})",
            })

    return sorted(anomalies, key=lambda x: x["z_score"], reverse=True)


def compute_savings_status(conn, target_monthly: int = 1000) -> dict:
    """
    Compute savings status relative to a user-defined monthly target.
    Uses actual transaction data to compare income vs expenses.
    """
    import database
    today = date.today()

    # Get last 3 months of actual data
    three_months_ago = date(today.year, today.month - 3, 1) if today.month > 3 else date(today.year - 1, today.month + 9, 1)
    rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month,
               SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as income,
               SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) as expenses
        FROM transactions
        WHERE date >= ?
        GROUP BY month
        ORDER BY month
    """, (three_months_ago.isoformat(),)).fetchall()

    monthly_nets = []
    for r in rows:
        net = (r["income"] or 0) + (r["expenses"] or 0)  # expenses are negative
        monthly_nets.append({"month": r["month"], "income": r["income"] or 0,
                            "expenses": abs(r["expenses"] or 0), "net": round(net, 2)})

    avg_net = sum(m["net"] for m in monthly_nets) / max(len(monthly_nets), 1) if monthly_nets else 0
    avg_expenses = sum(m["expenses"] for m in monthly_nets) / max(len(monthly_nets), 1) if monthly_nets else 0

    # Project savings based on cash flow model
    df = project_cash_flow(months_ahead=12)
    projected_nets = df["monthly_net"].tolist()[:12]
    avg_projected = sum(projected_nets) / len(projected_nets) if projected_nets else 0

    # Gap: how far are we from the target?
    current_gap = target_monthly - avg_net if avg_net < target_monthly else 0
    projected_gap = target_monthly - avg_projected if avg_projected < target_monthly else 0

    # On track?
    on_track = avg_net >= target_monthly

    return {
        "target_monthly": target_monthly,
        "actual_avg_net": round(avg_net, 2),
        "actual_avg_expenses": round(avg_expenses, 2),
        "projected_avg_net": round(avg_projected, 2),
        "current_gap": round(current_gap, 2),
        "projected_gap": round(projected_gap, 2),
        "on_track": on_track,
        "monthly_data": monthly_nets,
        "months_analyzed": len(monthly_nets),
    }
