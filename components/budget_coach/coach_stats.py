"""
Budget coach statistical engine — all computations, no UI.
Every number the coach shows traces back to a function here.
"""

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

import config
from components.budget_coach import coach_config as cfg


# ── Helpers ────────────────────────────────────────────────────────────

def _months_back(ref: date, months: int) -> date:
    """Go back N months from a reference date."""
    m = ref.month - months
    y = ref.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _get_reference_date(conn) -> date:
    """Today's date (or latest transaction date if needed)."""
    return date.today()


def _excluded_categories() -> set:
    base = set(getattr(config, "EXCLUDED_CATEGORIES", {
        "Transfers & Payments", "Income & Refunds", "Debt Payments",
    }))
    # Always exclude transfer/income categories regardless of config naming
    base.update({"Financial Transfers", "Transfers & Savings"})
    return base


# ── 1. Category Classification ────────────────────────────────────────

def classify_categories(conn, n_months: int = None) -> dict:
    """
    Classify each category as fixed / flexible_recurring / one_time / flexible
    based on CV and appearance rate over the last n_months.
    """
    n_months = n_months or cfg.PROFILE_LOOKBACK_MONTHS
    ref = _get_reference_date(conn)
    start = _months_back(ref, n_months)
    current_month_start = ref.replace(day=1)
    excluded = _excluded_categories()

    rows = conn.execute("""
        SELECT category, strftime('%Y-%m', date) as month_key,
               SUM(ABS(amount)) as total
        FROM transactions
        WHERE date >= ? AND date < ? AND amount < 0
        GROUP BY category, month_key
        ORDER BY category, month_key
    """, (start.isoformat(), current_month_start.isoformat())).fetchall()

    # Build per-category monthly totals
    cat_months = defaultdict(dict)
    all_months = set()
    for r in rows:
        cat = r["category"]
        if cat in excluded:
            continue
        mk = r["month_key"]
        cat_months[cat][mk] = r["total"]
        all_months.add(mk)

    total_months = len(all_months) if all_months else n_months
    profiles = {}

    for cat, month_data in cat_months.items():
        amounts = list(month_data.values())
        n_present = len(amounts)
        appearance_rate = n_present / max(total_months, 1)

        mean_val = float(np.mean(amounts)) if amounts else 0
        std_val = float(np.std(amounts, ddof=1)) if len(amounts) > 1 else 0
        cv = std_val / mean_val if mean_val > 0 else 999
        median_val = float(np.median(amounts)) if amounts else 0

        # Percentiles for guardrails
        p25 = float(np.percentile(amounts, 25)) if len(amounts) >= 4 else mean_val * 0.8
        p50 = median_val
        p75 = float(np.percentile(amounts, 75)) if len(amounts) >= 4 else mean_val * 1.2

        # Sorted monthly values for display
        sorted_months = sorted(month_data.keys())
        last_n = [month_data[m] for m in sorted_months]

        # Classification
        if appearance_rate >= cfg.FIXED_APPEARANCE_THRESHOLD and cv < cfg.FIXED_CV_THRESHOLD:
            cat_type = "fixed"
        elif appearance_rate >= cfg.FIXED_APPEARANCE_THRESHOLD and cv >= cfg.FIXED_CV_THRESHOLD:
            cat_type = "flexible_recurring"
        elif (appearance_rate < cfg.ONE_TIME_APPEARANCE_THRESHOLD and
              any(a > cfg.ONE_TIME_SPIKE_MULTIPLIER * median_val for a in amounts)):
            cat_type = "one_time"
        else:
            cat_type = "flexible"

        profiles[cat] = {
            "type": cat_type,
            "monthly_mean": round(mean_val, 2),
            "monthly_std": round(std_val, 2),
            "monthly_median": round(median_val, 2),
            "cv": round(cv, 4),
            "appearance_rate": round(appearance_rate, 2),
            "p25": round(p25, 2),
            "p50": round(p50, 2),
            "p75": round(p75, 2),
            "last_months": [round(v, 2) for v in last_n],
            "months_present": n_present,
        }

    return profiles


# ── 2. Overall Spending Velocity Curve ─────────────────────────────────

def compute_velocity_curve(conn, n_months: int = None) -> dict:
    """
    Compute the user's typical daily cumulative spending pattern
    as a percentage of the month's total, averaged over n_months.
    Returns avg_velocity[day] and std_velocity[day] arrays (1-indexed by day).
    """
    n_months = n_months or cfg.VELOCITY_LOOKBACK_MONTHS
    ref = _get_reference_date(conn)
    start = _months_back(ref, n_months)
    current_month_start = ref.replace(day=1)
    excluded = _excluded_categories()
    excl_list = ",".join(f"'{c}'" for c in excluded)

    rows = conn.execute(f"""
        SELECT date, ABS(amount) as amt,
               CAST(strftime('%d', date) AS INTEGER) as day_of_month,
               strftime('%Y-%m', date) as month_key
        FROM transactions
        WHERE date >= ? AND date < ? AND amount < 0
              AND category NOT IN ({excl_list})
        ORDER BY date
    """, (start.isoformat(), current_month_start.isoformat())).fetchall()

    # Build daily cumulative per month
    month_days = defaultdict(lambda: defaultdict(float))
    month_totals = defaultdict(float)
    for r in rows:
        mk = r["month_key"]
        day = r["day_of_month"]
        month_days[mk][day] += r["amt"]
        month_totals[mk] += r["amt"]

    # Convert to cumulative percentages
    velocity_by_day = defaultdict(list)  # day -> list of pct values across months
    for mk, daily_spend in month_days.items():
        total = month_totals[mk]
        if total <= 0:
            continue
        # Parse month to get days_in_month
        y, m = int(mk[:4]), int(mk[5:7])
        dim = monthrange(y, m)[1]

        cumulative = 0.0
        for day in range(1, dim + 1):
            cumulative += daily_spend.get(day, 0)
            velocity_by_day[day].append(cumulative / total)

    # Average and std across months
    max_day = 31
    avg_velocity = {}
    std_velocity = {}
    for day in range(1, max_day + 1):
        vals = velocity_by_day.get(day, [])
        if vals:
            avg_velocity[day] = float(np.mean(vals))
            std_velocity[day] = float(np.std(vals)) if len(vals) > 1 else 0.05
        else:
            # Interpolate linearly for missing days
            avg_velocity[day] = day / max_day
            std_velocity[day] = 0.05

    return {
        "avg_velocity": avg_velocity,
        "std_velocity": std_velocity,
        "months_analyzed": len(month_totals),
    }


# ── 3. Category-Level Velocity Curves ─────────────────────────────────

def compute_category_velocities(conn, n_months: int = None) -> dict:
    """
    Per-category daily velocity curves for flexible categories.
    Returns dict of category -> {avg_velocity, typical_total}.
    """
    n_months = n_months or cfg.VELOCITY_LOOKBACK_MONTHS
    ref = _get_reference_date(conn)
    start = _months_back(ref, n_months)
    current_month_start = ref.replace(day=1)
    excluded = _excluded_categories()

    rows = conn.execute("""
        SELECT category, date, ABS(amount) as amt,
               CAST(strftime('%d', date) AS INTEGER) as day_of_month,
               strftime('%Y-%m', date) as month_key
        FROM transactions
        WHERE date >= ? AND date < ? AND amount < 0
        ORDER BY category, date
    """, (start.isoformat(), current_month_start.isoformat())).fetchall()

    # Group by category -> month -> day
    cat_month_days = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    cat_month_totals = defaultdict(lambda: defaultdict(float))

    for r in rows:
        cat = r["category"]
        if cat in excluded:
            continue
        mk = r["month_key"]
        day = r["day_of_month"]
        cat_month_days[cat][mk][day] += r["amt"]
        cat_month_totals[cat][mk] += r["amt"]

    result = {}
    for cat, month_data in cat_month_days.items():
        velocity_by_day = defaultdict(list)
        monthly_totals = []

        for mk, daily_spend in month_data.items():
            total = cat_month_totals[cat][mk]
            if total <= 0:
                continue
            monthly_totals.append(total)
            y, m = int(mk[:4]), int(mk[5:7])
            dim = monthrange(y, m)[1]
            cumulative = 0.0
            for day in range(1, dim + 1):
                cumulative += daily_spend.get(day, 0)
                velocity_by_day[day].append(cumulative / total)

        avg_velocity = {}
        for day in range(1, 32):
            vals = velocity_by_day.get(day, [])
            avg_velocity[day] = float(np.mean(vals)) if vals else day / 31.0

        result[cat] = {
            "avg_velocity": avg_velocity,
            "typical_total": float(np.mean(monthly_totals)) if monthly_totals else 0,
        }

    return result


# ── 4. Anomaly Detection ──────────────────────────────────────────────

def detect_anomalies(category_profiles: dict, current_month_totals: dict) -> dict:
    """
    Flag categories where current month spending is statistically unusual.
    Returns dict of category -> {z_score, flag, current, expected}.
    """
    anomalies = {}
    for cat, profile in category_profiles.items():
        current = current_month_totals.get(cat, 0)
        if current == 0:
            continue

        mean_val = profile["monthly_mean"]
        std_val = profile["monthly_std"]
        cat_type = profile["type"]

        # For one-time / low-data categories, use robust stats
        if cat_type == "one_time" or profile["months_present"] < 3:
            median_val = profile["monthly_median"]
            last = profile["last_months"]
            if len(last) >= 3:
                mad = float(np.median(np.abs(np.array(last) - median_val)))
                robust_std = mad * 1.4826  # scale to match normal std
                z = (current - median_val) / robust_std if robust_std > 0 else 0
            else:
                z = (current - mean_val) / std_val if std_val > 0 else 0
        else:
            z = (current - mean_val) / std_val if std_val > 0 else 0

        if z > cfg.ANOMALY_SPIKE_Z:
            flag = "spike"
        elif z > cfg.ANOMALY_ELEVATED_Z:
            flag = "elevated"
        elif z < -cfg.ANOMALY_ELEVATED_Z:
            flag = "low"
        else:
            flag = "normal"

        anomalies[cat] = {
            "z_score": round(z, 2),
            "flag": flag,
            "current": round(current, 2),
            "expected": round(mean_val, 2),
        }

    return anomalies


# ── 5. Guardrail Caps ─────────────────────────────────────────────────

def compute_guardrail_caps(category_profiles: dict) -> dict:
    """
    Compute suggested spending caps for flexible_recurring categories
    based on percentiles. Returns {category: {aggressive, moderate, gentle}}.
    """
    caps = {}
    for cat, profile in category_profiles.items():
        if profile["type"] not in ("flexible_recurring", "flexible"):
            continue

        caps[cat] = {
            "aggressive": cfg.round_to_cap(profile["p25"]),
            "moderate": cfg.round_to_cap(profile["p50"]),
            "gentle": cfg.round_to_cap(profile["p75"]),
        }

    return caps


# ── 6. Recovery Options ───────────────────────────────────────────────

def compute_recovery_options(deficit: float, category_profiles: dict) -> list:
    """
    Compute recovery pace options. Only returns options where the
    extra_per_month is <= MAX_FLEX_SQUEEZE_PCT of flex baseline.
    """
    if deficit <= 0:
        return []

    # Sum of medians for all flexible categories = flex baseline
    flex_baseline = sum(
        p["monthly_median"] for p in category_profiles.values()
        if p["type"] in ("flexible_recurring", "flexible")
    )
    max_squeeze = flex_baseline * cfg.MAX_FLEX_SQUEEZE_PCT

    options = []
    for months in cfg.RECOVERY_HORIZONS:
        extra = deficit / months
        feasible = extra <= max_squeeze
        options.append({
            "months": months,
            "extra_per_month": round(extra, 0),
            "new_flex_budget": round(flex_baseline - extra, 0),
            "feasible": feasible,
        })

    return options


# ── 7. Projected End-of-Month ─────────────────────────────────────────

def project_end_of_month(conn, selected_month: str,
                         category_velocities: dict,
                         category_profiles: dict) -> dict:
    """
    Project end-of-month spend per category using velocity curves.
    """
    ref = _get_reference_date(conn)
    y, m = int(selected_month[:4]), int(selected_month[5:7])
    dim = monthrange(y, m)[1]
    day_of_month = ref.day if ref.year == y and ref.month == m else dim

    # Current month actuals by category
    current_totals = _get_current_month_totals(conn, selected_month)

    breakdown = {}
    total_projected = 0.0

    for cat, spent in current_totals.items():
        vel = category_velocities.get(cat, {})
        avg_vel = vel.get("avg_velocity", {})
        typical_pct = avg_vel.get(day_of_month, day_of_month / dim)
        typical_total = vel.get("typical_total", spent)

        if typical_pct > 0.05:
            projected = spent / typical_pct
        else:
            projected = spent  # too early, use actual

        # Blend with historical if early in month
        if day_of_month <= 7 and typical_total > 0:
            weight = day_of_month / 7.0
            projected = weight * projected + (1 - weight) * typical_total

        breakdown[cat] = {
            "current": round(spent, 2),
            "projected": round(projected, 2),
            "typical": round(typical_total, 2),
        }
        total_projected += projected

    return {
        "total_projected": round(total_projected, 2),
        "day_of_month": day_of_month,
        "days_in_month": dim,
        "breakdown": breakdown,
    }


# ── 8. Pace Check ────────────────────────────────────────────────────

def compute_pace_check(conn, selected_month: str,
                       velocity_curves: dict,
                       category_velocities: dict,
                       category_profiles: dict) -> dict:
    """
    Compute pace check data: overall pace vs typical, per-category alerts.
    """
    ref = _get_reference_date(conn)
    y, m = int(selected_month[:4]), int(selected_month[5:7])
    dim = monthrange(y, m)[1]
    day_of_month = ref.day if ref.year == y and ref.month == m else dim
    excluded = _excluded_categories()

    # Current month total spend
    current_totals = _get_current_month_totals(conn, selected_month)
    total_spent = sum(current_totals.values())

    # Get current month daily cumulative for the chart
    current_daily = _get_current_daily_cumulative(conn, selected_month, day_of_month)

    # Overall pace comparison
    avg_vel = velocity_curves.get("avg_velocity", {})
    expected_pct = avg_vel.get(day_of_month, day_of_month / dim)

    # Category-level pace alerts
    hot = []
    warm = []
    on_track = []

    for cat, spent in current_totals.items():
        if cat in excluded:
            continue
        profile = category_profiles.get(cat, {})
        if profile.get("type") in ("fixed", "one_time"):
            continue

        cat_vel = category_velocities.get(cat, {})
        cat_avg_vel = cat_vel.get("avg_velocity", {})
        typical_total = cat_vel.get("typical_total", 0)
        expected_cat_pct = cat_avg_vel.get(day_of_month, day_of_month / dim)

        if typical_total <= 0:
            continue

        actual_pct = spent / typical_total if typical_total > 0 else 0
        pace_delta = actual_pct - expected_cat_pct
        expected_amount = expected_cat_pct * typical_total

        entry = {
            "category": cat,
            "spent": round(spent, 2),
            "typical_total": round(typical_total, 2),
            "expected_at_day": round(expected_amount, 2),
            "actual_pct": round(actual_pct, 4),
            "expected_pct": round(expected_cat_pct, 4),
            "pace_delta": round(pace_delta, 4),
        }

        if pace_delta > cfg.PACE_HOT_THRESHOLD:
            hot.append(entry)
        elif pace_delta > cfg.PACE_WARM_THRESHOLD:
            warm.append(entry)
        else:
            on_track.append(entry)

    # Sort hot/warm by pace_delta descending
    hot.sort(key=lambda x: x["pace_delta"], reverse=True)
    warm.sort(key=lambda x: x["pace_delta"], reverse=True)

    return {
        "day_of_month": day_of_month,
        "days_in_month": dim,
        "total_spent": round(total_spent, 2),
        "expected_pct": round(expected_pct, 4),
        "current_daily_cumulative": current_daily,
        "hot_categories": hot,
        "warm_categories": warm,
        "on_track_categories": on_track,
    }


# ── 9. Top-Level Orchestrator ─────────────────────────────────────────

def get_coach_data(conn, selected_month: str) -> dict:
    """
    Compute all stats needed for the budget coach.
    Caller should cache this in session state.
    """
    category_profiles = classify_categories(conn)
    velocity_curves = compute_velocity_curve(conn)
    category_velocities = compute_category_velocities(conn)

    # Current month totals
    current_totals = _get_current_month_totals(conn, selected_month)

    # Anomaly detection
    anomaly_flags = detect_anomalies(category_profiles, current_totals)

    # Guardrail caps
    guardrail_caps = compute_guardrail_caps(category_profiles)

    # End-of-month projection
    eom_projection = project_end_of_month(
        conn, selected_month, category_velocities, category_profiles)

    # Pace check
    pace_check = compute_pace_check(
        conn, selected_month, velocity_curves,
        category_velocities, category_profiles)

    # Fixed costs total (auto-detected)
    fixed_total = sum(
        p["monthly_mean"] for p in category_profiles.values()
        if p["type"] == "fixed"
    )
    fixed_categories = [
        cat for cat, p in category_profiles.items() if p["type"] == "fixed"
    ]

    return {
        "category_profiles": category_profiles,
        "velocity_curves": velocity_curves,
        "category_velocities": category_velocities,
        "current_totals": current_totals,
        "anomaly_flags": anomaly_flags,
        "guardrail_caps": guardrail_caps,
        "eom_projection": eom_projection,
        "pace_check": pace_check,
        "fixed_total": round(fixed_total, 2),
        "fixed_categories": fixed_categories,
    }


# ── Internal Helpers ──────────────────────────────────────────────────

def _get_current_month_totals(conn, selected_month: str) -> dict:
    """Get total spend per category for the selected month."""
    rows = conn.execute("""
        SELECT category, SUM(ABS(amount)) as total
        FROM transactions
        WHERE strftime('%Y-%m', date) = ? AND amount < 0
        GROUP BY category
    """, (selected_month,)).fetchall()

    excluded = _excluded_categories()
    return {r["category"]: r["total"] for r in rows if r["category"] not in excluded}


def _get_current_daily_cumulative(conn, selected_month: str,
                                   up_to_day: int) -> list:
    """Get daily cumulative spend for current month (for the velocity chart)."""
    rows = conn.execute("""
        SELECT CAST(strftime('%d', date) AS INTEGER) as day_of_month,
               SUM(ABS(amount)) as daily_total
        FROM transactions
        WHERE strftime('%Y-%m', date) = ? AND amount < 0
              AND category NOT IN ('Transfers & Payments', 'Income & Refunds', 'Debt Payments')
        GROUP BY day_of_month
        ORDER BY day_of_month
    """, (selected_month,)).fetchall()

    daily = defaultdict(float)
    for r in rows:
        daily[r["day_of_month"]] = r["daily_total"]

    cumulative = []
    running = 0.0
    for day in range(1, up_to_day + 1):
        running += daily.get(day, 0)
        cumulative.append(round(running, 2))

    return cumulative


def get_last_month_anomalies(conn, category_profiles: dict) -> dict:
    """Get anomaly flags for LAST month (used in Game Plan watch list)."""
    ref = _get_reference_date(conn)
    last_month = _months_back(ref, 1)
    last_month_key = _month_key(last_month)

    last_month_totals = _get_current_month_totals(conn, last_month_key)
    return detect_anomalies(category_profiles, last_month_totals)
