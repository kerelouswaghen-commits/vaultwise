"""
VaultWise Budget Coach — Drop-in replacement for the inline spending coach
section in views/home.py.  Renders Claude-driven summary + category cards.

Usage in views/home.py:
    import budget_coach
    budget_coach.render(conn, selected_month, ...)
"""

import calendar
from datetime import date

import plotly.graph_objects as go
import streamlit as st

import analytics_cache
import config
import database
import spending_intelligence


# ═══════════════════════════════════════════════════════════════
# CONFIG helpers
# ═══════════════════════════════════════════════════════════════

def _get_muted():
    return set(getattr(config, 'MUTED_CATEGORIES', []))


# ═══════════════════════════════════════════════════════════════
# DATA ASSEMBLY
# ═══════════════════════════════════════════════════════════════

def _get_flex_categories(conn, fixed_cats, month_key=None):
    """Get budget status for flexible (non-fixed, non-muted) categories.
    Also handles: merging duplicate categories, hiding $0 categories."""
    all_status = spending_intelligence.get_category_budget_status(conn, month_key=month_key)
    muted = _get_muted()
    merges = getattr(config, 'CATEGORY_MERGES', {})
    merge_sources = set()
    for sources in merges.values():
        merge_sources.update(sources)

    hide_zero = getattr(config, 'HIDE_ZERO_CATEGORIES', True)

    flex = [
        s for s in all_status
        if s["category"] not in fixed_cats
        and s["category"] not in muted
        and s["category"] not in merge_sources  # hide merged-away categories
        and (not hide_zero or s["current_spend"] > 0)  # hide $0 categories
    ]
    flex.sort(key=lambda x: x["current_spend"], reverse=True)
    return flex


def _get_history(conn, category):
    """6-month spending history via the database helper.
    Returns {"labels": ["Oct", "Nov", ...], "values": [123, 456, ...]}."""
    rows = database.get_category_monthly_history(conn, category, months=6)
    # Rows come back newest-first; reverse for chronological sparklines
    rows = list(reversed(rows))

    # Build labels with year context when crossing year boundary
    years_present = {r["month"][:4] for r in rows}
    cross_year = len(years_present) > 1
    labels = []
    for r in rows:
        month_num = int(r["month"][5:7])
        month_label = calendar.month_abbr[month_num]
        if cross_year:
            month_label += f" '{r['month'][2:4]}"
        labels.append(month_label)

    return {
        "labels": labels,
        "values": [round(abs(r["total"])) for r in rows],
    }


def _get_merchants(conn, category, month_key, limit=4):
    """Top merchants for a category in a given month."""
    rows = database.get_merchant_breakdown_for_month(conn, category, month_key, limit=limit)
    return [{"name": r["name"][:28], "amount": round(abs(r["total"]))} for r in rows]


def _get_forecast(conn, category, hist_values):
    """Prophet forecast with sanity cap for spike months."""
    pf = analytics_cache.get_cached_prophet(conn, category)
    if not pf or not pf.get("forecast"):
        return None

    nxt = pf["forecast"][0]
    pred = nxt.get("predicted", 0)
    low = nxt.get("lower", 0)
    high = nxt.get("upper", 0)
    note = ""

    # Sanity: if forecast > 3x median and recent data was a spike, cap it
    if hist_values and len(hist_values) >= 3:
        median_val = sorted(hist_values)[len(hist_values) // 2]
        if median_val > 0 and pred > median_val * 3:
            pred = round(median_val * 1.1)
            high = round(median_val * 1.5)
            low = round(median_val * 0.7)
            note = " (adjusted — last month was a spike)"

    return {
        "predicted": round(pred),
        "low": round(max(low, 0)),
        "high": round(high),
        "note": note,
    }


# ═══════════════════════════════════════════════════════════════
# CLAUDE — prompt + call
# ═══════════════════════════════════════════════════════════════

def _build_prompt(flex_status, conn, month_key, sel_year, sel_month,
                  monthly_income, effective_fixed, savings_target,
                  disc_budget, txn_discretionary, discretionary_left,
                  days_left, days_in_month, fixed_cats):
    """Build the Claude system prompt with runtime data."""

    viewing_current = days_left > 0

    if viewing_current:
        today = date.today()
        time_ctx = (
            f"Day {today.day} of {days_in_month} ({days_left} days left). "
            f"This is the current month — spending is still in progress."
        )
    else:
        time_ctx = (
            f"Viewing {calendar.month_name[sel_month]} {sel_year} "
            f"(completed month, {days_in_month} days, all spending is final)."
        )

    # Category data
    cat_lines = []
    for s in flex_status[:12]:
        cat_lines.append(
            f"- {s['category']}: ${s['current_spend']:,.0f} this month, "
            f"expected ${s['monthly_average']:,.0f}, "
            f"median ${s['monthly_median']:,.0f}, "
            f"projected ${s['projected_month_end']:,.0f}, "
            f"percentile {s['percentile']}"
        )

    # Decompose "Other"
    other_detail = ""
    if any(s["category"] == "Other" for s in flex_status):
        rows = conn.execute("""
            SELECT description, SUM(ABS(amount)) as total
            FROM transactions
            WHERE strftime('%Y-%m', date) = ? AND category = 'Other' AND amount < 0
            GROUP BY description ORDER BY total DESC LIMIT 5
        """, (month_key,)).fetchall()
        if rows:
            other_detail = "Breakdown of 'Other': " + ", ".join(
                f"{r['description'][:25]}: ${r['total']:,.0f}" for r in rows
            )

    # Forecasts
    fc_lines = []
    for s in flex_status[:8]:
        pf = analytics_cache.get_cached_prophet(conn, s["category"])
        if pf and pf.get("forecast"):
            n = pf["forecast"][0]
            fc_lines.append(
                f"- {s['category']}: next month ~${n['predicted']:,.0f} "
                f"(range ${n.get('lower', 0):,.0f}–${n.get('upper', 0):,.0f})"
            )

    excluded = ", ".join(sorted(fixed_cats | _get_muted()))

    return (
        "You are a budget coach inside a personal finance app. "
        "Analyze the spending data and generate insights.\n\n"
        f"CONTEXT: This user's spending money is ${disc_budget:,.0f}/month. "
        f"That's what remains after income (${monthly_income:,.0f}) minus "
        f"fixed bills (${effective_fixed:,.0f}) minus savings target "
        f"(${savings_target:,}/mo). Every number and percentage you mention "
        f"should be relative to this ${disc_budget:,.0f} spending money — "
        f"NOT relative to total income.\n\n"
        f"BUDGET:\n"
        f"- Spending money: ${disc_budget:,.0f} (THIS is the budget)\n"
        f"- Spent: ${txn_discretionary:,.0f}\n"
        f"- Remaining: ${discretionary_left:,.0f}\n"
        f"- % used: {round(txn_discretionary / max(disc_budget, 1) * 100)}%\n"
        f"- {time_ctx}\n\n"
        f"CATEGORIES (flexible spending only — fixed bills already excluded):\n"
        + "\n".join(cat_lines) + "\n\n"
        f"{other_detail}\n\n"
        f"FORECASTS:\n"
        + ("\n".join(fc_lines) if fc_lines else "None available.") + "\n\n"
        f"EXCLUDED (already removed from the data above): {excluded}\n\n"
        "DUPLICATE MERCHANTS: Check if any merchant appears in multiple "
        "categories in the data above. If so, mention it in the relevant "
        "category notes (e.g., 'Note: Amazon also appears in Other Shopping'). "
        "This helps the user understand their categorization.\n\n"
        "RETURN a JSON object with:\n"
        '1. "headline": 8 words max. Reference spending money, not income.\n'
        '2. "body": 3-5 sentences. Frame everything relative to the '
        f'${disc_budget:,.0f} spending money budget. Example: '
        f'"You\'ve used 45% of your spending money halfway through the month." '
        'Past tense for completed months. Never suggest returning purchases. '
        'Use forecast data when relevant.\n'
        '3. "categories": array sorted by concern (worst first), each with:\n'
        '   - "name": exact category name from data above\n'
        '   - "badge": "way over" | "elevated" | "hot pace" | "one-time" | '
        '"normal" | "under pace" | "low"\n'
        '   - "badge_icon": single emoji\n'
        '   - "color": "#dc2626" (red/way over) | "#e11d48" (rose/elevated) | "#f59e0b" (amber/hot) | "#0284c7" (blue/normal) | "#16a34a" (green/under) | "#059669" (emerald/low)\n'
        '   - "note": one sentence. Say "$X actual vs $Y expected" then '
        'brief context. If a merchant appears in multiple categories '
        '(e.g., Amazon in both Online Shopping and Other Shopping, or '
        'Anthropic in multiple categories), note the duplication.\n\n'
        "SORT: Most concerning first (way over → elevated → normal → low).\n\n"
        "CATEGORY NOTE: Some merchants may appear in multiple categories "
        "(e.g., Amazon in both 'Online Shopping' and 'Other Shopping'). "
        "If you notice this, mention it briefly in the relevant category's "
        "note (e.g., 'includes some Amazon purchases also in Online Shopping'). "
        "Do NOT double-count the impact.\n\n"
        "DUPLICATE CHECK: If categories look like they overlap "
        "(e.g., 'Education' $57 when 'Childcare & Education' is excluded as fixed), "
        "flag the smaller one as possibly miscategorized in your note.\n\n"
        "Return ONLY valid JSON. No markdown. No explanation."
    )


def _call_claude(prompt, get_advisor_fn, flex_status):
    """Call Claude via generate_coach_response. Fallback on failure."""
    advisor = get_advisor_fn()
    if not advisor:
        return _fallback_response(flex_status)

    try:
        return advisor.generate_coach_response(prompt, max_tokens=2048)
    except Exception:
        return _fallback_response(flex_status)


def _fallback_response(flex_status):
    """Minimal response if Claude is unavailable."""
    return {
        "headline": "Spending summary",
        "body": "Claude is unavailable. Here are your spending categories.",
        "categories": [
            {
                "name": s["category"],
                "badge": "—",
                "badge_icon": "",
                "color": "#6b7280",
                "note": f"${s['current_spend']:,.0f} spent",
            }
            for s in flex_status[:8]
        ],
    }


# ═══════════════════════════════════════════════════════════════
# RENDERING
# ═══════════════════════════════════════════════════════════════

def _render_daily_card(over_budget, discretionary_left, days_left,
                       viewing_current, month_name_str):
    """Replaces the old FREEZE spending card."""

    if not viewing_current:
        # Past month
        if over_budget > 0:
            html = (
                f'<div style="background:#fef2f2;border:1px solid #fecaca;'
                f'border-radius:10px;padding:10px 14px;margin-bottom:8px;">'
                f'<span style="font-size:1rem;font-weight:700;color:#ef4444;">'
                f'\\${over_budget:,.0f} from savings</span> '
                f'<span style="color:#6b7280;font-size:0.88rem;">'
                f'was used in {month_name_str}.</span></div>'
            )
        else:
            html = (
                f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;'
                f'border-radius:10px;padding:10px 14px;margin-bottom:8px;">'
                f'<span style="font-size:1rem;font-weight:700;color:#16a34a;">'
                f'{month_name_str} closed</span> '
                f'<span style="color:#6b7280;font-size:0.88rem;">'
                f'with \\${discretionary_left:,.0f} spending money left.'
                f'</span></div>'
            )
    elif over_budget > 0:
        html = (
            f'<div style="background:#fef2f2;border:1px solid #fecaca;'
            f'border-radius:10px;padding:10px 14px;margin-bottom:8px;">'
            f'<span style="font-size:1rem;font-weight:700;color:#ef4444;">'
            f'\\${over_budget:,.0f} from savings</span> '
            f'<span style="color:#6b7280;font-size:0.88rem;">'
            f'used this month.'
        )
        if days_left > 0:
            html += (
                f' Keeping spending minimal for the last {days_left} days '
                f'stops it from growing.'
            )
        html += '</span></div>'
    elif discretionary_left > 0 and days_left > 0:
        daily = round(discretionary_left / max(days_left, 1))
        if daily > 80:
            html = (
                f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;'
                f'border-radius:10px;padding:10px 14px;margin-bottom:8px;">'
                f'<span style="font-size:1rem;font-weight:700;color:#22c55e;">'
                f'\\${daily}/day</span> '
                f'<span style="color:#6b7280;font-size:0.88rem;">'
                f'for the next {days_left} days. Looking good.</span></div>'
            )
        else:
            html = (
                f'<div style="background:#fffbeb;border:1px solid #fde68a;'
                f'border-radius:10px;padding:10px 14px;margin-bottom:8px;">'
                f'<span style="font-size:1rem;font-weight:700;color:#d97706;">'
                f'\\${daily}/day</span> '
                f'<span style="color:#6b7280;font-size:0.88rem;">'
                f'for the next {days_left} days. Getting tight.</span></div>'
            )
    else:
        return  # nothing to show

    st.markdown(html, unsafe_allow_html=True)


def _render_summary(coach, escape_fn):
    """Claude's summary card."""
    body = escape_fn(coach.get("body", ""))
    headline = escape_fn(coach.get("headline", "Spending summary"))

    st.markdown(
        f'<div style="'
        f'background:#f8f7f5;'
        f'border:1px solid #e8e5df;'
        f'border-radius:12px;'
        f'padding:14px 16px;'
        f'margin-bottom:12px;'
        f'">'
        f'<div style="font-weight:700;font-size:0.95rem;color:#1a1a2e;'
        f'margin-bottom:6px;">{headline}</div>'
        f'<div style="font-size:0.85rem;line-height:1.55;color:#555;">'
        f'{body}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _badge_style(badge_text):
    """Return (bg_color, text_color) for a badge."""
    b = badge_text.lower()
    if "way over" in b:
        return "#fef2f2", "#dc2626"      # Red
    if any(w in b for w in ("elevated", "high")):
        return "#fff1f2", "#e11d48"      # Rose
    if any(w in b for w in ("hot", "one-time", "spike")):
        return "#fffbeb", "#d97706"      # Amber
    if "normal" in b:
        return "#f0f9ff", "#0284c7"      # Sky blue (neutral)
    if "under" in b:
        return "#f0fdf4", "#16a34a"      # Green (good)
    if "low" in b:
        return "#ecfdf5", "#059669"      # Emerald (very good)
    return "#f5f5f5", "#888888"          # Gray fallback


def _bold_dollars(text):
    """Make dollar amounts bold in HTML text."""
    import re
    return re.sub(r'(\$[\d,]+)', r'<strong>\1</strong>', text)


def _hex_to_rgba(hex_color, alpha):
    """Convert #RRGGBB to rgba(r, g, b, alpha)."""
    if hex_color.startswith("#") and len(hex_color) == 7:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        return f"rgba({r},{g},{b},{alpha})"
    return f"rgba(107,114,128,{alpha})"


def _render_category_card(cat_info, spent, typical, escape_fn):
    """One collapsed category card."""
    name = cat_info.get("name", "")
    badge = cat_info.get("badge", "")
    badge_icon = cat_info.get("badge_icon", "")
    color = cat_info.get("color", "#6b7280")
    note = escape_fn(cat_info.get("note", ""))

    badge_bg, badge_fg = _badge_style(badge)

    # Card border/bg tint by severity
    if any(w in badge.lower() for w in ("way over", "elevated")):
        card_bg = "#fef2f2"
        card_border = color
    elif any(w in badge.lower() for w in ("hot", "one-time", "spike")):
        card_bg = "#fffbeb"
        card_border = "#f59e0b"
    elif "normal" in badge.lower():
        card_bg = "#f8fafc"
        card_border = "#e2e8f0"
    else:
        card_bg = "#f0fdf4"
        card_border = "#bbf7d0"

    # Bar percentage: spent vs typical (capped at 100)
    bar_pct = min(round(spent / max(typical, 1) * 100), 100) if typical > 0 else 50

    st.markdown(
        f'<div style="'
        f'background:{card_bg};'
        f'border:1px solid {card_border};'
        f'border-left:4px solid {color};'
        f'border-radius:12px;'
        f'padding:11px 14px;'
        f'margin-bottom:3px;'
        f'">'

        # Row 1: name + badge + amount
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:center;gap:6px;">'
        f'<div style="display:flex;align-items:center;gap:7px;'
        f'flex:1;overflow:hidden;min-width:0;">'
        f'<span style="font-weight:700;font-size:0.9rem;color:#1a1a2e;'
        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
        f'{name}</span>'
        f'<span style="font-size:0.65rem;font-weight:700;'
        f'padding:2px 8px;border-radius:10px;white-space:nowrap;flex-shrink:0;'
        f'background:{badge_bg};color:{badge_fg};">'
        f'{badge_icon} {badge}</span>'
        f'</div>'
        f'<span style="font-weight:800;font-size:0.95rem;color:{color};'
        f'white-space:nowrap;flex-shrink:0;">'
        f'\\${spent:,.0f}</span>'
        f'</div>'

        # Row 2: progress bar
        f'<div style="height:5px;border-radius:3px;background:#eee;'
        f'overflow:hidden;margin:6px 0 5px;">'
        f'<div style="height:100%;width:{bar_pct}%;'
        f'background:{color};border-radius:3px;"></div></div>'

        # Row 3: note (Claude's note already includes "actual vs expected")
        f'<div style="font-size:0.78rem;color:#666;line-height:1.35;">'
        f'{_bold_dollars(note)}</div>'

        f'</div>',
        unsafe_allow_html=True,
    )


def _render_detail_expander(cat_name, hist, forecast, merchants, spent,
                            typical, median_val, percentile, color, escape_fn):
    """Expandable detail: stats, sparkline, forecast, merchants."""

    with st.expander(f"Details: {cat_name}", expanded=False):

        # Stats row
        st.markdown(
            f'<div style="display:flex;justify-content:space-around;text-align:center;'
            f'padding:6px 0;margin-bottom:4px;">'
            f'<div><div style="font-size:0.65rem;color:#aaa;text-transform:uppercase;">Expected</div>'
            f'<div style="font-weight:700;font-size:0.9rem;">\\${typical:,.0f}</div></div>'
            f'<div><div style="font-size:0.65rem;color:#aaa;text-transform:uppercase;">Median</div>'
            f'<div style="font-weight:700;font-size:0.9rem;">\\${median_val:,.0f}</div></div>'
            f'<div><div style="font-size:0.65rem;color:#aaa;text-transform:uppercase;">Percentile</div>'
            f'<div style="font-weight:700;font-size:0.9rem;">{percentile:.0f}th</div></div>'
            f'</div>', unsafe_allow_html=True)

        # Sparkline — always show something
        if hist["values"] and len(hist["values"]) >= 2:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hist["labels"],
                y=hist["values"],
                mode="lines+markers",
                line=dict(color=color, width=2.5, shape="spline"),
                marker=dict(size=5, color=color),
                fill="tozeroy",
                fillcolor=_hex_to_rgba(color, 0.08),
                hovertemplate="%{x}: $%{y:,.0f}<extra></extra>",
            ))
            fig.update_layout(
                height=110,
                margin=dict(t=5, b=25, l=45, r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=False, tickfont=dict(size=10, color="#aaa")),
                yaxis=dict(
                    showgrid=True, gridcolor="#f5f5f5",
                    tickfont=dict(size=9, color="#bbb"),
                    tickformat="$,.0f", zeroline=False,
                ),
                showlegend=False,
                hovermode="x",
            )
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False})
        elif hist["values"] and len(hist["values"]) == 1:
            st.metric(
                hist["labels"][0],
                f"${hist['values'][0]:,.0f}",
                help="Only one month of data available",
            )
        else:
            st.caption("No spending history for this category yet.")

        # Forecast
        if forecast:
            note_html = ""
            if forecast.get("note"):
                note_html = (
                    f'<div style="font-size:0.72rem;color:#5b7bb4;'
                    f'margin-top:4px;">{escape_fn(forecast["note"])}</div>'
                )

            st.markdown(
                f'<div style="'
                f'background:linear-gradient(135deg,#f0f4ff,#e8f0fe);'
                f'border:1px solid #d4e0f7;border-radius:10px;'
                f'padding:10px 12px;margin-bottom:10px;">'
                f'<div style="font-size:0.65rem;color:#5b7bb4;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px;">'
                f'Next Month Forecast</div>'
                f'<div style="display:flex;align-items:baseline;gap:6px;">'
                f'<span style="font-size:1.1rem;font-weight:800;color:#1a4a8a;">'
                f'\\${forecast["predicted"]:,.0f}</span>'
                f'<span style="font-size:0.72rem;color:#7fa3d4;">'
                f'\\${forecast["low"]:,.0f} – \\${forecast["high"]:,.0f}</span>'
                f'</div>'
                f'{note_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Merchants
        if merchants:
            st.markdown(
                '<div style="font-size:0.65rem;color:#bbb;font-weight:700;'
                'text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px;">'
                'Where It Went</div>',
                unsafe_allow_html=True,
            )
            for m in merchants:
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:4px 0;border-bottom:1px solid #f5f3ef;'
                    f'font-size:0.82rem;">'
                    f'<span style="color:#555;overflow:hidden;text-overflow:ellipsis;'
                    f'white-space:nowrap;max-width:65%;">'
                    f'{escape_fn(m["name"])}</span>'
                    f'<span style="font-weight:700;color:#1a1a2e;">'
                    f'\\${m["amount"]:,.0f}</span></div>',
                    unsafe_allow_html=True,
                )


# ═══════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def render(conn, selected_month, sel_year, sel_month,
           monthly_income, effective_fixed, savings_target,
           disc_budget, txn_discretionary, discretionary_left,
           over_budget, days_left, days_in_month, fixed_cats,
           get_advisor_fn, escape_fn):
    """
    Main entry point. Renders the daily card, Claude-driven spending
    summary, and category cards. Call this from views/home.py.
    """

    viewing_current = days_left > 0
    month_name = calendar.month_name[sel_month]

    # ── Daily card (replaces FREEZE) ─────────────────────────
    _render_daily_card(
        over_budget, discretionary_left, days_left,
        viewing_current, f"{month_name} {sel_year}",
    )

    # ── Get flexible categories (exclude fixed + muted) ──────
    flex_status = _get_flex_categories(conn, fixed_cats, month_key=selected_month)

    if not flex_status:
        st.info("No flexible spending data for this month.")
        return

    # ── Call Claude (cached in session state) ────────────────
    sel_day = date.today().day if viewing_current else days_in_month
    _month_txn_count = conn.execute(
        "SELECT COUNT(*) as c FROM transactions WHERE strftime('%Y-%m', date) = ?",
        (selected_month,)
    ).fetchone()["c"]
    cache_key = f"coach_{selected_month}_{int(txn_discretionary)}_{sel_day}_{_month_txn_count}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = None

    if st.session_state[cache_key] is None:
        prompt = _build_prompt(
            flex_status, conn, selected_month, sel_year, sel_month,
            monthly_income, effective_fixed, savings_target,
            disc_budget, txn_discretionary, discretionary_left,
            days_left, days_in_month, fixed_cats,
        )
        with st.spinner("Analyzing spending..."):
            st.session_state[cache_key] = _call_claude(
                prompt, get_advisor_fn, flex_status
            )

    coach = st.session_state.get(cache_key)
    if not coach:
        return

    # ── Sort by severity ─────────────────────────────────────
    severity_map = {
        "way over": 0, "elevated": 1, "hot": 2, "high": 2,
        "one-time": 3, "spike": 3, "normal": 4, "under": 5, "low": 6,
    }

    claude_cats = {c["name"]: c for c in coach.get("categories", [])}

    # Attach spend amounts for secondary sort
    for cc in coach.get("categories", []):
        match = next((s for s in flex_status if s["category"] == cc["name"]), None)
        if match:
            cc["_amount"] = match["current_spend"]

    def _badge_sort(c):
        badge = c.get("badge", "normal").lower()
        sev = 7
        for k, v in severity_map.items():
            if k in badge:
                sev = v
                break
        return (sev, -c.get("_amount", 0))

    coach["categories"].sort(key=_badge_sort)

    # ── Render summary ───────────────────────────────────────
    _render_summary(coach, escape_fn)

    # ── Render category cards ────────────────────────────────
    st.markdown(
        '<div style="font-size:0.68rem;color:#aaa;font-weight:700;'
        'text-transform:uppercase;letter-spacing:0.6px;'
        'margin:8px 0 6px 2px;">Your Spending Money Breakdown</div>',
        unsafe_allow_html=True,
    )

    # Use Claude's sorted order, but ensure all flex categories are shown
    rendered = set()
    ordered = []
    for cc in coach.get("categories", []):
        match = next((s for s in flex_status if s["category"] == cc["name"]), None)
        if match:
            ordered.append(match)
            rendered.add(cc["name"])
    # Append any categories Claude didn't mention
    for fs in flex_status:
        if fs["category"] not in rendered:
            ordered.append(fs)

    for fs in ordered:
        cat_name = fs["category"]
        spent = fs["current_spend"]
        typical = fs["monthly_average"]
        median_val = fs["monthly_median"]
        percentile = fs["percentile"]

        # Claude's analysis (or fallback with actual vs expected)
        ci = claude_cats.get(cat_name, {
            "name": cat_name,
            "badge": "low" if spent < typical * 0.5 else ("under pace" if spent < typical * 0.8 else ("normal" if spent <= typical * 1.3 else "elevated")),
            "badge_icon": "\U0001f4c9" if spent < typical * 0.5 else ("\u2705" if spent < typical * 0.8 else ("\U0001f4ca" if spent <= typical * 1.3 else "\u26a0\ufe0f")),
            "color": "#059669" if spent < typical * 0.5 else ("#16a34a" if spent < typical * 0.8 else ("#0284c7" if spent <= typical * 1.3 else "#dc2626")),
            "note": f"${spent:,.0f} actual vs ${typical:,.0f} expected",
        })

        # Render collapsed card
        _render_category_card(ci, spent, typical, escape_fn)

        # Get detail data
        hist = _get_history(conn, cat_name)
        merchants = _get_merchants(conn, cat_name, selected_month)
        forecast = _get_forecast(conn, cat_name, hist["values"])
        color = ci.get("color", "#6b7280")

        # Render expandable detail
        _render_detail_expander(
            cat_name, hist, forecast, merchants,
            spent, typical, median_val, percentile, color, escape_fn,
        )

    # ── Savings dip callout ──────────────────────────────────
    if over_budget > 0:
        st.markdown(
            f'<div style="background:#fef2f2;border:1px solid #fecaca;'
            f'border-radius:10px;padding:10px 14px;margin-top:8px;'
            f'font-size:0.84rem;color:#991b1b;">'
            f'\\${over_budget:,.0f} came from savings '
            f'{"this" if viewing_current else "that"} month.</div>',
            unsafe_allow_html=True,
        )

    # ── Refresh button ─────────────────────────────────────
    if st.button("\U0001f504 Refresh Analysis", key=f"refresh_{selected_month}"):
        keys_to_clear = [
            k for k in st.session_state.keys()
            if k.startswith(f"coach_{selected_month}")
        ]
        for k in keys_to_clear:
            del st.session_state[k]
        st.rerun()
