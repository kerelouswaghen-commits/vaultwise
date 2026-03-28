"""Budget coach configuration — all tunable thresholds in one place."""

# ── Mode boundaries (day of month) ─────────────────────────────────────
MODE_GAME_PLAN = (1, 7)
MODE_PACE_CHECK = (8, 21)
MODE_WRAP_UP = (22, 31)

# ── Category classification ────────────────────────────────────────────
PROFILE_LOOKBACK_MONTHS = 6
FIXED_CV_THRESHOLD = 0.20            # CV below this = fixed
FIXED_APPEARANCE_THRESHOLD = 0.83    # must appear 5/6 months
ONE_TIME_APPEARANCE_THRESHOLD = 0.5  # below this = sporadic
ONE_TIME_SPIKE_MULTIPLIER = 2.0      # vs median = one-time spike

# ── Anomaly detection ──────────────────────────────────────────────────
ANOMALY_SPIKE_Z = 2.0
ANOMALY_ELEVATED_Z = 1.0

# ── Pace check ─────────────────────────────────────────────────────────
VELOCITY_LOOKBACK_MONTHS = 3
PACE_HOT_THRESHOLD = 0.15   # 15pp ahead of typical velocity
PACE_WARM_THRESHOLD = 0.05  # 5pp ahead

# ── Recovery feasibility ───────────────────────────────────────────────
MAX_FLEX_SQUEEZE_PCT = 0.30   # max 30% cut to flex spending
RECOVERY_HORIZONS = [2, 3, 4, 6]  # months

# ── Guardrail rounding ─────────────────────────────────────────────────
CAP_ROUND_TO = 50  # round caps to nearest $50

# ── Cache ──────────────────────────────────────────────────────────────
COACH_CACHE_TTL_SECONDS = 86400  # 24 hours


def get_current_mode(day_of_month: int) -> str:
    """Return the coach mode based on day of month."""
    if MODE_GAME_PLAN[0] <= day_of_month <= MODE_GAME_PLAN[1]:
        return "gameplan"
    elif MODE_PACE_CHECK[0] <= day_of_month <= MODE_PACE_CHECK[1]:
        return "pacecheck"
    else:
        return "wrapup"


def round_to_cap(amount: float) -> float:
    """Round amount to nearest CAP_ROUND_TO (e.g. nearest $50)."""
    return round(amount / CAP_ROUND_TO) * CAP_ROUND_TO
