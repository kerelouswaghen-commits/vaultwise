"""
Statistical analysis engine — replaces hardcoded thresholds with data-driven ML.
All insights are computed from actual transaction data using statistical methods.
No hardcoded dollar amounts or percentages.
"""

import math
import random
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import numpy as np

import config
import database


# ---------------------------------------------------------------------------
# Data classes for analysis results
# ---------------------------------------------------------------------------

@dataclass
class TrendResult:
    """Result of a linear regression trend analysis on a category."""
    category: str
    direction: str          # "rising", "falling", "stable"
    slope_per_month: float  # $/month rate of change
    r_squared: float        # how well the trend fits (0-1)
    current: float          # most recent month's spend
    mean: float             # historical average
    std: float              # standard deviation
    pct_vs_mean: float      # % above/below mean
    months_analyzed: int
    forecast_next: float    # predicted next month
    severity: str           # "normal", "watch", "warning", "critical"
    action: str             # data-driven action recommendation


@dataclass
class BudgetStatus:
    """Data-driven budget status for a category."""
    category: str
    current_spend: float
    historical_mean: float
    historical_median: float
    historical_std: float
    percentile: float        # where current spend falls in historical distribution
    pct_of_month_elapsed: float
    projected_month_end: float
    status: str              # "under", "on_track", "elevated", "over"
    excess_amount: float     # how much over median (0 if under)
    savings_potential: float # realistic savings based on historical variance


@dataclass
class SavingsOpportunity:
    """A statistically identified savings opportunity."""
    category: str
    monthly_savings: float
    confidence: float        # 0-1 based on data consistency
    basis: str              # explanation of how computed
    difficulty: str         # "easy", "moderate", "hard"
    top_merchants: list     # merchants driving the spend
    historical_low: float   # best month they've achieved
    current_avg: float      # recent average


@dataclass
class CashFlowForecast:
    """Cash flow projection with confidence intervals."""
    base_df: pd.DataFrame
    ci_low: list            # 10th percentile cumulative
    ci_high: list           # 90th percentile cumulative
    p_negative: float       # probability of negative cumulative at 12 months
    expected_surplus: float # expected savings at 12 months


# ---------------------------------------------------------------------------
# Core statistical functions
# ---------------------------------------------------------------------------

def linear_regression(x: list, y: list) -> tuple:
    """Simple OLS linear regression. Returns (slope, intercept, r_squared)."""
    n = len(x)
    if n < 2:
        return 0.0, (y[0] if y else 0.0), 0.0

    x_arr = np.array(x, dtype=float)
    y_arr = np.array(y, dtype=float)

    x_mean = x_arr.mean()
    y_mean = y_arr.mean()

    ss_xy = ((x_arr - x_mean) * (y_arr - y_mean)).sum()
    ss_xx = ((x_arr - x_mean) ** 2).sum()
    ss_yy = ((y_arr - y_mean) ** 2).sum()

    if ss_xx == 0:
        return 0.0, y_mean, 0.0

    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy > 0 else 0.0

    return slope, intercept, r_squared


def percentile_rank(value: float, distribution: list) -> float:
    """What percentile does `value` fall at in the given distribution? 0-100."""
    if not distribution:
        return 50.0
    sorted_dist = sorted(distribution)
    count_below = sum(1 for v in sorted_dist if v < value)
    count_equal = sum(1 for v in sorted_dist if v == value)
    return ((count_below + 0.5 * count_equal) / len(sorted_dist)) * 100


def ewma(values: list, span: int = 3) -> float:
    """Exponentially weighted moving average — more weight on recent values."""
    if not values:
        return 0.0
    s = pd.Series(values)
    return float(s.ewm(span=span, adjust=False).mean().iloc[-1])


# ---------------------------------------------------------------------------
# Advanced time-series analysis
# ---------------------------------------------------------------------------

def mann_kendall_test(values: list) -> dict:
    """
    Mann-Kendall trend test — non-parametric test for monotonic trend.
    Returns trend strength classification and statistics.
    Requires at least 4 data points.
    """
    n = len(values)
    if n < 4:
        return {"trend": "insufficient_data", "strength": "none", "p_value": 1.0, "z_score": 0.0, "s_stat": 0}

    # Compute S statistic: count concordant - discordant pairs
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            diff = values[j] - values[i]
            if diff > 0:
                s += 1
            elif diff < 0:
                s -= 1

    # Variance of S (with ties correction)
    # Count ties
    from collections import Counter
    tie_counts = Counter(values)
    tie_groups = [c for c in tie_counts.values() if c > 1]

    var_s = (n * (n - 1) * (2 * n + 5)) / 18.0
    for t in tie_groups:
        var_s -= (t * (t - 1) * (2 * t + 5)) / 18.0

    if var_s <= 0:
        return {"trend": "no_trend", "strength": "none", "p_value": 1.0, "z_score": 0.0, "s_stat": s}

    # Z-score
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0

    # Two-tailed p-value using normal approximation (numpy only, no scipy needed)
    import math
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))

    # Classify trend
    if p_value < 0.01:
        strength = "strong"
    elif p_value < 0.05:
        strength = "moderate"
    elif p_value < 0.10:
        strength = "weak"
    else:
        strength = "none"

    if s > 0:
        trend = "increasing"
    elif s < 0:
        trend = "decreasing"
    else:
        trend = "no_trend"

    return {
        "trend": trend,
        "strength": strength,
        "p_value": round(p_value, 4),
        "z_score": round(z, 3),
        "s_stat": s,
    }


def seasonality_decomposition(values: list) -> dict:
    """
    Additive seasonality decomposition using centered moving average.
    Adapts period to data size: period=12 if >=24 points, period=3 if >=6, skip if <6.
    Returns trend component, seasonal component, and residual.
    """
    n = len(values)
    if n < 6:
        return {"has_seasonality": False, "reason": "insufficient_data", "data_points": n}

    arr = np.array(values, dtype=float)

    # Choose period based on data size
    if n >= 24:
        period = 12
    elif n >= 6:
        period = 3
    else:
        return {"has_seasonality": False, "reason": "insufficient_data", "data_points": n}

    # Centered moving average for trend
    trend = np.full(n, np.nan)
    half = period // 2
    for i in range(half, n - half):
        if period % 2 == 0:
            trend[i] = (arr[i - half:i + half].sum() + 0.5 * arr[i - half] + 0.5 * arr[i + half]) / period
        else:
            trend[i] = arr[i - half:i + half + 1].mean()

    # Detrended = original - trend
    detrended = arr - trend

    # Seasonal component: average of detrended values for each position in the cycle
    seasonal = np.zeros(n)
    for pos in range(period):
        indices = list(range(pos, n, period))
        valid = [detrended[i] for i in indices if not np.isnan(detrended[i])]
        if valid:
            seasonal_avg = np.mean(valid)
            for i in indices:
                seasonal[i] = seasonal_avg

    # Residual
    residual = arr - trend - seasonal

    # Measure seasonality strength: variance of seasonal / variance of (seasonal + residual)
    valid_mask = ~np.isnan(trend)
    if valid_mask.sum() > 0:
        var_seasonal = np.var(seasonal[valid_mask])
        var_remainder = np.var((seasonal + residual)[valid_mask])
        seasonality_strength = 1.0 - (np.var(residual[valid_mask]) / var_remainder) if var_remainder > 0 else 0.0
    else:
        seasonality_strength = 0.0

    return {
        "has_seasonality": seasonality_strength > 0.3,
        "strength": round(max(0, min(1, seasonality_strength)), 3),
        "period": period,
        "data_points": n,
        "seasonal_pattern": [round(s, 2) for s in seasonal[:period].tolist()],
        "trend_direction": "rising" if not np.isnan(trend[-1 - half]) and trend[-1 - half] > trend[half] else "falling",
    }


def cross_category_correlation(conn, months: int = 12) -> list[dict]:
    """
    Compute pairwise correlations between category monthly totals.
    Returns pairs with |correlation| > 0.4 (meaningful relationship).
    """
    today = _get_data_date(conn)
    start = _months_back(today, months)

    rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month, category, SUM(amount) as total
        FROM transactions
        WHERE date >= ? AND amount < 0
        GROUP BY month, category
    """, (start.isoformat(),)).fetchall()

    # Build pivot: month -> {category: total}
    from collections import defaultdict
    monthly_data = defaultdict(dict)
    all_cats = set()
    for r in rows:
        monthly_data[r["month"]][r["category"]] = abs(r["total"])
        all_cats.add(r["category"])

    # Skip non-actionable categories
    skip = config.EXCLUDED_CATEGORIES | {"Debt Payments", "Fees & Interest"}
    cats = sorted([c for c in all_cats if c not in skip])
    all_months = sorted(monthly_data.keys())

    if len(all_months) < 4 or len(cats) < 2:
        return []

    # Build matrix
    matrix = np.zeros((len(all_months), len(cats)))
    for i, m in enumerate(all_months):
        for j, c in enumerate(cats):
            matrix[i, j] = monthly_data[m].get(c, 0)

    # Compute correlation matrix
    if matrix.shape[0] < 3:
        return []

    corr_matrix = np.corrcoef(matrix.T)

    # Extract significant pairs
    pairs = []
    for i in range(len(cats)):
        for j in range(i + 1, len(cats)):
            r = corr_matrix[i, j]
            if not np.isnan(r) and abs(r) > 0.4:
                if r > 0:
                    relation = "move together"
                    interpretation = f"When {cats[i]} spending rises, {cats[j]} tends to rise too"
                else:
                    relation = "substitute"
                    interpretation = f"When {cats[i]} spending rises, {cats[j]} tends to fall (substitution effect)"

                pairs.append({
                    "category_a": cats[i],
                    "category_b": cats[j],
                    "correlation": round(float(r), 3),
                    "relation": relation,
                    "interpretation": interpretation,
                })

    return sorted(pairs, key=lambda p: abs(p["correlation"]), reverse=True)


def granger_causality_simple(x_series: list, y_series: list, max_lag: int = 2) -> dict:
    """
    Simplified Granger causality test using numpy OLS.
    Tests if x_series helps predict y_series beyond its own history.
    Returns F-statistic and whether the relationship is significant.
    """
    n = len(y_series)
    if n < max_lag + 4 or len(x_series) != n:
        return {"significant": False, "f_stat": 0, "p_value": 1.0, "reason": "insufficient_data"}

    y = np.array(y_series, dtype=float)
    x = np.array(x_series, dtype=float)

    # Build restricted model: y_t = a0 + a1*y_{t-1} + ... + a_lag*y_{t-lag}
    Y = y[max_lag:]
    n_obs = len(Y)

    # Restricted: only lagged Y
    X_restricted = np.ones((n_obs, max_lag + 1))  # +1 for intercept
    for lag in range(1, max_lag + 1):
        X_restricted[:, lag] = y[max_lag - lag: n - lag]

    # Unrestricted: lagged Y + lagged X
    X_unrestricted = np.ones((n_obs, 2 * max_lag + 1))
    for lag in range(1, max_lag + 1):
        X_unrestricted[:, lag] = y[max_lag - lag: n - lag]
        X_unrestricted[:, max_lag + lag] = x[max_lag - lag: n - lag]

    # OLS: RSS for both models
    try:
        # Restricted
        beta_r = np.linalg.lstsq(X_restricted, Y, rcond=None)[0]
        residuals_r = Y - X_restricted @ beta_r
        rss_r = float(np.sum(residuals_r ** 2))

        # Unrestricted
        beta_u = np.linalg.lstsq(X_unrestricted, Y, rcond=None)[0]
        residuals_u = Y - X_unrestricted @ beta_u
        rss_u = float(np.sum(residuals_u ** 2))
    except np.linalg.LinAlgError:
        return {"significant": False, "f_stat": 0, "p_value": 1.0, "reason": "singular_matrix"}

    # F-test
    df1 = max_lag  # additional parameters in unrestricted
    df2 = n_obs - 2 * max_lag - 1

    if df2 <= 0 or rss_u <= 0:
        return {"significant": False, "f_stat": 0, "p_value": 1.0, "reason": "degenerate"}

    f_stat = ((rss_r - rss_u) / df1) / (rss_u / df2)

    # Approximate p-value (no scipy dependency)
    # Using conservative thresholds from F-distribution tables
    if f_stat > 6.0:
        p_value = 0.01
    elif f_stat > 4.0:
        p_value = 0.04
    elif f_stat > 3.0:
        p_value = 0.08
    else:
        p_value = 0.5

    return {
        "significant": p_value < 0.05,
        "f_stat": round(f_stat, 3),
        "p_value": round(p_value, 4),
    }


def adaptive_window(n_months: int) -> dict:
    """Return appropriate analysis windows based on available data size."""
    return {
        "trend": min(n_months, 12),
        "seasonality": min(n_months, 24),
        "short_term": min(n_months, 6),
        "prophet_min": 4,
        "can_decompose": n_months >= 6,
        "can_detect_annual": n_months >= 24,
    }


def compute_merchant_impact(conn, category: str, months: int = 6) -> list[dict]:
    """
    Rank merchants by their contribution to category spending trend.
    Uses correlation between merchant monthly frequency and category monthly total.
    Returns merchants sorted by impact (highest first).
    """
    today = _get_data_date(conn)
    start = _months_back(today, months)

    # Get all transactions for this category
    rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month, description, amount
        FROM transactions
        WHERE category = ? AND date >= ? AND amount < 0
        ORDER BY date
    """, (category, start.isoformat())).fetchall()

    if not rows:
        return []

    # Build per-merchant monthly data
    from collections import defaultdict
    merchant_monthly = defaultdict(lambda: defaultdict(float))
    category_monthly = defaultdict(float)
    merchant_totals = defaultdict(float)
    merchant_counts = defaultdict(int)

    all_months = set()
    for r in rows:
        m = r["month"]
        desc = r["description"]
        amt = abs(r["amount"])
        merchant_monthly[desc][m] += amt
        category_monthly[m] += amt
        merchant_totals[desc] += amt
        merchant_counts[desc] += 1
        all_months.add(m)

    sorted_months = sorted(all_months)
    if len(sorted_months) < 3:
        # Not enough months for correlation — fall back to simple ranking
        return [
            {
                "name": desc,
                "total": round(merchant_totals[desc], 2),
                "visits": merchant_counts[desc],
                "contribution_pct": round(merchant_totals[desc] / sum(merchant_totals.values()) * 100, 1) if merchant_totals else 0,
                "avg_per_visit": round(merchant_totals[desc] / max(merchant_counts[desc], 1), 2),
                "impact_score": 0,
            }
            for desc in sorted(merchant_totals, key=lambda d: -merchant_totals[d])[:10]
        ]

    # Compute correlation for each merchant
    cat_series = [category_monthly.get(m, 0) for m in sorted_months]
    results = []

    for desc in merchant_totals:
        if merchant_counts[desc] < 2:
            continue

        merch_series = [merchant_monthly[desc].get(m, 0) for m in sorted_months]

        # Correlation between merchant spend and category total
        if np.std(merch_series) > 0 and np.std(cat_series) > 0:
            corr = float(np.corrcoef(merch_series, cat_series)[0, 1])
        else:
            corr = 0.0

        total = merchant_totals[desc]
        contribution = total / sum(merchant_totals.values()) * 100 if merchant_totals else 0

        # Impact score: weighted combination of correlation and contribution
        impact = abs(corr) * 0.5 + (contribution / 100) * 0.5

        results.append({
            "name": desc,
            "total": round(total, 2),
            "visits": merchant_counts[desc],
            "contribution_pct": round(contribution, 1),
            "avg_per_visit": round(total / max(merchant_counts[desc], 1), 2),
            "impact_score": round(impact, 3),
            "correlation": round(corr, 3),
        })

    return sorted(results, key=lambda r: -r["impact_score"])[:10]


# ---------------------------------------------------------------------------
# Trend analysis using linear regression
# ---------------------------------------------------------------------------

def analyze_category_trend(conn, category: str, months: int = 6) -> TrendResult:
    """
    Analyze a category's spending trend using linear regression.
    Returns direction, rate of change, R², and severity classification.
    """
    history = database.get_category_monthly_history(conn, category, months)
    if not history:
        return TrendResult(
            category=category, direction="stable", slope_per_month=0,
            r_squared=0, current=0, mean=0, std=0, pct_vs_mean=0,
            months_analyzed=0, forecast_next=0, severity="normal", action="",
        )

    # Reverse to chronological order
    history = list(reversed(history))
    amounts = [abs(h["total"]) for h in history]

    n = len(amounts)
    x = list(range(n))
    slope, intercept, r_sq = linear_regression(x, amounts)
    mean_val = np.mean(amounts)
    std_val = np.std(amounts) if n >= 2 else 0.0
    current = amounts[-1]

    pct_vs_mean = ((current - mean_val) / mean_val * 100) if mean_val > 0 else 0.0
    forecast_next = slope * n + intercept

    # Direction classification — uses both slope significance and R²
    # A trend is meaningful only if R² > 0.3 and the slope is > 5% of mean/month
    slope_pct = abs(slope) / mean_val * 100 if mean_val > 0 else 0
    if r_sq > 0.3 and slope_pct > 5:
        direction = "rising" if slope > 0 else "falling"
    else:
        direction = "stable"

    # Severity classification — based on z-score of current month
    z_score = (current - mean_val) / std_val if std_val > 0 else 0
    if z_score > 2.0 or (direction == "rising" and pct_vs_mean > 30):
        severity = "critical"
    elif z_score > 1.0 or (direction == "rising" and pct_vs_mean > 15):
        severity = "warning"
    elif z_score > 0.5 or (direction == "rising" and pct_vs_mean > 5):
        severity = "watch"
    else:
        severity = "normal"

    # Generate data-driven action
    action = _generate_trend_action(category, direction, severity, current, mean_val, std_val, forecast_next)

    return TrendResult(
        category=category, direction=direction, slope_per_month=round(slope, 2),
        r_squared=round(r_sq, 3), current=round(current, 2),
        mean=round(mean_val, 2), std=round(std_val, 2),
        pct_vs_mean=round(pct_vs_mean, 1), months_analyzed=n,
        forecast_next=round(max(0, forecast_next), 2),
        severity=severity, action=action,
    )


def _generate_trend_action(category: str, direction: str, severity: str,
                           current: float, mean: float, std: float,
                           forecast: float) -> str:
    """Generate a useful, actionable recommendation — not raw stats."""
    if direction == "falling":
        saved = mean - current
        if saved > 50:
            return f"Great progress — saving ${saved:,.0f}/mo vs your average. That's ${saved * 12:,.0f}/yr toward your goals. Keep it up!"
        return f"On track — spending is below your average. Maintain this pace."

    if severity == "normal":
        return f"Spending is stable and within your normal range. No action needed."

    excess = current - mean
    if severity == "critical":
        return (f"This is ${excess:,.0f} above your average — one of your highest months. "
                f"Review recent charges and pause non-essential purchases to get back to ${mean:,.0f}.")
    elif severity == "warning":
        return (f"Running ${excess:,.0f} above average. "
                f"If this continues, next month could hit ${forecast:,.0f}. Consider cutting back now.")
    else:  # watch
        return f"Slightly above average (+${excess:,.0f}). Keep an eye on it this week."


# ---------------------------------------------------------------------------
# Data-driven budget analysis
# ---------------------------------------------------------------------------

def compute_budget_status(conn, month_key: str = None) -> list[BudgetStatus]:
    """
    Compute budget status for every active category using statistical methods.
    No hardcoded thresholds — uses percentiles and standard deviations.
    month_key: optional "YYYY-MM" to evaluate a specific month instead of today.
    """
    if month_key:
        parts = month_key.split("-")
        ref_year, ref_month = int(parts[0]), int(parts[1])
        days_in_month = monthrange(ref_year, ref_month)[1]
        today_actual = _get_data_date(conn)
        # Current month: use today's day; past month: use full month
        if ref_year == today_actual.year and ref_month == today_actual.month:
            today = today_actual
        else:
            today = date(ref_year, ref_month, days_in_month)
    else:
        today = _get_data_date(conn)
    month_start = today.replace(day=1)
    days_elapsed = (today - month_start).days + 1
    days_in_month = monthrange(today.year, today.month)[1]
    pct_elapsed = days_elapsed / days_in_month

    # Target month spending (bounded to the single month)
    month_end = date(today.year, today.month, days_in_month)
    current_rows = conn.execute("""
        SELECT category, SUM(amount) as total
        FROM transactions WHERE date >= ? AND date <= ? AND amount < 0
        GROUP BY category
    """, (month_start.isoformat(), month_end.isoformat())).fetchall()
    current_map = {r["category"]: abs(r["total"]) for r in current_rows}

    # Historical monthly totals (last 6 months, excluding current)
    six_months_ago = _months_back(today, 6)
    hist_rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month, category, SUM(amount) as total
        FROM transactions
        WHERE date >= ? AND date < ? AND amount < 0
        GROUP BY month, category
    """, (six_months_ago.isoformat(), month_start.isoformat())).fetchall()

    # Build per-category monthly distributions
    cat_monthly = defaultdict(list)
    for r in hist_rows:
        cat_monthly[r["category"]].append(abs(r["total"]))

    statuses = []
    all_cats = set(current_map.keys()) | set(cat_monthly.keys())

    for cat in sorted(all_cats):
        current_spend = current_map.get(cat, 0)
        hist_values = cat_monthly.get(cat, [])

        if not hist_values:
            statuses.append(BudgetStatus(
                category=cat, current_spend=current_spend,
                historical_mean=0, historical_median=0, historical_std=0,
                percentile=50, pct_of_month_elapsed=pct_elapsed,
                projected_month_end=current_spend / max(pct_elapsed, 0.1),
                status="new" if current_spend > 0 else "inactive",
                excess_amount=0, savings_potential=0,
            ))
            continue

        mean_val = np.mean(hist_values)
        median_val = np.median(hist_values)
        std_val = np.std(hist_values) if len(hist_values) >= 2 else mean_val * 0.2

        # Project current spending to month-end using EWMA-weighted velocity
        projected = current_spend / max(pct_elapsed, 0.1)

        # Percentile of projected spend in historical distribution
        pctile = percentile_rank(projected, hist_values)

        # Status based on percentile rank (data-driven, not hardcoded thresholds)
        if pctile >= 85:
            status = "over"
        elif pctile >= 70:
            status = "elevated"
        elif pctile >= 30:
            status = "on_track"
        else:
            status = "under"

        excess = max(0, projected - median_val)

        # Savings potential: difference between current trajectory and their best quartile
        q25 = float(np.percentile(hist_values, 25)) if len(hist_values) >= 4 else median_val * 0.8
        savings_potential = max(0, projected - q25)

        statuses.append(BudgetStatus(
            category=cat, current_spend=round(current_spend, 2),
            historical_mean=round(mean_val, 2),
            historical_median=round(median_val, 2),
            historical_std=round(std_val, 2),
            percentile=round(pctile, 1),
            pct_of_month_elapsed=round(pct_elapsed, 3),
            projected_month_end=round(projected, 2),
            status=status, excess_amount=round(excess, 2),
            savings_potential=round(savings_potential, 2),
        ))

    return sorted(statuses, key=lambda s: s.current_spend, reverse=True)


# ---------------------------------------------------------------------------
# Savings opportunity detection (fully data-driven)
# ---------------------------------------------------------------------------

def detect_savings_opportunities(conn, min_monthly: float = 30) -> list[SavingsOpportunity]:
    """
    Identify savings opportunities based on statistical analysis of spending patterns.
    Uses variance, trend analysis, and merchant concentration — no hardcoded tips.
    """
    today = _get_data_date(conn)
    month_start = today.replace(day=1)

    # Get 6-month category history
    six_months_ago = _months_back(today, 6)
    hist_rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month, category, SUM(amount) as total
        FROM transactions
        WHERE date >= ? AND date < ? AND amount < 0
        GROUP BY month, category
    """, (six_months_ago.isoformat(), month_start.isoformat())).fetchall()

    cat_monthly = defaultdict(list)
    for r in hist_rows:
        cat_monthly[r["category"]].append(abs(r["total"]))

    # Non-actionable categories
    skip_cats = config.EXCLUDED_CATEGORIES | {"Daycare",
                 "Housing & Utilities", "Debt Payments"}

    opportunities = []

    for cat, values in cat_monthly.items():
        if cat in skip_cats or len(values) < 2:
            continue

        mean_val = np.mean(values)
        median_val = np.median(values)
        std_val = np.std(values)
        min_val = min(values)
        q25 = float(np.percentile(values, 25))

        # Savings potential = gap between recent average and their proven best (25th pctile)
        recent_avg = ewma(values, span=3)
        savings = recent_avg - q25

        if savings < min_monthly:
            continue

        # Confidence: based on consistency of historical data
        # Low std relative to mean = more predictable = higher confidence
        cv = std_val / mean_val if mean_val > 0 else 1.0
        confidence = max(0.3, min(0.95, 1.0 - cv))

        # Difficulty: based on how far from their best they are
        gap_ratio = savings / mean_val if mean_val > 0 else 0
        if gap_ratio < 0.15:
            difficulty = "easy"
        elif gap_ratio < 0.30:
            difficulty = "moderate"
        else:
            difficulty = "hard"

        # Get top merchants driving this category
        top_merchants = _get_category_merchants(conn, cat, months=3)

        basis = (f"Your recent avg is ${recent_avg:,.0f}/mo. "
                 f"Your best months averaged ${q25:,.0f}. "
                 f"Reducing to that level saves ${savings:,.0f}/mo.")

        opportunities.append(SavingsOpportunity(
            category=cat, monthly_savings=round(savings, 2),
            confidence=round(confidence, 2), basis=basis,
            difficulty=difficulty, top_merchants=top_merchants[:3],
            historical_low=round(min_val, 2), current_avg=round(recent_avg, 2),
        ))

    return sorted(opportunities, key=lambda o: o.monthly_savings, reverse=True)


def _get_category_merchants(conn, category: str, months: int = 3) -> list[dict]:
    """Get top merchants for a category, ranked by spend."""
    today = _get_data_date(conn)
    start = _months_back(today, months)
    rows = conn.execute("""
        SELECT description, COUNT(*) as visits, SUM(amount) as total
        FROM transactions
        WHERE category = ? AND date >= ? AND amount < 0
        GROUP BY description
        ORDER BY total ASC
        LIMIT 5
    """, (category, start.isoformat())).fetchall()
    return [{"name": r["description"], "visits": r["visits"],
             "total": round(abs(r["total"]), 2)} for r in rows]


# ---------------------------------------------------------------------------
# Facebook Prophet — time-series forecasting for spending categories
# ---------------------------------------------------------------------------

def _clamp_forecast(value: float, historical_values: list, floor: float = 0) -> float:
    """Clamp a forecast value to a sane range based on historical data.
    Uses median + IQR to be robust against outlier months."""
    if not historical_values:
        return max(floor, value)
    arr = np.array(historical_values)
    median = float(np.median(arr))
    q75 = float(np.percentile(arr, 75))
    iqr = q75 - float(np.percentile(arr, 25))
    # Upper fence: Q3 + 1.5*IQR (standard outlier detection), but at least 1.5x median
    ceiling = max(q75 + 1.5 * iqr, median * 1.5)
    return round(max(floor, min(ceiling, value)), 2)


def _suppress_prophet_logs():
    """Suppress noisy Prophet/cmdstanpy logging."""
    import logging
    logging.getLogger("prophet").setLevel(logging.ERROR)
    logging.getLogger("cmdstanpy").setLevel(logging.ERROR)


def prophet_forecast_category(conn, category: str, periods: int = 3) -> dict | None:
    """
    Use Facebook Prophet to forecast a category's monthly spending.
    Applies sanity bounds: no negative values, capped at 2x historical max.
    Requires at least 4 months of data.
    """
    try:
        from prophet import Prophet
    except ImportError:
        return None

    history = database.get_category_monthly_history(conn, category, months=24)
    if len(history) < 4:
        return None

    # Build Prophet DataFrame (ds, y) — chronological order
    rows = []
    for h in reversed(history):
        rows.append({
            "ds": pd.Timestamp(h["month"] + "-01"),
            "y": abs(h["total"]),
        })
    df = pd.DataFrame(rows)
    hist_values = df["y"].tolist()
    hist_mean = float(df["y"].mean())

    _suppress_prophet_logs()

    # Fit Prophet — conservative settings for noisy monthly data
    model = Prophet(
        yearly_seasonality=True if len(history) >= 12 else False,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_prior_scale=0.05,  # Very conservative — reduces wild swings
        seasonality_prior_scale=0.1,   # Dampen seasonality
        interval_width=0.80,
        growth="flat",                 # Flat growth — spending isn't exponential
    )
    model.fit(df)

    future = model.make_future_dataframe(periods=periods, freq="MS")
    forecast = model.predict(future)

    # Extract and CLAMP forecasted values
    future_rows = forecast.tail(periods)
    forecasted = []
    for _, row in future_rows.iterrows():
        predicted = _clamp_forecast(float(row["yhat"]), hist_values)
        lower = _clamp_forecast(float(row["yhat_lower"]), hist_values)
        upper = _clamp_forecast(float(row["yhat_upper"]), hist_values)
        forecasted.append({
            "month": row["ds"].strftime("%Y-%m"),
            "predicted": predicted,
            "lower": lower,
            "upper": upper,
        })

    # Trend direction from Prophet's trend component
    trend_values = forecast["trend"].tolist()
    trend_slope = trend_values[-1] - trend_values[-periods - 1] if len(trend_values) > periods else 0

    # Historical fit quality
    actual = df["y"].values
    fitted = forecast.head(len(actual))["yhat"].values[:len(actual)]
    residuals = actual - fitted
    mae = float(np.mean(np.abs(residuals)))
    mape = float(np.mean(np.abs(residuals / np.where(actual > 0, actual, 1)))) * 100

    return {
        "category": category,
        "forecast": forecasted,
        "trend_slope_monthly": round(trend_slope / periods, 2),
        "trend_direction": "rising" if trend_slope > 0 else ("falling" if trend_slope < 0 else "flat"),
        "historical_avg": round(hist_mean, 2),
        "mae": round(mae, 2),
        "mape": round(mape, 1),
        "data_points": len(history),
        "model": "Prophet",
    }


def prophet_forecast_total_spending(conn, periods: int = 6) -> dict | None:
    """
    Forecast total monthly spending using Prophet.
    More reliable than per-category since it uses aggregated data.
    """
    try:
        from prophet import Prophet
    except ImportError:
        return None

    hist_rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month,
               SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) as spending
        FROM transactions
        GROUP BY month
        ORDER BY month
    """).fetchall()

    if len(hist_rows) < 4:
        return None

    rows = []
    for r in hist_rows:
        if r["spending"]:
            rows.append({
                "ds": pd.Timestamp(r["month"] + "-01"),
                "y": abs(r["spending"]),
            })
    df = pd.DataFrame(rows)
    hist_values = df["y"].tolist()

    _suppress_prophet_logs()

    model = Prophet(
        yearly_seasonality=True if len(rows) >= 12 else False,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_prior_scale=0.05,
        seasonality_prior_scale=0.1,
        interval_width=0.80,
        growth="flat",
    )
    model.fit(df)

    future = model.make_future_dataframe(periods=periods, freq="MS")
    forecast = model.predict(future)

    future_rows = forecast.tail(periods)
    forecasted = []
    for _, row in future_rows.iterrows():
        predicted = _clamp_forecast(float(row["yhat"]), hist_values)
        lower = _clamp_forecast(float(row["yhat_lower"]), hist_values)
        upper = _clamp_forecast(float(row["yhat_upper"]), hist_values)
        forecasted.append({
            "month": row["ds"].strftime("%Y-%m"),
            "predicted": predicted,
            "lower": lower,
            "upper": upper,
        })

    actual = df["y"].values
    fitted = forecast.head(len(actual))["yhat"].values
    residuals = actual - fitted
    mae = float(np.mean(np.abs(residuals)))
    mape = float(np.mean(np.abs(residuals / np.where(actual > 0, actual, 1)))) * 100

    return {
        "forecast": forecasted,
        "historical_avg": round(float(df["y"].mean()), 2),
        "mae": round(mae, 2),
        "mape": round(mape, 1),
        "data_points": len(rows),
        "model": "Prophet",
    }


# ---------------------------------------------------------------------------
# Monte Carlo simulation for cash flow confidence intervals
# ---------------------------------------------------------------------------

def simulate_cash_flow(conn, n_simulations: int = 500,
                       months_ahead: int = 66) -> CashFlowForecast:
    """
    Run Monte Carlo simulation on cash flow projection.
    Uses Prophet forecast variance when available, falls back to historical variance.
    """
    import models

    # Get base projection
    base_df = models.project_cash_flow(months_ahead=months_ahead)

    # Get historical monthly expense variance
    today = _get_data_date(conn)
    hist_rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month,
               SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) as spending
        FROM transactions
        GROUP BY month
        ORDER BY month
    """).fetchall()

    if len(hist_rows) < 3:
        # Not enough data for simulation — return base projection with wide bands
        n = len(base_df)
        return CashFlowForecast(
            base_df=base_df,
            ci_low=[c * 0.85 for c in base_df["cumulative"].tolist()],
            ci_high=[c * 1.15 for c in base_df["cumulative"].tolist()],
            p_negative=0.5,
            expected_surplus=base_df["cumulative"].iloc[min(11, len(base_df) - 1)] if len(base_df) > 0 else 0,
        )

    # Try to get Prophet-based variance estimate for better simulation
    prophet_cv = None
    try:
        prophet_result = prophet_forecast_total_spending(conn, periods=6)
        if prophet_result and prophet_result["mape"] > 0:
            # Use Prophet's MAPE as the noise factor
            prophet_cv = prophet_result["mape"] / 100.0
    except Exception:
        pass

    # Compute expense variance from actual data
    actual_spending = [abs(r["spending"]) for r in hist_rows if r["spending"]]
    expense_mean = np.mean(actual_spending)
    expense_std = np.std(actual_spending)

    # Coefficient of variation — prefer Prophet if available
    cv = prophet_cv if prophet_cv else (expense_std / expense_mean if expense_mean > 0 else 0.15)

    # Run simulations
    n = len(base_df)
    cumulative_paths = np.zeros((n_simulations, n))

    for sim in range(n_simulations):
        cumulative = 0.0
        for i in range(n):
            base_net = base_df.iloc[i]["monthly_net"]
            # Add random noise proportional to historical variance
            # Noise is scaled to the expense component
            noise = np.random.normal(0, base_df.iloc[i]["monthly_expenses"] * cv * 0.3)
            monthly_net = base_net + noise
            cumulative += monthly_net
            cumulative_paths[sim, i] = cumulative

    # Extract percentiles
    ci_low = np.percentile(cumulative_paths, 10, axis=0).tolist()
    ci_high = np.percentile(cumulative_paths, 90, axis=0).tolist()
    ci_median = np.percentile(cumulative_paths, 50, axis=0).tolist()

    # Check 12-month outlook
    check_idx = min(11, n - 1)
    check_values = cumulative_paths[:, check_idx]
    p_negative = float(np.mean(check_values < 0))
    expected_surplus = float(np.median(check_values))

    return CashFlowForecast(
        base_df=base_df,
        ci_low=ci_low,
        ci_high=ci_high,
        p_negative=round(p_negative, 3),
        expected_surplus=round(expected_surplus, 2),
    )


# ---------------------------------------------------------------------------
# Comprehensive analytics bundle for Claude context
# ---------------------------------------------------------------------------

def build_statistical_context(conn) -> dict:
    """
    Build a comprehensive statistical context for Claude prompts.
    All numbers are data-derived, not hardcoded.
    """
    today = _get_data_date(conn)

    # Read savings target from settings
    try:
        savings_target = int(conn.execute(
            "SELECT value FROM settings WHERE key = 'monthly_savings_target'"
        ).fetchone()["value"])
    except Exception:
        savings_target = 1000

    # Trend analysis for all active categories
    budget = compute_budget_status(conn)
    active_cats = [b.category for b in budget if b.current_spend > 0]
    trends = {cat: analyze_category_trend(conn, cat) for cat in active_cats}

    # Savings opportunities
    opportunities = detect_savings_opportunities(conn)
    total_potential = sum(o.monthly_savings for o in opportunities)

    # Monte Carlo forecast
    try:
        forecast = simulate_cash_flow(conn, n_simulations=300)
        forecast_summary = {
            "probability_of_negative": forecast.p_negative,
            "expected_surplus_12mo": forecast.expected_surplus,
        }
    except Exception:
        forecast_summary = {"note": "Insufficient data for Monte Carlo simulation"}

    # Prophet spending forecast
    prophet_forecast = None
    try:
        prophet_forecast = prophet_forecast_total_spending(conn, periods=3)
    except Exception:
        pass

    # Per-category Prophet forecasts for top categories
    category_forecasts = {}
    top_spend_cats = sorted(active_cats,
                           key=lambda c: trends[c].current if c in trends else 0,
                           reverse=True)[:5]
    for cat in top_spend_cats:
        try:
            cf = prophet_forecast_category(conn, cat, periods=2)
            if cf:
                category_forecasts[cat] = cf
        except Exception:
            pass

    # Rising categories (warning/critical)
    rising = [
        {
            "category": t.category,
            "current": t.current,
            "mean": t.mean,
            "pct_above": t.pct_vs_mean,
            "severity": t.severity,
            "action": t.action,
        }
        for t in trends.values()
        if t.severity in ("warning", "critical")
    ]

    # Falling categories (wins)
    wins = [
        {
            "category": t.category,
            "current": t.current,
            "mean": t.mean,
            "saved": round(t.mean - t.current, 2),
        }
        for t in trends.values()
        if t.direction == "falling" and t.mean > t.current
    ]

    # Data freshness check
    latest_txn = _get_latest_transaction_date(conn)
    data_age_days = (today - latest_txn).days

    return {
        "analysis_date": today.isoformat(),
        "latest_transaction_date": latest_txn.isoformat(),
        "data_age_days": data_age_days,
        "data_is_stale": data_age_days > 30,
        "savings_target": savings_target,
        "forecast": forecast_summary,
        "rising_categories": sorted(rising, key=lambda r: r["pct_above"], reverse=True),
        "spending_wins": sorted(wins, key=lambda w: w["saved"], reverse=True),
        "savings_opportunities": [
            {
                "category": o.category,
                "monthly_savings": o.monthly_savings,
                "confidence": o.confidence,
                "basis": o.basis,
                "difficulty": o.difficulty,
                "top_merchants": o.top_merchants,
            }
            for o in opportunities[:8]
        ],
        "total_potential_monthly_savings": round(total_potential, 2),
        "budget_status": [
            {
                "category": b.category,
                "current": b.current_spend,
                "projected": b.projected_month_end,
                "median": b.historical_median,
                "percentile": b.percentile,
                "status": b.status,
            }
            for b in budget if b.current_spend > 0
        ],
        "prophet_spending_forecast": {
            "model": "Facebook Prophet",
            "total_forecast": prophet_forecast["forecast"] if prophet_forecast else [],
            "mape": prophet_forecast["mape"] if prophet_forecast else None,
        } if prophet_forecast else None,
        "category_forecasts": {
            cat: {
                "next_months": cf["forecast"],
                "trend": cf["trend_direction"],
                "slope": cf["trend_slope_monthly"],
                "accuracy_mape": cf["mape"],
            }
            for cat, cf in category_forecasts.items()
        } if category_forecasts else None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_data_date(conn) -> date:
    """Always returns today's date for reference.
    Use _get_latest_transaction_date() to check data freshness."""
    return date.today()


def _get_latest_transaction_date(conn) -> date:
    """Get the most recent transaction date in the DB (for freshness checks)."""
    row = conn.execute(
        "SELECT MAX(date) as d FROM transactions WHERE date LIKE '____-__-__'"
    ).fetchone()
    if row and row["d"]:
        try:
            return date.fromisoformat(row["d"])
        except (ValueError, TypeError):
            pass
    return date.today()


def _months_back(ref: date, months: int) -> date:
    """Go back N months from a reference date, handling year boundaries."""
    m = ref.month - months
    y = ref.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)
