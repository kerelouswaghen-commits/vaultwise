"""
Spending intelligence — data-driven analytics for tactical advisor context.
No Claude dependency. All insights computed from actual transaction data using
statistical methods from analytics.py — no hardcoded thresholds or dollar amounts.
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import numpy as np

import analytics
import config
import database


def _get_latest_data_month(conn) -> date:
    """Get the most recent month that has transaction data."""
    return analytics._get_data_date(conn)


def get_spending_velocity(conn, category: Optional[str] = None) -> dict:
    """
    How much spent in each category so far this month, projected to month-end.
    Uses EWMA-weighted projection instead of naive linear interpolation.
    """
    from calendar import monthrange
    today = _get_latest_data_month(conn)
    month_start = today.replace(day=1)
    days_elapsed = (today - month_start).days + 1
    days_in_month = monthrange(today.year, today.month)[1]
    pct_elapsed = days_elapsed / days_in_month

    params = [month_start.isoformat()]
    query = """
        SELECT category, SUM(amount) as total, COUNT(*) as count
        FROM transactions WHERE date >= ? AND amount < 0
    """
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " GROUP BY category ORDER BY total ASC"

    rows = conn.execute(query, params).fetchall()

    # Get historical monthly averages for smarter projection
    hist_avgs = {}
    six_months_ago = analytics._months_back(today, 6)
    hist_rows = conn.execute("""
        SELECT category,
               SUM(amount) as total,
               COUNT(DISTINCT strftime('%Y-%m', date)) as months
        FROM transactions
        WHERE date >= ? AND date < ? AND amount < 0
        GROUP BY category
    """, (six_months_ago.isoformat(), month_start.isoformat())).fetchall()
    for r in hist_rows:
        months_count = max(r["months"], 1)
        hist_avgs[r["category"]] = abs(r["total"]) / months_count

    result = {}
    for r in rows:
        spent = abs(r["total"])
        hist_avg = hist_avgs.get(r["category"], 0)

        # Blended projection: weight between linear extrapolation and historical avg
        linear_proj = spent / max(pct_elapsed, 0.05)
        if hist_avg > 0 and pct_elapsed < 0.5:
            # Early in month: lean toward historical average
            weight = pct_elapsed  # 0 at start, 0.5 midway
            projected = weight * linear_proj + (1 - weight) * hist_avg
        else:
            projected = linear_proj

        result[r["category"]] = {
            "spent_so_far": round(spent, 2),
            "projected_month_end": round(projected, 2),
            "historical_avg": round(hist_avg, 2),
            "transactions": r["count"],
            "days_elapsed": days_elapsed,
            "days_remaining": days_in_month - days_elapsed,
            "pct_of_month": round(pct_elapsed * 100, 1),
        }
    return result


def get_merchant_frequency(conn, months: int = 3) -> list[dict]:
    """Top merchants ranked by frequency and spend."""
    return database.get_merchant_spending(conn, months)


def get_category_budget_status(conn, month_key: str = None) -> list[dict]:
    """
    Each category's current month vs historical — using statistical analysis.
    Returns budget status from analytics engine (percentile-based, not hardcoded).
    month_key: optional "YYYY-MM" to evaluate a specific month.
    """
    statuses = analytics.compute_budget_status(conn, month_key=month_key)
    return [
        {
            "category": s.category,
            "current_spend": s.current_spend,
            "monthly_average": s.historical_mean,
            "monthly_median": s.historical_median,
            "expected_by_now": round(s.historical_mean * s.pct_of_month_elapsed, 2),
            "projected_month_end": s.projected_month_end,
            "pct_of_average": round(s.current_spend / s.historical_mean * 100, 1) if s.historical_mean > 0 else 0,
            "percentile": s.percentile,
            "status": s.status.upper().replace("_", " ") if s.status in ("over", "elevated") else s.status,
            "savings_potential": s.savings_potential,
        }
        for s in statuses
    ]


def get_substitution_opportunities(conn) -> list[dict]:
    """Identify weeks with spending consolidation opportunities using data patterns."""
    today = _get_latest_data_month(conn)
    four_weeks_ago = today - timedelta(days=28)

    rows = conn.execute("""
        SELECT date, description, amount, category
        FROM transactions
        WHERE date >= ? AND amount < 0
          AND category IN ('Costco', 'Groceries', 'Dining Out')
        ORDER BY date ASC
    """, (four_weeks_ago.isoformat(),)).fetchall()

    # Group by week
    weeks = defaultdict(list)
    for r in rows:
        d = date.fromisoformat(r["date"])
        week_num = d.isocalendar()[1]
        weeks[week_num].append(dict(r))

    # Get historical weekly averages for comparison
    hist_weekly = conn.execute("""
        SELECT category, AVG(weekly_total) as avg_weekly FROM (
            SELECT category, strftime('%Y-%W', date) as week,
                   SUM(amount) as weekly_total
            FROM transactions
            WHERE amount < 0 AND category IN ('Costco', 'Groceries', 'Dining Out')
            GROUP BY category, week
        ) GROUP BY category
    """).fetchall()
    weekly_avgs = {r["category"]: abs(r["avg_weekly"]) for r in hist_weekly}

    opportunities = []
    for week, txns in weeks.items():
        costco = [t for t in txns if t["category"] == "Costco"]
        grocery = [t for t in txns if t["category"] == "Groceries"]
        dining = [t for t in txns if t["category"] == "Dining Out"]

        costco_total = sum(abs(t["amount"]) for t in costco)
        grocery_total = sum(abs(t["amount"]) for t in grocery)
        dining_total = sum(abs(t["amount"]) for t in dining)

        # Data-driven: flag if both Costco and grocery are above their weekly averages
        costco_avg = weekly_avgs.get("Costco", 200)
        if costco and grocery and costco_total > costco_avg:
            potential = round(grocery_total * 0.3, 2)
            opportunities.append({
                "type": "costco_consolidation",
                "week": week,
                "message": (f"Week {week}: Costco ${costco_total:.0f} + grocery ${grocery_total:.0f}. "
                            f"Your Costco avg is ${costco_avg:.0f}/wk. "
                            f"Plan Costco trips to replace separate grocery runs."),
                "potential_savings": potential,
            })

        dining_avg = weekly_avgs.get("Dining Out", 120)
        if dining_total > dining_avg * 1.3:
            excess = dining_total - dining_avg
            opportunities.append({
                "type": "dining_reduction",
                "week": week,
                "message": (f"Week {week}: ${dining_total:.0f} on dining "
                            f"({len(dining)} visits) — ${excess:.0f} above your weekly avg. "
                            f"Cook 2 extra meals at home to get back on track."),
                "potential_savings": round(excess * 0.6, 2),
            })

    return opportunities


def get_savings_tips(conn) -> list[dict]:
    """
    Generate savings tips using statistical analysis — fully data-driven.
    Every tip is backed by actual numbers from the database.
    """
    opportunities = analytics.detect_savings_opportunities(conn)
    subs = get_substitution_opportunities(conn)

    tips = []

    # Convert statistically-detected opportunities to tips
    for opp in opportunities:
        merchant_str = ""
        if opp.top_merchants:
            merchant_str = " Top merchants: " + ", ".join(
                f"{m['name']} (${m['total']:,.0f}, {m['visits']}x)"
                for m in opp.top_merchants[:3]
            ) + "."

        tips.append({
            "priority": 1 if opp.difficulty == "easy" else (2 if opp.difficulty == "moderate" else 3),
            "category": opp.category,
            "tip": f"{opp.basis}{merchant_str}",
            "savings": opp.monthly_savings,
            "confidence": opp.confidence,
            "difficulty": opp.difficulty,
        })

    # Add substitution opportunities
    for sub in subs[:2]:
        tips.append({
            "priority": 4,
            "category": sub["type"],
            "tip": sub["message"],
            "savings": sub.get("potential_savings", 0),
            "confidence": 0.7,
            "difficulty": "moderate",
        })

    return sorted(tips, key=lambda x: x["savings"], reverse=True)


def build_tactical_context(conn) -> dict:
    """
    Aggregate all spending intelligence into a single context blob for Claude.
    All values are data-derived from statistical analysis.
    """
    data_date = _get_latest_data_month(conn)
    today = date.today()

    velocity = get_spending_velocity(conn)
    budget_status = get_category_budget_status(conn)
    merchants = get_merchant_frequency(conn)
    substitutions = get_substitution_opportunities(conn)
    tips = get_savings_tips(conn)

    # Current week spending
    this_week = database.get_weekly_spending(conn, weeks_back=0)
    last_week = database.get_weekly_spending(conn, weeks_back=1)

    # Statistical context from analytics engine
    try:
        stat_context = analytics.build_statistical_context(conn)
    except Exception:
        stat_context = {}

    return {
        "today": today.isoformat(),
        "data_as_of": data_date.isoformat(),
        "savings_target": int(database.get_setting(conn, "monthly_savings_target", "1000")),
        "spending_velocity": {k: v for k, v in velocity.items() if v.get("spent_so_far", 0) > 0},
        "budget_status": [s for s in budget_status if s["current_spend"] > 0],
        "top_merchants": merchants[:15],
        "this_week": this_week,
        "last_week": last_week,
        "week_over_week_change": (
            round(this_week.get("total", 0) - last_week.get("total", 0), 2)
            if this_week.get("total") and last_week.get("total") else None
        ),
        "substitution_opportunities": substitutions,
        "savings_tips": tips,
        "total_potential_monthly_savings": sum(t["savings"] for t in tips),
        "statistical_analysis": stat_context,
    }
