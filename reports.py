"""
Weekly report generation and optional email dispatch.
Can be triggered manually from the app or scheduled via cron/APScheduler.
"""

import os
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import database
import config


def _get_month_phase(d: date) -> str:
    """Determine report phase based on day of month."""
    if d.day <= 7:
        return "start"    # Week 1: fresh start, set the plan
    elif d.day <= 21:
        return "middle"   # Weeks 2-3: track progress, course-correct
    else:
        return "end"      # Week 4+: final scorecard


def gather_report_data(conn, report_date: Optional[date] = None, period: str = "weekly") -> dict:
    """Pull transactions for the configured period, MTD totals, objective progress, alerts.
    period: 'weekly' (7 days), 'biweekly' (14 days), 'monthly' (month to date)
    """
    today = report_date or date.today()
    period_days = {"weekly": 7, "biweekly": 14, "monthly": (today - today.replace(day=1)).days or 30}
    week_ago = today - timedelta(days=period_days.get(period, 7))
    month_start = today.replace(day=1)

    # This week's transactions
    week_txns = database.get_transactions(
        conn,
        start_date=week_ago.isoformat(),
        end_date=today.isoformat(),
    )
    week_txns_list = [dict(t) for t in week_txns]

    # Filter to active categories only (exclude Financial Transfers, etc.)
    try:
        import category_engine
        _active_cats = category_engine.get_active_categories(conn)
        week_txns_list = [t for t in week_txns_list if t.get("category") in _active_cats]
    except Exception:
        pass

    # Month-to-date summary
    mtd_summary = database.get_monthly_summary(conn, today.year, today.month)

    # Category breakdown this month — filtered to active categories only
    _raw_breakdown = database.get_category_breakdown(
        conn, month_start.isoformat(), today.isoformat()
    )
    try:
        import category_engine
        _active_cats = category_engine.get_active_categories(conn)
        mtd_breakdown = [c for c in _raw_breakdown if c.get("category") in _active_cats]
    except Exception:
        mtd_breakdown = _raw_breakdown

    # Active alerts
    alerts = [dict(a) for a in database.get_active_alerts(conn)]

    # Objective progress (last snapshots)
    objectives = {}
    for obj in config.OBJECTIVES:
        history = database.get_objective_history(conn, obj["id"])
        if history:
            latest = dict(history[-1])
            objectives[obj["id"]] = {
                "label": obj["label"],
                "target": obj.get("target"),
                "current": latest["current_amount"],
                "deadline": obj.get("deadline"),
            }
        else:
            objectives[obj["id"]] = {
                "label": obj["label"],
                "target": obj.get("target"),
                "current": 0,
                "deadline": obj.get("deadline"),
            }

    # Spending intelligence: budget status + tips
    budget_status = []
    savings_tips = []
    try:
        import spending_intelligence
        budget_status = spending_intelligence.get_category_budget_status(conn)
        savings_tips = spending_intelligence.get_savings_tips(conn)
    except Exception:
        pass

    # MTD total for scorecard (only net-negative categories = actual spending, not refunds)
    mtd_total = sum(abs(c.get("total", 0)) for c in mtd_breakdown if c.get("total", 0) < 0) if mtd_breakdown else 0

    # ── Dashboard-grade metrics (same math as home.py) ────────────
    import models
    from calendar import monthrange
    income_data = models.get_income_for_month(today.year, today.month)
    monthly_income = income_data["total_income"] if isinstance(income_data, dict) else income_data

    fixed_costs = sum(config.FIXED_MONTHLY_EXPENSES.values())
    # Derive fixed categories from FIXED_BILL_GROUPS config (authoritative source)
    _fixed_cats = set()
    for _group_items in getattr(config, "FIXED_BILL_GROUPS", {}).values():
        _fixed_cats.update(_group_items)
    # Also include the common transaction-level category names that map to fixed bills
    _fixed_cats.update({
        "Housing & Utilities", "Debt Payments", "Giving & Church", "Family Support",
        "Transportation", "Childcare & Education", "Phone & Internet", "Car Insurance",
        "Daycare", "Church & Family", "Internet",
    })
    txn_fixed = sum(abs(c.get("total", 0)) for c in mtd_breakdown if c.get("category") in _fixed_cats)
    # Flex spending = sum of expense transactions (amount < 0) excluding fixed & internal categories
    # Computed at transaction level (not category-net) to match weekly breakdown exactly
    _excl_for_flex = _fixed_cats | config.EXCLUDED_CATEGORIES
    _flex_rows = conn.execute("""
        SELECT SUM(amount) as total FROM transactions
        WHERE date >= ? AND date <= ? AND amount < 0
          AND category NOT IN ({})
    """.format(",".join("?" for _ in _excl_for_flex)),
        (month_start.isoformat(), today.isoformat(), *_excl_for_flex)
    ).fetchone()
    txn_discretionary = abs(_flex_rows["total"]) if _flex_rows and _flex_rows["total"] else 0
    effective_fixed = max(fixed_costs, txn_fixed)
    total_outflow = effective_fixed + txn_discretionary
    savings_target_val = int(database.get_setting(conn, "monthly_savings_target", "2000"))
    saved = monthly_income - total_outflow
    savings_rate = (saved / monthly_income * 100) if monthly_income > 0 else 0

    days_in_month = monthrange(today.year, today.month)[1]
    days_left = max(days_in_month - today.day, 1)
    disc_budget = monthly_income - effective_fixed - savings_target_val
    disc_left = max(disc_budget - txn_discretionary, 0)
    daily_budget = disc_left / days_left if days_left > 0 else 0

    # Trend analysis + budget status (same engine as dashboard category cards)
    import analytics
    import analytics_cache

    # Trends: use cache first, compute fresh per category if no cache
    trends = {}
    for cat_data in mtd_breakdown:
        cat = cat_data.get("category", "")
        cached = analytics_cache.get_cached_trend(conn, cat)
        if cached:
            trends[cat] = cached
        else:
            try:
                t = analytics.analyze_category_trend(conn, cat)
                trends[cat] = {
                    "direction": t.direction, "severity": t.severity,
                    "pct_vs_mean": t.pct_vs_mean, "mean": t.mean,
                    "current": t.current, "slope_per_month": t.slope_per_month,
                }
            except Exception:
                pass

    # Budget status: fresh computation (exclude internal transfers)
    _excl = config.EXCLUDED_CATEGORIES
    budget_statuses = {}
    try:
        for s in analytics.compute_budget_status(conn):
            if s.category not in _excl:
                budget_statuses[s.category] = s
    except Exception:
        pass

    # Top merchants this month (exclude transfers/payments)
    try:
        _all_merchants = database.get_merchant_spending(conn, months=1)
        top_merchants = [m for m in _all_merchants if m.get("category") not in _excl][:10]
    except Exception:
        top_merchants = []

    # ── Phase-aware data for redesigned report ──────────────────
    month_phase = _get_month_phase(today)
    week_number = (today.day - 1) // 7 + 1
    weeks_in_month = (days_in_month - 1) // 7 + 1

    # Week-by-week cumulative breakdown (flex only — excludes fixed bills)
    weekly_breakdown = database.get_month_weekly_breakdown(
        conn, today.year, today.month,
        exclude_categories=_excl, fixed_categories=_fixed_cats,
    )

    # This week's top merchants (not monthly)
    week_merchants = database.get_weekly_merchants(
        conn, week_ago.isoformat(), today.isoformat(), exclude_categories=_excl
    )[:5]

    # Last month's over-budget categories (for "start" phase advice)
    last_month_overbudget = []
    if month_phase == "start":
        try:
            prev_month = today.month - 1 if today.month > 1 else 12
            prev_year = today.year if today.month > 1 else today.year - 1
            for s in analytics.compute_budget_status(conn, f"{prev_year}-{prev_month:02d}"):
                if s.category in _excl:
                    continue
                if hasattr(s, "status") and s.status in ("over", "elevated"):
                    last_month_overbudget.append({"category": s.category, "status": s.status})
        except Exception:
            pass

    return {
        "report_date": today.isoformat(),
        "week_start": week_ago.isoformat(),
        "period": period,
        "week_transactions": week_txns_list,
        "week_spending_total": sum(t["amount"] for t in week_txns_list if t["amount"] < 0),
        "week_txn_count": len(week_txns_list),
        "mtd_summary": mtd_summary,
        "mtd_total": mtd_total,
        "mtd_breakdown": mtd_breakdown,
        "objective_progress": objectives,
        "alerts": alerts,
        "budget_status": budget_status,
        "savings_tips": savings_tips,
        # Dashboard-grade data
        "monthly_income": monthly_income,
        "effective_fixed": effective_fixed,
        "txn_discretionary": txn_discretionary,
        "saved": saved,
        "savings_target": savings_target_val,
        "savings_rate": savings_rate,
        "days_left": days_left,
        "days_in_month": days_in_month,
        "daily_budget": daily_budget,
        "disc_budget": disc_budget,
        "trends": trends,
        "budget_statuses": budget_statuses,
        "top_merchants": top_merchants,
        "fixed_categories": _fixed_cats,
        # Phase-aware data
        "month_phase": month_phase,
        "week_number": week_number,
        "weeks_in_month": weeks_in_month,
        "weekly_breakdown": weekly_breakdown,
        "week_merchants": week_merchants,
        "last_month_overbudget": last_month_overbudget,
    }


def generate_and_save_report(db_path: str, advisor, report_date: Optional[date] = None) -> dict:
    """Orchestrate: gather data -> statistical analysis -> Claude writes report -> save to DB."""
    conn = database.get_connection(db_path)
    try:
        data = gather_report_data(conn, report_date)

        # Build statistical context for data-driven report
        statistical_context = None
        try:
            import analytics
            statistical_context = analytics.build_statistical_context(conn)
        except Exception:
            pass

        report = advisor.generate_weekly_report(
            week_transactions=data["week_transactions"],
            monthly_context=data["mtd_summary"],
            objective_progress=data["objective_progress"],
            alerts=data["alerts"],
            statistical_context=statistical_context,
        )

        report_id = database.save_weekly_report(
            conn,
            report_date=(report_date or date.today()).isoformat(),
            subject=report.get("subject", "Weekly Budget Report"),
            html_body=report.get("html_body", ""),
            plain_text=report.get("plain_text", ""),
        )

        report["id"] = report_id
        report["data"] = data
        return report
    finally:
        conn.close()


def send_email_report(report: dict) -> bool:
    """Send report via SMTP. Returns True if sent successfully."""
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    recipients = os.environ.get("REPORT_RECIPIENTS", "").split(",")

    if not all([smtp_host, smtp_user, smtp_pass, recipients[0]]):
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = report.get("subject", "Weekly Budget Report")
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)

    plain = MIMEText(report.get("plain_text", ""), "plain")
    html = MIMEText(report.get("html_body", ""), "html")
    msg.attach(plain)
    msg.attach(html)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipients, msg.as_string())
        return True
    except Exception:
        return False
