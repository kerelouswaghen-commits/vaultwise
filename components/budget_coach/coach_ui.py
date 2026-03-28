"""
Budget coach UI — adaptive Streamlit component that changes with the calendar.
Renders one of three modes: Game Plan (days 1-7), Pace Check (days 8-21), Wrap-Up (days 22-31).
"""

import hashlib
import json
from calendar import month_name
from datetime import date

import plotly.graph_objects as go
import streamlit as st

import database
from components.budget_coach import coach_config as cfg
from components.budget_coach import coach_stats
from components.budget_coach import coach_prompts
from shared.charts import CHART_LAYOUT, PALETTE
from shared.state import get_advisor


# ── Main Entry Point ──────────────────────────────────────────────────

def render_budget_coach(conn, selected_month: str, monthly_income: float,
                        fixed_costs: float, savings_target: int,
                        disc_budget: float, txn_discretionary: float,
                        over_budget: float, days_left: int,
                        month_breakdown: list):
    """Render the adaptive budget coach component on the home page."""
    today = date.today()
    sel_y, sel_m = int(selected_month[:4]), int(selected_month[5:7])
    is_current_month = (today.year == sel_y and today.month == sel_m)

    # Determine mode
    if is_current_month:
        mode = cfg.get_current_mode(today.day)
    else:
        mode = "wrapup"  # Past months always show wrap-up

    # Compute stats (cache in session state per month)
    coach_data = _get_or_compute_stats(conn, selected_month)
    if not coach_data:
        return

    # Carry-forward deficit from DB
    carry_forward = float(database.get_setting(conn, "carry_forward_deficit", "0"))

    # Build context
    context = {
        "income": monthly_income,
        "fixed_total": coach_data["fixed_total"],
        "fixed_categories": coach_data["fixed_categories"],
        "savings_target": savings_target,
        "flex_budget": disc_budget,
        "carry_forward": carry_forward,
        "over_budget": over_budget,
        "category_profiles": coach_data["category_profiles"],
        "anomaly_flags": coach_data["anomaly_flags"],
        "guardrail_caps": coach_data["guardrail_caps"],
        "eom_projection": coach_data["eom_projection"],
        "pace_check": coach_data["pace_check"],
        "current_totals": coach_data["current_totals"],
        "velocity_curves": coach_data["velocity_curves"],
    }

    # Render mode
    mode_labels = {"gameplan": "Game Plan", "pacecheck": "Pace Check", "wrapup": "Wrap-Up"}
    month_display = f"{month_name[sel_m]} {sel_y}"

    if mode == "gameplan":
        _render_game_plan(conn, context, month_display, coach_data)
    elif mode == "pacecheck":
        _render_pace_check(conn, context, month_display, coach_data, selected_month)
    else:
        _render_wrap_up(conn, context, month_display, coach_data,
                        monthly_income, txn_discretionary, fixed_costs, savings_target)


# ── Stats Caching ─────────────────────────────────────────────────────

def _get_or_compute_stats(conn, selected_month: str) -> dict | None:
    """Compute coach stats, caching in session state per month."""
    cache_key = "coach_data"
    month_key = "coach_stats_month"

    if (st.session_state.get(month_key) == selected_month
            and st.session_state.get(cache_key) is not None):
        return st.session_state[cache_key]

    try:
        data = coach_stats.get_coach_data(conn, selected_month)
        st.session_state[cache_key] = data
        st.session_state[month_key] = selected_month
        return data
    except Exception as e:
        st.error(f"Budget coach error: {str(e)[:100]}")
        return None


# ── Claude Response Caching ───────────────────────────────────────────

def _get_claude_response(conn, mode: str, month: str, prompt: str) -> dict | None:
    """Get Claude response with DB caching."""
    data_hash = hashlib.md5(prompt[:500].encode()).hexdigest()[:8]

    # Check cache
    cached = database.get_coach_cache(conn, mode, month, data_hash)
    if cached:
        return cached

    advisor = get_advisor()
    if not advisor:
        return None

    try:
        result = advisor.generate_coach_response(prompt)
        database.set_coach_cache(conn, mode, month, data_hash, result)
        return result
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
# MODE 1: GAME PLAN (Days 1-7)
# ══════════════════════════════════════════════════════════════════════

def _render_game_plan(conn, context: dict, month_display: str, coach_data: dict):
    st.markdown(f"#### 👋 {month_display} Game Plan")

    income = context["income"]
    fixed_total = context["fixed_total"]
    savings_target = context["savings_target"]
    flex_budget = context["flex_budget"]
    fixed_cats = context["fixed_categories"]

    # ── Income / Fixed / Flex breakdown card ──
    _card(f"""
        <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
            <div><span style="color:#6b7280;">Income</span><br>
                <span style="font-size:1.2rem;font-weight:700;">${income:,.0f}</span></div>
            <div><span style="color:#6b7280;">Fixed Costs</span><br>
                <span style="font-size:1.2rem;font-weight:700;color:#8b5cf6;">${fixed_total:,.0f}</span></div>
            <div><span style="color:#6b7280;">Savings Target</span><br>
                <span style="font-size:1.2rem;font-weight:700;color:#3b82f6;">${savings_target:,.0f}</span></div>
        </div>
        <div style="border-top:2px solid #e5e7eb;padding-top:8px;margin-top:4px;">
            <span style="font-size:1.1rem;font-weight:700;color:#22c55e;">
                You have ${flex_budget:,.0f} to work with
            </span>
            <div style="font-size:0.82rem;color:#9ca3af;margin-top:4px;">
                Based on {', '.join(fixed_cats[:5])}{'…' if len(fixed_cats) > 5 else ''}
                totaling ${fixed_total:,.0f} in recurring bills detected from your history.
            </div>
        </div>
    """)

    # ── Carry-forward deficit ──
    carry = context["carry_forward"]
    if carry > 0:
        recovery_options = coach_stats.compute_recovery_options(
            carry, context["category_profiles"])
        feasible = [o for o in recovery_options if o["feasible"]]

        st.markdown(f"#### 📦 Carrying ${carry:,.0f} from previous months")

        if feasible:
            st.markdown("Want to recover some this month?")
            cols = st.columns(len(feasible) + 1)
            for i, opt in enumerate(feasible):
                with cols[i]:
                    if st.button(f"${opt['extra_per_month']:,.0f}/mo\n{opt['months']} months",
                                 key=f"recovery_{opt['months']}", use_container_width=True):
                        st.session_state["coach_recovery_pace"] = opt
                        database.set_setting(conn, "carry_forward_deficit", str(carry))
                        st.rerun()
            with cols[-1]:
                if st.button("Skip this month", key="recovery_skip", use_container_width=True):
                    st.session_state["coach_recovery_pace"] = None
                    st.rerun()

            selected_pace = st.session_state.get("coach_recovery_pace")
            if selected_pace:
                new_flex = flex_budget - selected_pace["extra_per_month"]
                st.info(f"That leaves **${new_flex:,.0f}** for discretionary spending.")

    # ── Watch List (last month anomalies) ──
    last_month_anomalies = coach_stats.get_last_month_anomalies(
        conn, context["category_profiles"])
    profiles = context["category_profiles"]
    caps = context["guardrail_caps"]

    watch_items = []
    for cat, anom in last_month_anomalies.items():
        profile = profiles.get(cat, {})
        if profile.get("type") in ("fixed", "one_time"):
            continue
        if anom["flag"] in ("spike", "elevated"):
            watch_items.append((cat, anom, profile))

    if watch_items:
        st.markdown("#### 👀 Watch List")
        st.caption("These ran hot last month.")

        for cat, anom, profile in watch_items:
            cap_info = caps.get(cat, {})
            moderate_cap = cap_info.get("moderate", profile.get("monthly_median", 0))
            gentle_cap = cap_info.get("gentle", profile.get("p75", 0))

            flag_color = PALETTE["red"] if anom["flag"] == "spike" else PALETTE["amber"]
            _card(f"""
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <span style="font-weight:700;">{cat}</span>
                        <span style="color:{flag_color};font-size:0.8rem;margin-left:8px;">
                            {'🔴 spike' if anom["flag"] == "spike" else '🟠 elevated'}
                        </span>
                    </div>
                </div>
                <div style="color:#4b5563;margin:6px 0;font-size:0.9rem;">
                    ${anom['current']:,.0f} last month &middot;
                    Your typical: ${profile.get('monthly_median', 0):,.0f} &middot;
                    Range: ${profile.get('p25', 0):,.0f}–${profile.get('p75', 0):,.0f}
                </div>
                <div style="font-size:0.85rem;color:#6b7280;">
                    Suggested cap: <strong>${moderate_cap:,.0f}</strong>
                </div>
            """)

            rejection_key = f"rejected_{cat}"
            rejection_count = st.session_state.get("coach_rejected_guardrails", {}).get(cat, 0)

            if rejection_count >= 3:
                st.caption("No worries — we'll just keep tracking.")
            else:
                btn_cols = st.columns(2)
                with btn_cols[0]:
                    if st.button(f"Set ${moderate_cap:,.0f} cap", key=f"set_cap_{cat}",
                                 use_container_width=True):
                        accepted = st.session_state.get("coach_accepted_guardrails", [])
                        accepted.append({"category": cat, "cap": moderate_cap})
                        st.session_state["coach_accepted_guardrails"] = accepted
                        database.set_setting(conn, "accepted_guardrails",
                                             json.dumps(accepted, default=str))
                        st.rerun()
                with btn_cols[1]:
                    if st.button("Not realistic", key=f"not_realistic_{cat}",
                                 use_container_width=True):
                        rejected = st.session_state.get("coach_rejected_guardrails", {})
                        rejected[cat] = rejected.get(cat, 0) + 1
                        st.session_state["coach_rejected_guardrails"] = rejected
                        new_count = rejected[cat]

                        if new_count == 1:
                            st.info(f"How about ${gentle_cap:,.0f}? That's your upper-normal range.")
                        elif new_count == 2:
                            # Ask Claude for alternative
                            alt_prompt = coach_prompts.build_not_realistic_prompt(
                                {"category": cat, "profile": profile,
                                 "all_profiles": profiles}, 2)
                            alt = _get_claude_response(conn, "not_realistic",
                                                       st.session_state.get("coach_stats_month", ""),
                                                       alt_prompt)
                            if alt and "explanation" in alt:
                                st.info(alt["explanation"])
                        st.rerun()

    # ── Claude summary ──
    context["last_month_anomalies"] = last_month_anomalies
    prompt = coach_prompts.build_game_plan_prompt(context)
    claude_resp = _get_claude_response(conn, "gameplan",
                                        st.session_state.get("coach_stats_month", ""), prompt)
    if claude_resp and "summary" in claude_resp:
        _card(f'<div style="color:#374151;">{claude_resp["summary"]}</div>',
              bg="#f0fdf4", border="#bbf7d0")


# ══════════════════════════════════════════════════════════════════════
# MODE 2: PACE CHECK (Days 8-21)
# ══════════════════════════════════════════════════════════════════════

def _render_pace_check(conn, context: dict, month_display: str,
                       coach_data: dict, selected_month: str):
    pace = context["pace_check"]
    day = pace["day_of_month"]
    dim = pace["days_in_month"]

    st.markdown(f"#### 📊 {month_display} Pace Check — Day {day}")

    # ── Velocity chart ──
    vel = context["velocity_curves"]
    avg_vel = vel["avg_velocity"]
    std_vel = vel.get("std_velocity", {})
    current_daily = pace["current_daily_cumulative"]

    # Build the chart
    fig = go.Figure()

    # Historical band (gray area: mean ± 1 std)
    days_range = list(range(1, dim + 1))
    # Estimate total spend for scaling: use last month's total or current projected
    eom = context["eom_projection"]
    projected_total = eom["total_projected"]

    upper_band = []
    lower_band = []
    avg_line = []
    for d in days_range:
        avg_pct = avg_vel.get(d, d / dim)
        std_pct = std_vel.get(d, 0.05)
        avg_line.append(avg_pct * projected_total)
        upper_band.append((avg_pct + std_pct) * projected_total)
        lower_band.append(max((avg_pct - std_pct) * projected_total, 0))

    # Upper boundary
    fig.add_trace(go.Scatter(
        x=days_range, y=upper_band, mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    # Lower boundary with fill
    fig.add_trace(go.Scatter(
        x=days_range, y=lower_band, mode="lines",
        line=dict(width=0), fill="tonexty",
        fillcolor="rgba(107,114,128,0.15)",
        name="Typical range", hoverinfo="skip",
    ))
    # Average line
    fig.add_trace(go.Scatter(
        x=days_range, y=avg_line, mode="lines",
        line=dict(color=PALETTE["gray"], width=1, dash="dot"),
        name="Typical pace", hoverinfo="skip",
    ))

    # Actual spending line
    actual_days = list(range(1, len(current_daily) + 1))
    last_val = current_daily[-1] if current_daily else 0
    expected_at_day = avg_vel.get(day, day / dim) * projected_total
    line_color = PALETTE["green"] if last_val <= expected_at_day * 1.05 else PALETTE["red"]

    fig.add_trace(go.Scatter(
        x=actual_days, y=current_daily, mode="lines",
        line=dict(color=line_color, width=2.5),
        name="This month",
        hovertemplate="Day %{x}: $%{y:,.0f}<extra></extra>",
    ))

    # Today marker
    if current_daily:
        fig.add_trace(go.Scatter(
            x=[day], y=[current_daily[-1]], mode="markers",
            marker=dict(color=line_color, size=8),
            showlegend=False,
            hovertemplate=f"Today (Day {day}): ${current_daily[-1]:,.0f}<extra></extra>",
        ))

    fig.update_layout(
        **CHART_LAYOUT, height=280, showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
        yaxis=dict(title="Cumulative Spend ($)", gridcolor="#f3f4f6",
                   tickformat="$,.0f", zeroline=False),
        xaxis=dict(title="Day of Month", gridcolor="#f3f4f6",
                   dtick=7, range=[1, dim]),
    )
    st.plotly_chart(fig, use_container_width=True,
                    config={"responsive": True, "displayModeBar": False})

    # ── Projected EOM headline ──
    total_spent = pace["total_spent"]
    expected_pct = pace["expected_pct"]
    actual_pct = total_spent / projected_total if projected_total > 0 else 0
    delta_pp = (actual_pct - expected_pct) * 100

    if delta_pp > 5:
        _headline_card(
            f"At your current pace, you'll end the month at ${projected_total:,.0f}",
            f"You're {delta_pp:.0f} points ahead of your usual pace",
            PALETTE["red"], "#fef2f2", "#fecaca")
    elif delta_pp < -5:
        _headline_card(
            f"Projected: ${projected_total:,.0f} — under your typical pace",
            f"You're {abs(delta_pp):.0f} points below your usual — nice!",
            PALETTE["green"], "#f0fdf4", "#bbf7d0")
    else:
        _headline_card(
            f"Projected: ${projected_total:,.0f} — right on pace",
            f"Tracking within your normal spending pattern",
            PALETTE["blue"], "#eff6ff", "#bfdbfe")

    # ── Hot categories ──
    hot = pace.get("hot_categories", [])
    if hot:
        st.markdown("#### 🔥 Running Hot")
        for entry in hot:
            pct_used = entry["spent"] / entry["typical_total"] * 100 if entry["typical_total"] > 0 else 0
            pct_month = day / dim * 100
            _card(f"""
                <div style="font-weight:700;margin-bottom:4px;">{entry['category']}</div>
                <div style="display:flex;justify-content:space-between;font-size:0.9rem;color:#4b5563;">
                    <span>${entry['spent']:,.0f} spent</span>
                    <span>{pct_used:.0f}% used at {pct_month:.0f}% through month</span>
                </div>
                <div style="height:8px;border-radius:4px;background:#e5e7eb;margin:8px 0;overflow:hidden;">
                    <div style="height:100%;width:{min(pct_used, 100):.0f}%;background:{PALETTE['red']};border-radius:4px;"></div>
                </div>
                <div style="font-size:0.82rem;color:#9ca3af;">
                    Usually by day {day}: ${entry['expected_at_day']:,.0f} &middot;
                    Projected: ${entry['spent'] / max(entry['actual_pct'], 0.01) * 1.0 if entry['actual_pct'] > 0 else entry['spent']:,.0f}
                </div>
            """, border=PALETTE["red"])

            if st.button("I can't slow this down", key=f"rebalance_{entry['category']}"):
                _handle_rebalance(conn, entry, pace, context, selected_month)

    # ── Warm categories ──
    warm = pace.get("warm_categories", [])
    if warm:
        st.markdown("#### ⚠️ Watch")
        for entry in warm:
            st.markdown(
                f"**{entry['category']}** — ${entry['spent']:,.0f} "
                f"(usually ${entry['expected_at_day']:,.0f} by day {day})"
            )

    # ── On track ──
    on_track = pace.get("on_track_categories", [])
    if on_track:
        st.markdown("#### ✅ On Track")
        for entry in on_track:
            st.markdown(f"**{entry['category']}** — ${entry['spent']:,.0f}")

    # ── Claude commentary ──
    prompt_ctx = {
        "day_of_month": day,
        "days_in_month": dim,
        "total_spent": total_spent,
        "flex_budget": context["flex_budget"],
        "projected_total": projected_total,
        "savings_target": context["savings_target"],
        "hot_categories": hot,
        "warm_categories": warm,
    }
    prompt = coach_prompts.build_pace_check_prompt(prompt_ctx)
    claude_resp = _get_claude_response(conn, "pacecheck", selected_month, prompt)
    if claude_resp and "headline" in claude_resp:
        _card(f'<div style="color:#374151;">{claude_resp["headline"]}</div>',
              bg="#eff6ff", border="#bfdbfe")


def _handle_rebalance(conn, hot_entry: dict, pace: dict, context: dict, selected_month: str):
    """Handle rebalance request when user can't slow a hot category."""
    on_track = pace.get("on_track_categories", [])
    under_pace = [c for c in on_track if c["pace_delta"] < -0.02]

    rebalance_ctx = {
        "rejected_category": hot_entry["category"],
        "projected_overage": hot_entry["spent"],
        "overage_amount": hot_entry["spent"] - hot_entry["expected_at_day"],
        "under_pace_categories": under_pace,
    }
    prompt = coach_prompts.build_rebalance_prompt(rebalance_ctx)
    result = _get_claude_response(conn, "rebalance", selected_month, prompt)
    if result and "rebalance_plan" in result:
        st.info(result["rebalance_plan"])
    else:
        st.info("All categories are running near their typical pace — no room to shift right now.")


# ══════════════════════════════════════════════════════════════════════
# MODE 3: WRAP-UP (Days 22-31)
# ══════════════════════════════════════════════════════════════════════

def _render_wrap_up(conn, context: dict, month_display: str,
                    coach_data: dict, monthly_income: float,
                    txn_discretionary: float, fixed_costs: float,
                    savings_target: int):
    st.markdown(f"#### 📋 {month_display} Wrap-Up")

    total_spent = sum(context["current_totals"].values())
    actual_savings = monthly_income - total_spent - fixed_costs
    gap = actual_savings - savings_target

    # ── 5-number summary ──
    cols = st.columns(5)
    cols[0].metric("Spent", f"${total_spent:,.0f}")
    cols[1].metric("Budget", f"${monthly_income - savings_target:,.0f}")
    cols[2].metric("Savings", f"${actual_savings:,.0f}")
    cols[3].metric("Target", f"${savings_target:,.0f}")
    gap_delta = f"${abs(gap):,.0f} {'over' if gap >= 0 else 'short'}"
    cols[4].metric("Gap", gap_delta)

    # ── What Happened: Fixed costs ──
    st.markdown("#### What Happened")
    profiles = context["category_profiles"]
    anomalies = context["anomaly_flags"]
    current_totals = context["current_totals"]

    # Group categories by type
    fixed_cats = [(cat, current_totals.get(cat, 0), p)
                  for cat, p in profiles.items() if p["type"] == "fixed"]
    unusual_cats = [(cat, current_totals.get(cat, 0), anomalies.get(cat, {}))
                    for cat, p in profiles.items()
                    if p["type"] == "one_time"
                    or anomalies.get(cat, {}).get("flag") == "spike"
                    and p["type"] != "fixed"]
    controllable_cats = [(cat, current_totals.get(cat, 0), anomalies.get(cat, {}), p)
                         for cat, p in profiles.items()
                         if p["type"] in ("flexible_recurring", "flexible")
                         and anomalies.get(cat, {}).get("flag") == "elevated"
                         and current_totals.get(cat, 0) > 0]

    # Fixed
    if fixed_cats:
        st.markdown("**🔒 Fixed (auto-detected)**")
        st.caption("These showed up every month with <15% variation. Nothing to do.")
        for cat, amount, profile in fixed_cats:
            if amount > 0:
                st.markdown(
                    f"&nbsp;&nbsp; {cat} — ${amount:,.0f} "
                    f"*(typical: ${profile['monthly_mean']:,.0f} ± ${profile['monthly_std']:,.0f})*"
                )

    # Unusual
    if unusual_cats:
        st.markdown("**⚡ Unusual This Month**")
        for cat, amount, anom in unusual_cats:
            if amount > 0:
                z = anom.get("z_score", 0)
                z_text = "well above your usual" if z > 2 else "above your usual"
                expected = anom.get("expected", 0)
                st.markdown(
                    f"&nbsp;&nbsp; {cat} — ${amount:,.0f} "
                    f"*({z_text}, typically ${expected:,.0f}. Likely a one-time expense.)*"
                )
        st.caption("Won't repeat — no action needed.")

    # Controllable
    if controllable_cats:
        st.markdown("**🎯 Where You Have Control**")
        for cat, amount, anom, profile in controllable_cats:
            z = anom.get("z_score", 0)
            z_text = "well above your usual" if z > 2 else "a bit above your usual" if z > 1 else "near your usual"
            st.markdown(
                f"&nbsp;&nbsp; {cat} — ${amount:,.0f} "
                f"*(typical: ${profile['monthly_mean']:,.0f}, "
                f"this month: {z_text}, "
                f"your good months: ~${profile['p25']:,.0f})*"
            )

    # ── Recovery Pace Picker ──
    if gap < 0:
        deficit = abs(gap)
        carry = float(database.get_setting(conn, "carry_forward_deficit", "0"))
        total_deficit = carry + deficit

        st.markdown("#### Recovery Plan")
        st.markdown(f"You're **${total_deficit:,.0f}** behind your savings goal. Here's how to catch up.")

        recovery_options = coach_stats.compute_recovery_options(
            total_deficit, profiles)
        feasible = [o for o in recovery_options if o["feasible"]]

        if feasible:
            cols = st.columns(len(feasible))
            emojis = ["🏃", "🚶", "🐢", "🌊"]
            for i, opt in enumerate(feasible):
                with cols[i]:
                    emoji = emojis[i] if i < len(emojis) else "📅"
                    _card(f"""
                        <div style="text-align:center;">
                            <div style="font-size:1.5rem;">{emoji}</div>
                            <div style="font-weight:700;font-size:1.1rem;">{opt['months']} months</div>
                            <div style="color:#4b5563;margin:4px 0;">${opt['extra_per_month']:,.0f}/mo extra</div>
                            <div style="font-size:0.82rem;color:#9ca3af;">
                                Back by {_months_from_now(opt['months'])}
                            </div>
                        </div>
                    """)
                    if st.button("Choose", key=f"wrapup_recovery_{opt['months']}",
                                 use_container_width=True):
                        st.session_state["coach_recovery_pace"] = opt
                        database.set_setting(conn, "carry_forward_deficit", str(total_deficit))
                        st.success(f"Recovery plan set: ${opt['extra_per_month']:,.0f}/mo for {opt['months']} months.")
                        st.rerun()
        else:
            st.info("The deficit is large relative to your flexible spending. "
                    "Consider extending your recovery timeline or adjusting your savings target.")

    # ── Claude encouragement ──
    diag = {
        "fixed": [{"category": c, "amount": a} for c, a, _ in fixed_cats if a > 0],
        "unusual": [{"category": c, "amount": a, "z": an.get("z_score", 0)} for c, a, an in unusual_cats if a > 0],
        "controllable": [{"category": c, "amount": a, "z": an.get("z_score", 0)} for c, a, an, _ in controllable_cats],
    }
    wrap_ctx = {
        "total_spent": total_spent,
        "budget": monthly_income - savings_target,
        "actual_savings": actual_savings,
        "savings_target": savings_target,
        "gap": gap,
        "category_diagnosis": diag,
    }
    prompt = coach_prompts.build_wrap_up_prompt(wrap_ctx)
    month_key = st.session_state.get("coach_stats_month", "")
    claude_resp = _get_claude_response(conn, "wrapup", month_key, prompt)
    if claude_resp and "encouragement" in claude_resp:
        _card(f'<div style="color:#374151;">{claude_resp["encouragement"]}</div>',
              bg="#f0fdf4", border="#bbf7d0")


# ── UI Helpers ────────────────────────────────────────────────────────

def _card(html: str, bg: str = "white", border: str = "#e5e7eb"):
    """Render a styled card."""
    st.markdown(
        f'<div style="background:{bg};border:1px solid {border};border-radius:10px;'
        f'padding:14px 16px;margin-bottom:10px;">{html}</div>',
        unsafe_allow_html=True,
    )


def _headline_card(title: str, subtitle: str, color: str, bg: str, border: str):
    """Render a headline metric card."""
    _card(f"""
        <div style="font-size:1.05rem;font-weight:700;color:{color};">{title}</div>
        <div style="font-size:0.85rem;color:#6b7280;margin-top:4px;">{subtitle}</div>
    """, bg=bg, border=border)


def _months_from_now(n: int) -> str:
    """Return month name N months from now."""
    today = date.today()
    m = today.month + n
    y = today.year
    while m > 12:
        m -= 12
        y += 1
    return f"{month_name[m]} {y}"
