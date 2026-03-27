"""
Family Budget Tracker — Kero & Maggie's Financial Command Center
Upload PDF/CSV statements. Claude analyzes, advises, and forecasts.
"""

import json
import os
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import config
import chase_report_parser
import csv_parser
import database
import models
import pdf_parser
import reports
import spending_intelligence
import analytics_cache
import category_engine
from claude_advisor import ClaudeAdvisor

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG & INIT
# ═══════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="VaultWise", page_icon="💰", initial_sidebar_state="auto")

# PWA support — makes the app feel native on iPhone/Android
st.components.v1.html("""
<link rel="manifest" href="./static/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="VaultWise">
<link rel="apple-touch-icon" href="./static/icon-192.png">
<meta name="theme-color" content="#0066FF">
<script>
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./static/service-worker.js').catch(() => {});
}
</script>
""", height=0)

# Custom CSS — clean modern finance UI
st.markdown("""<style>
    /* Metric cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #f8f9fb 0%, #f0f2f6 100%);
        border: 1px solid #e2e6ed; border-radius: 14px; padding: 16px 20px;
        transition: transform 0.15s ease;
    }
    [data-testid="stMetric"]:hover { transform: translateY(-1px); }
    [data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 700; color: #1a1a2e; }
    [data-testid="stMetricLabel"] { font-size: 0.75rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600; }

    /* Sidebar */
    section[data-testid="stSidebar"] > div { padding-top: 1rem; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 4px; background: #f8f9fb; padding: 4px; border-radius: 10px; }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px; padding: 8px 16px; font-weight: 500;
    }
    .stTabs [aria-selected="true"] { background: white !important; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }

    /* Clean expanders */
    [data-testid="stExpander"] { border: 1px solid #e2e6ed; border-radius: 12px; overflow: hidden; }
    [data-testid="stExpander"] summary { font-weight: 500; }

    /* Alerts */
    .stAlert { border-radius: 10px; }

    /* Hide branding */
    #MainMenu, footer, header { visibility: hidden; }

    /* Chat */
    [data-testid="stChatMessage"] { border-radius: 12px; }

    /* Category cards */
    .cat-card { border-radius: 12px; padding: 16px; margin-bottom: 8px; border-left: 4px solid; }
    .cat-card-critical { border-left-color: #ef4444; background: #fef2f2; }
    .cat-card-warning { border-left-color: #f59e0b; background: #fffbeb; }
    .cat-card-good { border-left-color: #22c55e; background: #f0fdf4; }
    .cat-card-neutral { border-left-color: #6b7280; background: #f9fafb; }

    /* Progress bars */
    .budget-bar { height: 8px; border-radius: 4px; background: #e5e7eb; overflow: hidden; margin: 6px 0; }
    .budget-fill { height: 100%; border-radius: 4px; transition: width 0.3s ease; }

    /* Dividers */
    hr { border: none; border-top: 1px solid #e8ecf1; margin: 1.2rem 0; }

    /* Mobile responsive */
    @media (max-width: 768px) {
        [data-testid="stMetricValue"] { font-size: clamp(1rem, 4vw, 1.5rem); }
        [data-testid="stMetricLabel"] { font-size: clamp(0.6rem, 2vw, 0.75rem); }
        .cat-card { padding: 10px 12px; margin-bottom: 6px; }
        [data-testid="stExpander"] summary { font-size: 0.9rem; }
        [data-testid="stExpander"] > div { padding: 0.5rem 0.75rem; }
        /* Compact spacing */
        .block-container { padding: 1rem 0.75rem !important; }
        /* Chart height */
        [data-testid="stPlotlyChart"] > div { max-height: 300px; }
        /* Better touch targets */
        button, [data-testid="stCheckbox"] label { min-height: 44px; }
        /* Sidebar compact on mobile */
        section[data-testid="stSidebar"] > div { padding-top: 0.5rem; }
        section[data-testid="stSidebar"] [data-testid="stMetric"] { padding: 8px 12px; }
        /* Tabs compact */
        .stTabs [data-baseweb="tab"] { padding: 6px 10px; font-size: 0.85rem; }
    }
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 4px; }

    /* Top nav pill bar — never wrap */
    .nav-bar [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 4px !important; }
    .nav-bar button {
        font-size: clamp(0.6rem, 2.3vw, 0.78rem) !important;
        padding: 8px 2px !important; border-radius: 10px !important;
        white-space: nowrap; min-height: 42px;
    }
    .nav-bar button[kind="primary"] {
        box-shadow: 0 2px 8px rgba(0,102,255,0.25);
    }

    /* Gauge responsive helpers */
    .gauge-header, .gauge-footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 4px; }
    .gauge-detail { font-size: clamp(0.7rem, 2.5vw, 0.82rem); }
</style>""", unsafe_allow_html=True)

DB_PATH = os.path.join(os.path.dirname(__file__), "data", config.DB_FILENAME)
database.init_db(DB_PATH)

for key, default in [("advisor", None), ("session_id", str(uuid.uuid4())[:8]), ("chat_history", [])]:
    if key not in st.session_state:
        st.session_state[key] = default

_ci = database.get_connection(DB_PATH)
database.seed_default_objectives(_ci)

# Load persisted income/expense config from DB (if user edited in Settings)
import json as _json_init
_saved_income = database.get_setting(_ci, "income_config")
if _saved_income:
    try:
        config.INCOME.update(_json_init.loads(_saved_income))
    except (ValueError, TypeError):
        pass
_saved_expenses = database.get_setting(_ci, "fixed_expenses_config")
if _saved_expenses:
    try:
        config.FIXED_MONTHLY_EXPENSES.update(_json_init.loads(_saved_expenses))
    except (ValueError, TypeError):
        pass

# ── Monarch Money auto-sync on app open ──────────────────────────────────
if "monarch_synced" not in st.session_state:
    st.session_state.monarch_synced = False

if not st.session_state.monarch_synced:
    _monarch_on = database.get_setting(_ci, "monarch_enabled", "0")
    if _monarch_on == "1":
        try:
            import monarch_sync
            _sync_result = monarch_sync.sync_transactions(_ci)
            if _sync_result["new"] > 0:
                st.toast(f"Monarch: {_sync_result['new']} new transactions synced")
            if _sync_result["errors"]:
                st.toast(f"Monarch: {_sync_result['errors'][0]}", icon="⚠️")
        except Exception as _me:
            st.toast(f"Monarch sync: {str(_me)[:60]}", icon="⚠️")
    st.session_state.monarch_synced = True

_ci.close()


def get_advisor() -> ClaudeAdvisor | None:
    if st.session_state.advisor is not None:
        return st.session_state.advisor
    conn = database.get_connection(DB_PATH)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "") or database.get_setting(conn, "anthropic_api_key")
    conn.close()
    if not api_key:
        return None
    try:
        st.session_state.advisor = ClaudeAdvisor(api_key=api_key)
        return st.session_state.advisor
    except Exception:
        return None


def get_conn():
    return database.get_connection(DB_PATH)


def escape_dollars(text: str) -> str:
    """Escape ALL dollar signs so Streamlit never renders LaTeX.
    Claude responses never need LaTeX — all $ are currency."""
    if not text:
        return text
    return text.replace("$", "\\$")


def normalize_date(d: str, year_hint: str = "") -> str:
    """Ensure dates are YYYY-MM-DD format. Handles MM/DD, MM/DD/YY, MM/DD/YYYY."""
    if not d or d == "unknown":
        return d
    d = d.strip()
    # Already ISO?
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        return d
    # MM/DD/YYYY
    import re
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", d)
    if m:
        return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    # MM/DD/YY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2})", d)
    if m:
        yr = int(m.group(3))
        year = 2000 + yr if yr < 50 else 1900 + yr
        return f"{year}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    # MM/DD (no year) — use year_hint or current year
    m = re.match(r"(\d{1,2})/(\d{1,2})$", d)
    if m:
        yr = year_hint or str(date.today().year)
        return f"{yr}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    return d


def normalize_transactions(transactions: list, year_hint: str = "") -> list:
    """Normalize all dates in a transaction list to YYYY-MM-DD."""
    for txn in transactions:
        if "date" in txn:
            txn["date"] = normalize_date(txn["date"], year_hint)
    return transactions


# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 💰 Family Budget")
    st.caption(getattr(config, "FAMILY_DISPLAY_NAME", "Family Budget"))

    conn = get_conn()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "") or database.get_setting(conn, "anthropic_api_key")
    if not api_key:
        api_key_input = st.text_input("Anthropic API Key", type="password", placeholder="sk-ant-...")
        if api_key_input:
            database.set_setting(conn, "anthropic_api_key", api_key_input)
            os.environ["ANTHROPIC_API_KEY"] = api_key_input
            st.session_state.advisor = None
            conn.close()
            st.rerun()

    st.divider()

    # Status metrics
    txn_count = database.get_transaction_count(conn)
    stmts = database.get_all_statements(conn)
    c1, c2 = st.columns(2)
    c1.metric("Statements", len(stmts))
    c2.metric("Transactions", f"{txn_count:,}")

    savings_target = int(database.get_setting(conn, "monthly_savings_target", "1000"))
    st.metric("Savings Target", f"${savings_target:,}/mo")

    conn.close()
    st.divider()

    if "active_page" not in st.session_state:
        st.session_state.active_page = "Dashboard"

# ── Top navigation bar (buttons with on_click) ──────────────────────
def _set_page(p):
    st.session_state.active_page = p

_nav_items = [("📊", "Dashboard"), ("📋", "Transactions"), ("🔮", "Insights"), ("⚙️", "Settings")]
_nav_full = {"Insights": "Insights & Advisor"}  # short → full name

with st.container():
    st.markdown('<div class="nav-bar">', unsafe_allow_html=True)
    _ncols = st.columns([1, 1, 1, 1, 0.3])
    for i, (icon, label) in enumerate(_nav_items):
        full = _nav_full.get(label, label)
        is_active = st.session_state.active_page == full
        _ncols[i].button(
            f"{icon} {label}", key=f"nav_{i}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
            on_click=_set_page, args=(full,),
        )
    # Refresh button
    _ncols[4].button("🔄", key="nav_refresh", use_container_width=True,
                     help="Refresh app")
    st.markdown('</div>', unsafe_allow_html=True)

page = st.session_state.active_page

# ═══════════════════════════════════════════════════════════════════════════
# HELPER: Build clean charts
# ═══════════════════════════════════════════════════════════════════════════
CHART_LAYOUT = dict(
    margin=dict(t=40, b=35, l=55, r=30),
    font=dict(family="Inter, system-ui, sans-serif", size=12, color="#374151"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    hovermode="x unified",
    hoverlabel=dict(bgcolor="white", font_size=12, bordercolor="#e2e6ed"),
)

# Consistent color palette used across all charts
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

    # Confidence band (if Monte Carlo data available)
    if ci_low and ci_high:
        fig.add_trace(go.Scatter(
            x=list(df["month"]) + list(df["month"])[::-1],
            y=ci_high + ci_low[::-1],
            fill="toself", fillcolor="rgba(59,130,246,0.08)",
            line=dict(width=0), showlegend=True, name="80% confidence band",
            hoverinfo="skip",
        ))

    # Main line
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

    # Key annotations with better styling
    min_idx = df["cumulative"].idxmin()
    fig.add_annotation(
        x=df.loc[min_idx, "month"], y=df.loc[min_idx, "cumulative"],
        text=f"<b>Lowest: ${df.loc[min_idx, 'cumulative']:,.0f}</b>",
        showarrow=True, arrowhead=2, arrowcolor=PALETTE["red"],
        font=dict(color=PALETTE["red"], size=11),
        bgcolor="white", bordercolor=PALETTE["red"], borderwidth=1, borderpad=4,
    )
    # Final month annotation
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


# ═══════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════
if page == "Dashboard":
    import analytics

    conn = get_conn()
    txn_count = database.get_transaction_count(conn)

    st.markdown("## Dashboard")

    # Data freshness warning
    latest_txn = analytics._get_latest_transaction_date(conn)
    data_age = (date.today() - latest_txn).days
    if data_age > 30:
        st.warning(
            f"Your transaction data is **{data_age} days old** (latest: {latest_txn.isoformat()}). "
            f"Upload recent statements for accurate insights."
        )
    elif data_age > 7:
        st.info(f"Data as of {latest_txn.isoformat()} ({data_age} days ago). Upload recent statements to stay current.")

    if txn_count == 0:
        st.info("Upload statements to see monthly spending breakdown.")
        conn.close()
        st.stop()

    available_months = database.get_available_months(conn)
    if not available_months:
        st.info("No transaction data yet.")
        conn.close()
        st.stop()

    # Month navigation — selectbox
    from calendar import month_name as _mn
    selected_month = st.selectbox(
        "Month",
        available_months,
        index=0,
        format_func=lambda m: f"{_mn[int(m.split('-')[1])]} {m.split('-')[0]}",
        label_visibility="collapsed",
    )
    _y, _m = selected_month.split("-")
    month_display = f"{_mn[int(_m)]} {_y}"
    st.markdown(f"### {month_display}")

    # Get this month's data
    _raw_breakdown = database.get_monthly_category_breakdown(conn, selected_month)
    _active_cats_dash = category_engine.get_active_categories(conn)
    month_breakdown = [c for c in _raw_breakdown if c["category"] in _active_cats_dash]
    if not month_breakdown:
        st.info(f"No spending data for {month_display}.")
        conn.close()
        st.stop()

    # Top-level metrics
    total_spent = sum(abs(c["total"]) for c in month_breakdown)
    txn_total = sum(c["txn_count"] for c in month_breakdown)
    top_cat = month_breakdown[0] if month_breakdown else None

    # ── Savings Goal Tracker ──────────────────────────────────────
    _sel_year, _sel_month = int(_y), int(_m)
    _income_data = models.get_income_for_month(_sel_year, _sel_month)
    _monthly_income = _income_data["total_income"] if isinstance(_income_data, dict) else _income_data
    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))

    # Bonus toggles (default OFF for conservative planning)
    with st.expander("Bonus income toggles", expanded=False):
        _bonus_col1, _bonus_col2 = st.columns(2)
        _kero_bonus_on = _bonus_col1.checkbox("Include Kero bonus ($1,500/mo)", value=False, key="dash_kero_bonus")
        _maggie_bonus_on = _bonus_col2.checkbox("Include Maggie bonus ($417/mo)", value=False, key="dash_maggie_bonus")
    _kero_bonus_val = _income_data.get("kero_bonus", 0) if isinstance(_income_data, dict) else 0
    _maggie_bonus_val = _income_data.get("maggie_bonus", 0) if isinstance(_income_data, dict) else 0
    if not _kero_bonus_on:
        _monthly_income -= _kero_bonus_val
    if not _maggie_bonus_on:
        _monthly_income -= _maggie_bonus_val

    # Known fixed costs (mortgage, car, loans, church, etc.) — always happen even if not in transaction data
    _fixed_costs = sum(config.FIXED_MONTHLY_EXPENSES.values())

    # Total outflow = fixed costs + discretionary (from transactions)
    # Avoid double-counting: subtract any fixed-category spending already in transaction data
    _fixed_cats = {"Housing & Utilities", "Debt Payments", "Giving & Church", "Family Support",
                   "Transportation", "Childcare & Education", "Phone & Internet",
                   "Car Insurance"}
    _txn_fixed = sum(abs(c["total"]) for c in month_breakdown if c["category"] in _fixed_cats)
    _txn_discretionary = total_spent - _txn_fixed

    # Use the HIGHER of config fixed costs or actual fixed-category transactions
    _effective_fixed = max(_fixed_costs, _txn_fixed)
    _total_outflow = _effective_fixed + _txn_discretionary

    _budget_limit = _monthly_income - savings_target  # max you can spend and still save
    _saved = _monthly_income - _total_outflow
    _gap = _saved - savings_target
    _on_track = _saved >= savings_target
    _spent_pct = min(_total_outflow / _budget_limit * 100, 100) if _budget_limit > 0 else 100

    # Gauge colors
    _D = "$"
    if _on_track:
        _gauge_color = "#22c55e"
        _status_text = f"ON TRACK — {_D}{_gap:,.0f} above target"
        _status_icon = "✅"
    elif _saved > 0:
        _gauge_color = "#f59e0b"
        _status_text = f"AT RISK — {_D}{abs(_gap):,.0f} short of target"
        _status_icon = "⚠️"
    else:
        _gauge_color = "#ef4444"
        _status_text = f"OVER BUDGET — {_D}{abs(_saved):,.0f} in the red"
        _status_icon = "🔴"

    _D = "$"
    _gauge_html = (
        f'<div style="background:#f8f9fb;border:1px solid #e2e6ed;border-radius:14px;padding:14px 16px;margin-bottom:16px;">'
        f'<div class="gauge-header" style="margin-bottom:8px;">'
        f'<span style="font-weight:700;font-size:clamp(0.85rem,3vw,1rem);">🎯 {month_display} Savings Goal</span>'
        f'<span style="font-weight:700;font-size:clamp(0.9rem,3.5vw,1.1rem);color:{_gauge_color};">{_status_icon} {_D}{_saved:,.0f} saved</span>'
        f'</div>'
        f'<div style="height:12px;border-radius:6px;background:#e5e7eb;overflow:hidden;margin:8px 0;">'
        f'<div style="height:100%;width:{min(_spent_pct, 100):.0f}%;background:{_gauge_color};border-radius:6px;transition:width 0.3s;"></div>'
        f'</div>'
        f'<div class="gauge-footer gauge-detail" style="color:#6b7280;margin-top:4px;">'
        f'<span>{_D}{_total_outflow:,.0f} of {_D}{_budget_limit:,.0f} budget</span>'
        f'<span>Target: {_D}{savings_target:,}/mo</span>'
        f'</div>'
        f'<div class="gauge-detail" style="color:#9ca3af;margin-top:2px;">Fixed: {_D}{_effective_fixed:,.0f} · Disc: {_D}{_txn_discretionary:,.0f}</div>'
        f'<div style="font-size:clamp(0.75rem,2.5vw,0.85rem);color:{_gauge_color};font-weight:600;margin-top:6px;">{_status_text}</div>'
        f'</div>'
    )
    st.markdown(_gauge_html, unsafe_allow_html=True)

    # ── Daily Budget + Gap Closer ─────────────────────────────────
    _disc_budget = _monthly_income - _effective_fixed - savings_target
    _discretionary_left = max(_disc_budget - _txn_discretionary, 0)
    _over_budget = max(_txn_discretionary - _disc_budget, 0)

    from calendar import monthrange as _monthrange
    _days_in_month = _monthrange(_sel_year, _sel_month)[1]
    _days_left = max(_days_in_month - min(date.today().day, _days_in_month), 1) if (date.today().year, date.today().month) == (_sel_year, _sel_month) else 0

    _D = "$"
    if _days_left > 0:
        _daily_left = _discretionary_left / _days_left
        if _discretionary_left > 0:
            _pace_html = f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:12px 16px;margin-bottom:12px;"><span style="font-size:1.1rem;font-weight:700;color:#22c55e;">💰 {_D}{_daily_left:,.0f}/day</span> <span style="color:#6b7280;">for the next {_days_left} days to hit your {_D}{savings_target:,} target</span></div>'
        else:
            _pace_html = f'<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px 16px;margin-bottom:12px;"><span style="font-size:1.1rem;font-weight:700;color:#ef4444;">🛑 FREEZE spending</span> <span style="color:#6b7280;">for {_days_left} days — you\'re {_D}{_over_budget:,.0f} over your discretionary budget</span></div>'
        st.markdown(_pace_html, unsafe_allow_html=True)

    # Gap Closer — Claude-written actions (only if over budget)
    if _over_budget > 0:
        _gap_cache_key = f"gap_closer_{selected_month}_{_over_budget:.0f}"
        if _gap_cache_key not in st.session_state:
            st.session_state[_gap_cache_key] = None

        if st.session_state[_gap_cache_key] is None:
            advisor = get_advisor()
            if advisor:
                with st.spinner("Analyzing your spending to find savings..."):
                    try:
                        _gap_txns = conn.execute(
                            """SELECT date, description, amount, category FROM transactions
                               WHERE strftime('%Y-%m', date) = ? AND amount < 0 ORDER BY amount ASC""",
                            (selected_month,),
                        ).fetchall()
                        _gap_txn_text = "\n".join(f"{t['date']} | {t['description']} | {_D}{t['amount']:,.2f} | {t['category']}" for t in _gap_txns)
                        _gap_cat_summary = "\n".join(f"  {c['category']}: {_D}{abs(c['total']):,.2f} ({c['txn_count']} txns)" for c in month_breakdown)

                        _gap_result = advisor.generate_gap_closer(
                            gap=_over_budget,
                            discretionary_spent=_txn_discretionary,
                            discretionary_budget=_disc_budget,
                            days_left=_days_left,
                            savings_target=savings_target,
                            transactions_text=_gap_txn_text,
                            category_summary=_gap_cat_summary,
                        )
                        st.session_state[_gap_cache_key] = _gap_result
                    except Exception as _e:
                        st.session_state[_gap_cache_key] = {"error": str(_e)}

        _gap_data = st.session_state.get(_gap_cache_key)
        if _gap_data and "actions" in _gap_data:
            st.markdown(f"#### 🔴 Close Your {_D}{_over_budget:,.0f} Gap — Do These 3 Things")
            _cumulative_recovery = 0
            for _act in _gap_data.get("actions", [])[:3]:
                _recovery = _act.get("recovery", 0)
                _cumulative_recovery += _recovery
                _gap_remaining = max(_over_budget - _cumulative_recovery, 0)
                _pct_closed = min(_cumulative_recovery / _over_budget * 100, 100) if _over_budget > 0 else 0

                _act_html = (
                    f'<div style="background:white;border:1px solid #e5e7eb;border-radius:10px;padding:12px 16px;margin-bottom:8px;">'
                    f'<div style="font-weight:700;color:#1a1a2e;">{_act.get("rank", "")}. {_act.get("category", "")} — {_act.get("merchant", "")}</div>'
                    f'<div style="color:#4b5563;margin:6px 0;">{_act.get("action", "")}</div>'
                    f'<div style="display:flex;align-items:center;gap:10px;">'
                    f'<div style="flex:1;height:8px;border-radius:4px;background:#e5e7eb;overflow:hidden;">'
                    f'<div style="height:100%;width:{_pct_closed:.0f}%;background:#22c55e;border-radius:4px;"></div></div>'
                    f'<span style="font-size:0.85rem;color:#6b7280;">Gap: {_D}{_gap_remaining:,.0f}</span>'
                    f'</div></div>'
                )
                st.markdown(_act_html, unsafe_allow_html=True)

            _total_rec = _gap_data.get("total_recovery", _cumulative_recovery)
            _msg = _gap_data.get("message", "")
            if _msg:
                _summary_color = "#22c55e" if _total_rec >= _over_budget else "#f59e0b"
                st.markdown(f'<div style="background:#f8f9fb;border-radius:8px;padding:10px 14px;margin-bottom:16px;color:{_summary_color};font-weight:600;">✅ {_msg}</div>', unsafe_allow_html=True)

    # Detailed financial breakdown
    _kero_net = _income_data.get("kero_net", 0) if isinstance(_income_data, dict) else 0
    _maggie_net = _income_data.get("maggie_net", 0) if isinstance(_income_data, dict) else 0
    if _kero_bonus_on:
        _kero_net += _kero_bonus_val
    if _maggie_bonus_on:
        _maggie_net += _maggie_bonus_val

    with st.expander("Monthly Budget Breakdown", expanded=False):

        _left, _right = st.columns(2)
        with _left:
            st.markdown("**💵 Money In**")
            _D = "$"
            _in_html = (
                f'<table style="width:100%;font-size:0.9rem;border-collapse:collapse;">'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:4px 0;">Kero (Premera)</td><td style="text-align:right;font-weight:600;">{_D}{_kero_net:,.0f}</td></tr>'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:4px 0;">Maggie (Boeing)</td><td style="text-align:right;font-weight:600;">{_D}{_maggie_net:,.0f}</td></tr>'
                f'<tr style="border-bottom:2px solid #1a1a2e;"><td style="padding:6px 0;font-weight:700;">Total Income</td><td style="text-align:right;font-weight:700;font-size:1rem;">{_D}{_monthly_income:,.0f}</td></tr>'
                f'</table>'
            )
            st.markdown(_in_html, unsafe_allow_html=True)

            st.markdown("")
            st.markdown("**🏠 Fixed Monthly Bills**")
            _fixed_groups = {
                "Mortgage": config.FIXED_MONTHLY_EXPENSES.get("Mortgage (Mr. Cooper 6.49%)", 0),
                "Car (loan + insurance)": config.FIXED_MONTHLY_EXPENSES.get("Auto Loan (Chase #2102)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Car Insurance (CCS Country)", 0),
                "Student Loans": config.FIXED_MONTHLY_EXPENSES.get("Student Loan 1", 0) + config.FIXED_MONTHLY_EXPENSES.get("Student Loan 2", 0),
                "Church & Family": config.FIXED_MONTHLY_EXPENSES.get("Church (Zelle)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Family Support (Nermeen)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Church (CC small donations)", 0),
                "Utilities & Internet": config.FIXED_MONTHLY_EXPENSES.get("PSE Electric & Gas", 0) + config.FIXED_MONTHLY_EXPENSES.get("Water/Sewer (NUD)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Internet (Comcast/Xfinity)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Garbage & Recycling", 0),
                "Phone (T-Mobile + Mint)": config.FIXED_MONTHLY_EXPENSES.get("T-Mobile", 0) + config.FIXED_MONTHLY_EXPENSES.get("Mint Mobile (normalized)", 0),
                "Other fixed": config.FIXED_MONTHLY_EXPENSES.get("Gas (fuel)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Auto Maintenance (normalized)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Renters Insurance (AGI)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Digital Subscriptions", 0) + config.FIXED_MONTHLY_EXPENSES.get("Affirm", 0) + config.FIXED_MONTHLY_EXPENSES.get("CC Interest (card 3072)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Home Improvement (normalized)", 0) + config.FIXED_MONTHLY_EXPENSES.get("Travel (normalized)", 0),
            }
            _bills_html = '<table style="width:100%;font-size:0.85rem;border-collapse:collapse;">'
            for label, amt in _fixed_groups.items():
                _bills_html += f'<tr style="border-bottom:1px solid #f3f4f6;"><td style="padding:3px 0;color:#6b7280;">{label}</td><td style="text-align:right;">{_D}{amt:,.0f}</td></tr>'
            _bills_html += f'<tr style="border-top:2px solid #1a1a2e;"><td style="padding:5px 0;font-weight:700;">Total Fixed</td><td style="text-align:right;font-weight:700;">{_D}{_effective_fixed:,.0f}</td></tr>'
            _bills_html += '</table>'
            st.markdown(_bills_html, unsafe_allow_html=True)

        with _right:
            st.markdown("**🧮 The Math**")
            _disc_budget = _monthly_income - _effective_fixed - savings_target
            _math_html = (
                f'<table style="width:100%;font-size:0.9rem;border-collapse:collapse;">'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:5px 0;">Income</td><td style="text-align:right;font-weight:600;">{_D}{_monthly_income:,.0f}</td></tr>'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:5px 0;">− Fixed bills</td><td style="text-align:right;color:#ef4444;">−{_D}{_effective_fixed:,.0f}</td></tr>'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:5px 0;">− Savings target</td><td style="text-align:right;color:#7c3aed;">−{_D}{savings_target:,.0f}</td></tr>'
                f'<tr style="border-bottom:2px solid #1a1a2e;background:#f0fdf4;"><td style="padding:6px 0;font-weight:700;">= Discretionary budget</td><td style="text-align:right;font-weight:700;font-size:1.05rem;">{_D}{_disc_budget:,.0f}</td></tr>'
                f'<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:5px 0;">− Spent this month</td><td style="text-align:right;color:#ef4444;">−{_D}{_txn_discretionary:,.0f}</td></tr>'
                f'<tr style="background:{"#f0fdf4" if _discretionary_left > 0 else "#fef2f2"};"><td style="padding:6px 0;font-weight:700;">= Still available</td>'
                f'<td style="text-align:right;font-weight:700;font-size:1.1rem;color:{"#22c55e" if _discretionary_left > 0 else "#ef4444"};">{_D}{_discretionary_left:,.0f}</td></tr>'
                f'</table>'
            )
            st.markdown(_math_html, unsafe_allow_html=True)

            st.markdown("")
            st.markdown("**📊 Summary**")
            _s1, _s2 = st.columns(2)
            _s1.metric("Saved", f"${_saved:,.0f}")
            _s2.metric("Target", f"${savings_target:,}")
            st.metric("Gap to Target", f"${_gap:+,.0f}", delta_color="normal" if _gap >= 0 else "inverse")

    # ── Cache integration ──────────────────────────────────────────────
    # Check cache staleness and offer refresh
    _cache_stale = analytics_cache.is_stale(conn)
    if _cache_stale:
        st.warning(
            "Analytics cache is stale (last refreshed: "
            f"{analytics_cache.get_last_refresh_display(conn)}). "
            "Hit **Refresh Analytics** below to update trend data."
        )
    if st.button("Refresh Analytics", type="secondary" if not _cache_stale else "primary"):
        with st.spinner("Refreshing analytics cache (trends, forecasts, merchants)..."):
            analytics_cache.refresh_all(conn)
        st.rerun()

    # Read all cached trend data (instant reads from DB)
    cats = [c["category"] for c in month_breakdown]
    vals = [abs(c["total"]) for c in month_breakdown]

    _default_trend_dict = {
        "category": "", "direction": "stable", "slope_per_month": 0,
        "r_squared": 0, "current": 0, "mean": 0, "std": 0,
        "pct_vs_mean": 0, "months_analyzed": 0, "forecast_next": 0,
        "severity": "normal", "action": "",
    }

    trend_results = {}
    for cat in cats:
        cached_t = analytics_cache.get_cached_trend(conn, cat)
        if cached_t:
            trend_results[cat] = cached_t
        else:
            trend_results[cat] = {**_default_trend_dict, "category": cat}

    severity_map = {
        "critical": {"icon": "🔴", "color": PALETTE["red"], "label": "Needs Action"},
        "warning": {"icon": "🟠", "color": PALETTE["amber"], "label": "Watch"},
        "watch": {"icon": "🟡", "color": PALETTE["amber"], "label": "Monitor"},
        "normal": {"icon": "🟢", "color": PALETTE["green"], "label": "On Track"},
    }

    direction_icons = {"rising": "↑", "falling": "↓", "stable": "→"}

    # ── Bar chart: color by severity ────────────────────────────────────
    bar_colors = [
        severity_map.get(trend_results.get(c, _default_trend_dict).get("severity", "normal"),
                         severity_map["normal"])["color"]
        for c in cats
    ]

    fig = go.Figure(go.Bar(
        x=vals, y=cats, orientation="h",
        marker_color=bar_colors, marker_line_width=0,
        text=[f"${v:,.0f}" for v in vals],
        textposition="auto", textfont_size=11,
        hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(**CHART_LAYOUT, height=max(350, len(cats) * 38 + 80),
                     showlegend=False, yaxis=dict(autorange="reversed"),
                     xaxis=dict(title="Amount ($)", gridcolor="#f3f4f6", tickformat="$,.0f"))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.caption("Bar color: 🔴 needs action | 🟠 watch | 🟢 on track (based on statistical trend analysis)")

    # ── Unified Chat About Your Finances ──────────────────────────────
    if "dashboard_chat_history" not in st.session_state:
        st.session_state.dashboard_chat_history = []
    if "dashboard_chat_month" not in st.session_state:
        st.session_state.dashboard_chat_month = ""
    if st.session_state.dashboard_chat_month != selected_month:
        st.session_state.dashboard_chat_history = []
        st.session_state.dashboard_chat_month = selected_month

    with st.expander(f"💬 Chat About Your Finances", expanded=len(st.session_state.dashboard_chat_history) > 0):
        for msg in st.session_state.dashboard_chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(escape_dollars(msg["content"]))

        dash_question = st.chat_input(
            "Ask about spending or savings...",
            key="dashboard_chat_input",
        )
        if dash_question:
            with st.chat_message("user"):
                st.markdown(escape_dollars(dash_question))
            st.session_state.dashboard_chat_history.append({"role": "user", "content": dash_question})

            # Build comprehensive unified context
            _all_txns = conn.execute(
                """SELECT date, description, amount, category FROM transactions
                   WHERE strftime('%Y-%m', date) = ? ORDER BY category, date""",
                (selected_month,),
            ).fetchall()
            _txn_lines = [f"{t['date']} | {t['description']} | ${t['amount']:,.2f} | {t['category']}" for t in _all_txns]
            _txn_context = "\n".join(_txn_lines)
            _cat_summary = "\n".join(f"  {c['category']}: ${abs(c['total']):,.2f} ({c['txn_count']} txns)" for c in month_breakdown)

            # Include forecast data
            _forecast_lines = ""
            for _cat in [c["category"] for c in month_breakdown[:8]]:
                _pf = analytics_cache.get_cached_prophet(conn, _cat)
                if _pf and _pf.get("forecast"):
                    _next = _pf["forecast"][0]
                    _forecast_lines += f"  {_cat}: ${_next['predicted']:,.0f} predicted next month\n"

            _unified_context = (
                f"DASHBOARD DATA for {month_display}:\n"
                f"- Income (no bonus): ${_monthly_income:,.0f}\n"
                f"- Fixed bills: ${_effective_fixed:,.0f}\n"
                f"- Savings target: ${savings_target:,}/mo\n"
                f"- Discretionary budget: ${_disc_budget:,.0f}\n"
                f"- Discretionary spent: ${_txn_discretionary:,.0f}\n"
                f"- Over budget by: ${_over_budget:,.0f}\n"
                f"- Days left in month: {_days_left}\n"
                f"- Saved so far: ${_saved:,.0f}\n"
                f"- Gap to target: ${_gap:+,.0f}\n"
                f"- Total tracked: ${total_spent:,.0f} ({sum(c['txn_count'] for c in month_breakdown)} txns)\n\n"
                f"CATEGORY BREAKDOWN:\n{_cat_summary}\n\n"
                f"FORECASTS FOR NEXT MONTH:\n{_forecast_lines}\n"
                f"ALL TRANSACTIONS:\n{_txn_context}\n\n"
                f"You can explain any number shown on the dashboard, break down any category, "
                f"explain any transaction, interpret any forecast, or give savings advice. "
                f"Be realistic. Items already purchased may not be returnable. "
                f"Focus on: reducing remaining spending this month, planning next month's budget, "
                f"identifying habits to change, and using forecast data to prevent future overages."
            )

            advisor = get_advisor()
            if advisor:
                with st.chat_message("assistant"):
                    with st.spinner("Analyzing..."):
                        try:
                            result = advisor.get_advisor_response(
                                user_message=f"{_unified_context}\n\nUser question: {dash_question}",
                                conversation_history=st.session_state.dashboard_chat_history[:-1],
                                financial_context={"month": selected_month, "month_display": month_display, "total_spent": total_spent, "savings_target": savings_target, "gap": _over_budget},
                                tactical_context={},
                            )
                            response = result.get("response", str(result))
                            st.markdown(escape_dollars(response))
                            st.session_state.dashboard_chat_history.append({"role": "assistant", "content": response})
                        except Exception as e:
                            st.error(f"Could not get a response: {e}")
                            st.session_state.dashboard_chat_history.append({"role": "assistant", "content": str(e)})
            else:
                with st.chat_message("assistant"):
                    st.warning("Set your Anthropic API key in Settings to use the chat.")

    # ── Category Cards from Cache ─────────────────────────────────────
    st.divider()

    # Claude preventive actions — reads from cache instead of computing inline
    @st.cache_data(ttl=300, show_spinner=False)
    def _get_claude_preventive_actions(_month_key: str):
        """Cache Claude's preventive actions for 5 minutes to avoid repeated API calls."""
        advisor = get_advisor()
        if not advisor:
            return {}
        _conn = get_conn()
        cats_payload = []
        _mb = database.get_monthly_category_breakdown(_conn, _month_key)
        for cd in _mb:
            c = cd["category"]
            _actual_spend = abs(cd.get("total", 0))
            if _actual_spend == 0:
                continue
            t = analytics_cache.get_cached_trend(_conn, c) or _default_trend_dict
            _avg = float(t.get("mean", 0))
            _pct = ((_actual_spend / _avg) - 1) * 100 if _avg > 0 else 0
            entry = {
                "category": c,
                "current_spend": _actual_spend,  # Use selected month's actual spend
                "historical_avg": _avg,
                "historical_std": float(t.get("std", 0)),
                "trend_direction": t.get("direction", "stable"),
                "slope_per_month": float(t.get("slope_per_month", 0)),
                "pct_vs_mean": _pct,  # Recomputed from actual spend
                "severity": "critical" if _pct > 115 else ("warning" if _pct > 100 else t.get("severity", "normal")),
                "merchants": [],
            }
            # Current month merchants (from DB, not stale cache)
            _cur_merchants = database.get_merchant_breakdown_for_month(_conn, c, _month_key, limit=5)
            if _cur_merchants:
                entry["merchants"] = [m["name"] for m in _cur_merchants]
                entry["merchant_details"] = [
                    {"name": m["name"], "total": abs(m["total"]), "visits": m["visits"],
                     "avg_per_visit": round(abs(m["total"]) / max(m["visits"], 1), 2)}
                    for m in _cur_merchants
                ]
            # Cached Prophet forecast
            cached_pf = analytics_cache.get_cached_prophet(_conn, c)
            if cached_pf and cached_pf.get("forecast"):
                entry["prophet_forecast"] = cached_pf["forecast"]
                entry["prophet_trend"] = cached_pf.get("trend_direction", "")
                entry["prophet_slope"] = cached_pf.get("trend_slope_monthly", 0)
            # Cached advanced analytics
            cached_adv = analytics_cache.get_cached_advanced(_conn, c)
            if cached_adv:
                mk = cached_adv.get("mann_kendall", {})
                entry["mann_kendall_trend"] = mk.get("trend", "")
                entry["mann_kendall_strength"] = mk.get("strength", "")
                entry["mann_kendall_p"] = mk.get("p_value", 1.0)
                seas = cached_adv.get("seasonality", {})
                entry["seasonal"] = seas.get("has_seasonality", False)
                entry["seasonal_strength"] = seas.get("seasonal_strength", 0)
                entry["seasonal_period"] = seas.get("period", 0)
            cats_payload.append(entry)
        _conn.close()

        try:
            actions = advisor.generate_preventive_actions(cats_payload)
            return {a["category"]: a for a in actions if isinstance(a, dict) and "category" in a}
        except Exception:
            return {}

    # Only call Claude if we have an API key
    claude_actions = {}
    advisor = get_advisor()
    if advisor:
        with st.spinner("Analyzing trends & generating preventive actions..."):
            claude_actions = _get_claude_preventive_actions(selected_month)

    # Helper: build a category card reading from cache
    def _render_category_card(cat_data, trend_d, severity_info, expanded_default=False):
        """Render a single category card. `trend_d` is a dict from cache."""
        cat = cat_data["category"]
        spent = abs(cat_data["total"])
        count = cat_data["txn_count"]
        sev = severity_info
        t_direction = trend_d.get("direction", "stable")
        t_current = spent  # Use SELECTED month's actual spend, not cached latest
        t_mean = float(trend_d.get("mean", 0))
        t_std = float(trend_d.get("std", 0))
        t_slope = float(trend_d.get("slope_per_month", 0))
        t_pct = ((t_current / t_mean) - 1) * 100 if t_mean > 0 else 0  # Recompute from actual spend
        t_action = trend_d.get("action", "")

        direction_icon = direction_icons.get(t_direction, "→")
        pct_str = f"+{t_pct:.0f}%" if t_pct > 0 else f"{t_pct:.0f}%"

        # Card class, icon, and bar — ALL use the same color logic
        fill_pct = min(120, spent / t_mean * 100) if t_mean > 0 else 50
        if fill_pct > 115:
            card_class = "cat-card-critical"
            sev = severity_map["critical"]
            bar_color = PALETTE["red"]
        elif fill_pct > 100:
            card_class = "cat-card-warning"
            sev = severity_map["warning"]
            bar_color = PALETTE["amber"]
        elif fill_pct < 75:
            card_class = "cat-card-good"
            sev = {"icon": "🟢", "color": PALETTE["green"], "label": "On Track"}
            bar_color = PALETTE["green"]
        else:
            card_class = "cat-card-good"
            sev = {"icon": "🟢", "color": PALETTE["green"], "label": "On Track"}
            bar_color = PALETTE["green"]

        # Prophet forecast inline — from cache
        prophet_line = ""
        cached_pf = analytics_cache.get_cached_prophet(conn, cat)
        if cached_pf and cached_pf.get("forecast"):
            next_mo = cached_pf["forecast"][0]
            fc_icon = "↑" if next_mo["predicted"] > t_current else "↓"
            prophet_line = f'<div style="font-size:0.78rem; color:#7c3aed; margin-top:3px;">🔮 Forecast: <b>${next_mo["predicted"]:,.0f}</b> next month {fc_icon}</div>'

        _card_html = (
            f'<div class="cat-card {card_class}">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">'
            f'<span style="font-weight:700;font-size:1rem;">{sev["icon"]} {cat}</span>'
            f'<span style="font-weight:700;font-size:1.1rem;color:{sev["color"]};">${spent:,.0f}</span>'
            f'</div>'
            f'<div class="budget-bar"><div class="budget-fill" style="width:{min(fill_pct, 100):.0f}%;background:{bar_color};"></div></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:0.8rem;color:#6b7280;margin-top:2px;">'
            f'<span>{direction_icon} {pct_str} vs avg (${t_mean:,.0f})</span>'
            f'<span>{count} transactions</span>'
            f'</div>'
            f'{prophet_line}'
            f'</div>'
        )
        st.markdown(_card_html, unsafe_allow_html=True)

        # Expandable: history chart + Prophet forecast + merchants + advanced + action
        with st.expander("Trend, Forecast & Action Plan", expanded=expanded_default):
            history = database.get_category_monthly_history(conn, cat, months=12)

            if len(history) >= 2:
                hist_df = pd.DataFrame(list(reversed(history)))
                hist_df["total"] = hist_df["total"].abs()

                fig = go.Figure()

                # Historical spending line
                fig.add_trace(go.Scatter(
                    x=hist_df["month"], y=hist_df["total"], mode="lines+markers",
                    name="Actual", line=dict(color=sev["color"], width=2.5),
                    marker=dict(size=7, color=sev["color"]),
                    hovertemplate="<b>%{x}</b><br>Actual: $%{y:,.0f}<extra></extra>",
                ))

                # Prophet forecast overlay from cache — connected to last actual
                if cached_pf and cached_pf.get("forecast"):
                    last_actual_month = hist_df["month"].iloc[-1]
                    last_actual_val = hist_df["total"].iloc[-1]

                    fc_months = [last_actual_month] + [f["month"] for f in cached_pf["forecast"]]
                    fc_vals = [last_actual_val] + [f["predicted"] for f in cached_pf["forecast"]]
                    fc_lower = [last_actual_val] + [f["lower"] for f in cached_pf["forecast"]]
                    fc_upper = [last_actual_val] + [f["upper"] for f in cached_pf["forecast"]]

                    # Confidence band (connected from last actual)
                    fig.add_trace(go.Scatter(
                        x=fc_months + fc_months[::-1],
                        y=fc_upper + fc_lower[::-1],
                        fill="toself", fillcolor="rgba(139,92,246,0.12)",
                        line=dict(width=0), showlegend=True, name="80% CI",
                        hoverinfo="skip",
                    ))
                    # Forecast line (connected from last actual)
                    fig.add_trace(go.Scatter(
                        x=fc_months, y=fc_vals, mode="lines+markers",
                        name="Prophet Forecast",
                        line=dict(color=PALETTE["purple"], width=2, dash="dash"),
                        marker=dict(size=7, symbol="diamond", color=PALETTE["purple"]),
                        hovertemplate="<b>%{x}</b><br>Forecast: $%{y:,.0f}<extra></extra>",
                    ))

                # Average line
                avg = hist_df["total"].mean()
                fig.add_hline(y=avg, line_dash="dot", line_color=PALETTE["gray"],
                             annotation_text=f"avg ${avg:,.0f}", annotation_font_size=9)

                compact_layout = {**CHART_LAYOUT, "margin": dict(t=15, b=25, l=50, r=15)}
                fig.update_layout(**compact_layout, height=220,
                                 legend=dict(orientation="h", yanchor="bottom", y=1.02, font_size=9),
                                 xaxis=dict(showgrid=False),
                                 yaxis=dict(gridcolor="#f3f4f6", tickformat="$,.0f"))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            # Stats + merchants + advanced analytics + action in columns
            col_info, col_action = st.columns([1, 1])

            with col_info:
                st.markdown(f"**Trend:** {t_direction.title()} at \\${abs(t_slope):,.0f}/mo")
                st.markdown(f"**This month:** \\${t_current:,.0f} | **Avg:** \\${t_mean:,.0f} ± \\${t_std:,.0f}")

                # Merchant impact — current month spend per merchant (from DB)
                _month_merchants = database.get_merchant_breakdown_for_month(conn, cat, selected_month, limit=6)
                if _month_merchants:
                    import re as _re
                    m_entries = []
                    for _fbm in _month_merchants:
                        name = _fbm["name"] or ""
                        name = _re.sub(r'[A-Z0-9]{8,}', '', name).strip()
                        name = _re.sub(r'\s+', ' ', name).strip().rstrip(',').strip()
                        if name and len(name) > 2:
                            name = name.title() if name.isupper() else name
                            m_entries.append((name[:25], abs(_fbm["total"])))
                    if m_entries:
                        m_names = [e[0] for e in m_entries]
                        m_vals = [e[1] for e in m_entries]
                        _vibrant = ["#7c3aed", "#2563eb", "#059669", "#d97706", "#dc2626", "#ec4899"]
                        m_colors = [_vibrant[i % len(_vibrant)] for i in range(len(m_names))]
                        st.markdown("**Top merchants this month:**")
                        fig_m = go.Figure(go.Bar(
                            x=m_vals[::-1], y=m_names[::-1], orientation="h",
                            marker_color=m_colors[::-1],
                            text=[f"${v:,.0f}" for v in m_vals[::-1]],
                            textposition="auto", textfont=dict(color="white", size=11),
                            hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
                        ))
                        fig_m.update_layout(
                            margin=dict(t=5, b=5, l=5, r=5), height=max(80, len(m_names) * 30 + 20),
                            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                            yaxis=dict(autorange=True),
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(size=11),
                        )
                        st.plotly_chart(fig_m, use_container_width=True, config={"displayModeBar": False})

                # Advanced analytics — plain English from cache
                cached_adv = analytics_cache.get_cached_advanced(conn, cat)
                if cached_adv:
                    mk = cached_adv.get("mann_kendall", {})
                    mk_trend = mk.get("trend", "")
                    mk_strength = mk.get("strength", "none")

                    if mk_trend and mk_trend != "insufficient_data" and mk_strength != "none":
                        # Plain English trend description
                        if mk_strength == "strong":
                            trend_desc = f"Spending is **clearly {'rising' if mk_trend == 'increasing' else 'falling'}** over recent months"
                        elif mk_strength == "moderate":
                            trend_desc = f"Spending shows a **moderate {'upward' if mk_trend == 'increasing' else 'downward'}** trend"
                        else:
                            trend_desc = f"There's a **slight {'upward' if mk_trend == 'increasing' else 'downward'}** tendency"
                        st.caption(trend_desc)

                    seas = cached_adv.get("seasonality", {})
                    if seas.get("has_seasonality") and seas.get("strength", 0) > 0.1:
                        s_period = seas.get("period", 0)
                        if s_period == 3:
                            st.caption("This category has a **quarterly spending pattern** — expect ups and downs every ~3 months")
                        elif s_period == 12:
                            st.caption("This category follows a **yearly cycle** — compare to the same month last year for a better picture")
                        else:
                            st.caption(f"This category shows a **repeating pattern** every ~{s_period} months")

            with col_action:
                # Claude-driven preventive action (reads cache data)
                ca = claude_actions.get(cat)
                if ca:
                    sev_icon = {"critical": "🔴", "warning": "🟠", "good": "🟢"}.get(ca.get("severity", "stable"), "🔵")
                    st.markdown(escape_dollars(f"**{sev_icon} {ca.get('headline', '')}**"))

                    if ca.get("severity") in ("critical", "warning"):
                        st.error(escape_dollars(ca.get("action", "")))
                    elif ca.get("severity") == "good":
                        st.success(escape_dollars(ca.get("action", "")))
                    else:
                        st.info(escape_dollars(ca.get("action", "")))

                    if ca.get("forecast_note"):
                        st.caption(escape_dollars(f"🔮 {ca['forecast_note']}"))

                    impact = ca.get("impact", 0)
                    if impact:
                        st.markdown(f"**Impact:** \\${impact:,.0f}/mo toward your savings target")
                else:
                    # Fallback: regression-based action when Claude unavailable
                    if t_action:
                        st.info(f"**{t_action}**")
                    # Prophet forecast note from cache
                    if cached_pf and cached_pf.get("forecast"):
                        next_p = cached_pf["forecast"][0]["predicted"]
                        st.caption(f"🔮 Forecast: \\${next_p:,.0f} next month")

    # ── Three-tier card ordering ───────────────────────────────────
    # Sort ALL categories using the SAME fill_pct logic as card colors
    red_cats = []
    yellow_cats = []
    green_cats = []

    for cat_data in month_breakdown:
        cat = cat_data["category"]
        spent = abs(cat_data["total"])
        td = trend_results.get(cat, _default_trend_dict)
        t_mean = float(td.get("mean", 0))

        # Same threshold as card color logic
        fill_pct = (spent / t_mean * 100) if t_mean > 0 else 50
        excess = spent - t_mean

        if fill_pct > 115:
            red_cats.append((cat_data, td, excess))
        elif fill_pct > 100:
            yellow_cats.append((cat_data, td, excess))
        else:
            green_cats.append((cat_data, td, excess))

    # Sort: RED/YELLOW by highest excess first; GREEN by highest spend first
    red_cats.sort(key=lambda x: -x[2])
    yellow_cats.sort(key=lambda x: -x[2])
    green_cats.sort(key=lambda x: -abs(x[0]["total"]))

    # ── RED: full-width, auto-expanded ────────────────────────────────
    if red_cats:
        st.markdown("#### ⚠ Needs Attention")
        for cat_data, td, _ in red_cats:
            sev = severity_map.get(td.get("severity", "normal"), severity_map["normal"])
            _render_category_card(cat_data, td, sev, expanded_default=True)

    # ── YELLOW: 2-column grid, collapsed ──────────────────────────────
    if yellow_cats:
        st.markdown("#### 👀 Monitor")
        cols = st.columns(2)
        for i, (cat_data, td, _) in enumerate(yellow_cats):
            sev = severity_map.get(td.get("severity", "normal"), severity_map["normal"])
            with cols[i % 2]:
                _render_category_card(cat_data, td, sev, expanded_default=False)

    # ── GREEN: 2-column grid, collapsed ───────────────────────────────
    if green_cats:
        st.markdown("#### ✅ On Track")
        cols = st.columns(2)
        for i, (cat_data, td, _) in enumerate(green_cats):
            sev = severity_map.get(td.get("severity", "normal"), severity_map["normal"])
            with cols[i % 2]:
                _render_category_card(cat_data, td, sev, expanded_default=False)

    # Monthly comparison donut chart
    st.divider()
    st.markdown(f"#### Where the Tracked ${total_spent:,.0f} Went")
    top_cats = month_breakdown[:10]
    fig = go.Figure(go.Pie(
        labels=[c["category"] for c in top_cats],
        values=[abs(c["total"]) for c in top_cats],
        hole=0.45, textinfo="label+percent", textfont_size=10,
        marker=dict(colors=CATEGORY_PALETTE[:len(top_cats)]),
        hovertemplate="%{label}<br>$%{value:,.0f} (%{percent})<extra></extra>",
    ))
    fig.update_layout(**CHART_LAYOUT, height=400, showlegend=False,
                     annotations=[dict(text=f"<b>${total_spent:,.0f}</b>",
                                      x=0.5, y=0.5, font_size=16, showarrow=False)])
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# PAGE: TRANSACTIONS (with Upload Statements integrated)
# ═══════════════════════════════════════════════════════════════════════════
elif page == "Transactions":
    st.markdown("## Transactions")
    conn = get_conn()
    txn_count = database.get_transaction_count(conn)

    # ── Upload Statements (expander) ─────────────────────────────────
    _upload_expanded = txn_count == 0
    with st.expander("Upload Statements", expanded=_upload_expanded):
        # ── Coverage heatmap ──────────────────────────────────────────────────
        coverage = database.get_account_coverage(conn)
        if coverage:
            # Build month range from earliest to latest across all accounts
            all_months_covered = set()
            all_earliest, all_latest = None, None
            for info in coverage.values():
                if info.get("months_covered"):
                    all_months_covered.update(info["months_covered"])
                if info.get("earliest"):
                    if all_earliest is None or info["earliest"] < all_earliest:
                        all_earliest = info["earliest"]
                if info.get("latest"):
                    if all_latest is None or info["latest"] > all_latest:
                        all_latest = info["latest"]

            # Generate full month range
            all_months_range = []
            if all_earliest and all_latest:
                cur_d = date.fromisoformat(all_earliest).replace(day=1)
                end_d = date.fromisoformat(all_latest).replace(day=1)
                while cur_d <= end_d:
                    all_months_range.append(cur_d.strftime("%Y-%m"))
                    if cur_d.month == 12:
                        cur_d = cur_d.replace(year=cur_d.year + 1, month=1)
                    else:
                        cur_d = cur_d.replace(month=cur_d.month + 1)

            if all_months_range:
                # Build heatmap data: rows = accounts, cols = months
                all_acct_ids = list(config.ACCOUNTS.keys())
                acct_labels = [config.ACCOUNTS[a]["label"] for a in all_acct_ids]
                z_data = []
                total_cells = 0
                filled_cells = 0
                for acct_id in all_acct_ids:
                    row = []
                    acct_months = set(coverage.get(acct_id, {}).get("months_covered", []))
                    for m in all_months_range:
                        total_cells += 1
                        if m in acct_months:
                            row.append(1)
                            filled_cells += 1
                        else:
                            row.append(0)
                    z_data.append(row)

                # Month labels for x-axis (short form)
                month_labels = [datetime.strptime(m, "%Y-%m").strftime("%b %y") for m in all_months_range]

                completeness_pct = (filled_cells / total_cells * 100) if total_cells > 0 else 0

                st.markdown("#### Coverage Heatmap")
                st.caption(f"**{completeness_pct:.0f}%** complete ({filled_cells} of {total_cells} account-months)")

                fig_heat = go.Figure(data=go.Heatmap(
                    z=z_data,
                    x=month_labels,
                    y=acct_labels,
                    colorscale=[[0, '#ef4444'], [1, '#22c55e']],
                    showscale=True,
                    colorbar=dict(
                        title="", tickvals=[0, 1], ticktext=["Missing", "Has Data"],
                        len=0.5, thickness=12,
                    ),
                    hovertemplate="<b>%{y}</b><br>%{x}<br>%{customdata}<extra></extra>",
                    customdata=[["Has data" if cell == 1 else "Missing" for cell in row] for row in z_data],
                    xgap=3, ygap=4,
                ))
                # Show every 3rd month label to reduce crowding
                tick_interval = max(1, len(month_labels) // 15)
                fig_heat.update_layout(
                    **CHART_LAYOUT,
                    height=max(180, 55 * len(all_acct_ids)),
                    xaxis=dict(side="top", tickangle=-45, dtick=tick_interval),
                    yaxis=dict(autorange="reversed"),
                )
                st.plotly_chart(fig_heat, use_container_width=True, config={"displayModeBar": False})

                # Missing months — actionable items
                missing_months = database.get_missing_months(conn)
                if missing_months:
                    with st.expander(f"Missing months ({len(missing_months)})", expanded=len(missing_months) <= 6):
                        for item in missing_months:
                            label = config.ACCOUNTS.get(item["account_id"], {}).get("label", item["account_id"])
                            ym = datetime.strptime(item["year_month"], "%Y-%m").strftime("%B %Y")
                            st.markdown(f"- Upload **{label}** for **{ym}**")
            else:
                st.info("No statements yet. Drop your first PDF or CSV below.")
        else:
            st.info("No statements yet. Drop your first PDF or CSV below.")

        st.divider()

        # ── File uploader ─────────────────────────────────────────────────────
        uploaded_files = st.file_uploader(
            "Drop PDF or CSV statements",
            type=["pdf", "csv"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        if uploaded_files:
            advisor = get_advisor()
            existing_stmts = database.get_all_statements(conn)
            existing_periods = [
                {"account_id": s["account_id"], "period_start": s["period_start"], "period_end": s["period_end"]}
                for s in existing_stmts
            ]

            for uploaded_file in uploaded_files:
                st.divider()
                file_bytes = uploaded_file.read()
                file_hash = pdf_parser.compute_bytes_hash(file_bytes)
                is_csv = uploaded_file.name.lower().endswith(".csv")

                st.markdown(f"#### {uploaded_file.name}")

                # STEP 1: Detect account + period
                if is_csv:
                    with st.spinner("Analyzing CSV..."):
                        detected_account = csv_parser.identify_account_from_csv(file_bytes, uploaded_file.name)
                        try:
                            quick_result = csv_parser.parse_chase_csv(file_bytes, account_hint=detected_account)
                            period_start = quick_result.get("period_start")
                            period_end = quick_result.get("period_end")
                        except Exception as e:
                            st.error(f"CSV parsing failed: {e}")
                            continue
                    detection_reasons = ["Transaction pattern analysis" if detected_account else ""]
                    page_count = None
                    is_checking = detected_account == "joint_checking"
                else:
                    with st.spinner("Scanning PDF..."):
                        analysis = pdf_parser.analyze_upload(file_bytes, uploaded_file.name)
                        detected_account = analysis["detected_account"]
                        period_start = analysis["period_start"]
                        period_end = analysis["period_end"]
                        detection_reasons = analysis["detection_reasons"]
                        page_count = analysis["page_count"]
                        is_checking = analysis["is_checking"]

                # Account confirmation
                acct_label = config.ACCOUNTS.get(detected_account, {}).get("label", "Unknown")
                account_options = list(config.ACCOUNTS.keys())
                default_idx = account_options.index(detected_account) if detected_account in account_options else 0
                account_id = st.selectbox(
                    "Confirm account:",
                    account_options,
                    index=default_idx,
                    format_func=lambda x: f"{config.ACCOUNTS[x]['label']} ({config.ACCOUNTS[x]['owner']})",
                    key=f"acct_{uploaded_file.name}",
                )

                # STEP 2: Period check
                if period_start and period_end:
                    upload_status = database.classify_upload(conn, account_id, period_start, period_end, file_hash)
                else:
                    upload_status = {"status": "new", "message": "Period unknown — importing all.", "action": "import", "new_transactions_likely": True}

                status_colors = {"new": "success", "extends": "info", "duplicate_file": "error", "duplicate_period": "warning", "overlapping": "warning"}
                getattr(st, status_colors.get(upload_status["status"], "info"))(upload_status["message"])

                # Warn if statement is old (> 12 months)
                _old_statement = False
                if period_start and period_start != "unknown":
                    try:
                        _ps = date.fromisoformat(period_start)
                        _age_days = (date.today() - _ps).days
                        if _age_days > 365:
                            st.warning(f"This statement is from **{period_start}** ({_age_days // 30} months ago). "
                                       f"Old data may reduce forecast accuracy. Transactions older than 18 months will be skipped.")
                            _old_statement = True
                    except (ValueError, TypeError):
                        pass

                if upload_status["action"] == "skip":
                    continue

                should_proceed = True
                if upload_status["action"] == "ask_user":
                    should_proceed = st.checkbox("Import anyway? (duplicates auto-skipped)", key=f"force_{uploaded_file.name}")
                if not should_proceed:
                    continue

                # STEP 3: Extract transactions
                if is_csv:
                    result = quick_result
                    result["account_id"] = account_id
                else:
                    # Check if this is a Chase Spending Report (instant parsing, no Claude needed)
                    is_spending_report = chase_report_parser.is_spending_report(analysis["raw_text"])

                    if is_spending_report:
                        with st.spinner("Parsing Chase Spending Report (instant)..."):
                            try:
                                result = chase_report_parser.parse_spending_report(
                                    file_bytes, uploaded_file.name, raw_text=analysis["raw_text"]
                                )
                                result["account_id"] = account_id
                            except Exception as e:
                                st.error(f"Spending report parsing failed: {e}")
                                continue
                    elif is_checking:
                        # Chase Checking Statement — direct regex parsing (instant, no Claude)
                        with st.spinner("Parsing Chase Checking Statement (instant)..."):
                            try:
                                result = chase_report_parser.parse_checking_statement(
                                    file_bytes, uploaded_file.name,
                                    raw_text=analysis["raw_text"],
                                    period_start=period_start or "",
                                    period_end=period_end or "",
                                )
                                result["account_id"] = account_id
                            except Exception as e:
                                st.error(f"Checking statement parsing failed: {e}")
                                continue
                    else:
                        # Regular PDF statement — needs Claude
                        if not advisor:
                            st.error("Set your Anthropic API key in Settings to process PDFs.")
                            continue
                        with st.spinner("Claude is extracting transactions..."):
                            try:
                                result = advisor.extract_transactions(
                                    raw_text=analysis["raw_text"], tables=analysis["tables"],
                                    account_hint=account_id, existing_periods=existing_periods,
                                    is_checking=is_checking,
                                    categories=category_engine.get_active_categories(conn),
                                )
                            except Exception as e:
                                st.error(f"Extraction failed: {e}")
                                continue

                    if not period_start:
                        period_start = result.get("period_start", "")
                    if not period_end:
                        period_end = result.get("period_end", "")

                # STEP 4: Auto-import transactions
                transactions = result.get("transactions", [])
                if not transactions:
                    st.warning("No transactions found.")
                    continue

                # Normalize all dates to YYYY-MM-DD before saving
                year_hint = (period_start or "")[:4] if period_start and period_start != "unknown" else ""
                transactions = normalize_transactions(transactions, year_hint)
                period_start = normalize_date(period_start or "unknown", year_hint)
                period_end = normalize_date(period_end or "unknown", year_hint)

                # Date validation: reject transactions with invalid/missing dates
                import re as _re
                valid_txns = []
                bad_dates = 0
                for txn in transactions:
                    d = txn.get("date", "")
                    if d and d != "unknown" and _re.match(r'^\d{4}-\d{2}-\d{2}$', d):
                        valid_txns.append(txn)
                    else:
                        bad_dates += 1
                if bad_dates > 0:
                    st.warning(f"Skipped {bad_dates} transactions with invalid dates.")
                transactions = valid_txns

                # Auto-import (skip if already imported on a previous rerun)
                if database.check_duplicate_statement(conn, file_hash):
                    st.info(f"Already imported: **{uploaded_file.name}** ({len(transactions)} transactions)")
                    continue

                stmt_id = database.insert_statement(
                    conn, uploaded_file.name, account_id,
                    period_start, period_end, file_hash,
                    notes=f"Status: {upload_status['status']}",
                )
                for txn in transactions:
                    txn["account_id"] = account_id
                    txn["statement_id"] = stmt_id

                inserted = database.bulk_insert_transactions(conn, transactions)
                database.update_statement_txn_count(conn, stmt_id, inserted)
                skipped = len(transactions) - inserted

                # Invalidate analytics cache after successful import
                analytics_cache.invalidate(conn)
                st.session_state['analytics_stale'] = True

                # Auto-fix: if period is still unknown, derive from actual transaction dates
                if not period_start or period_start == "unknown" or not period_end or period_end == "unknown":
                    date_row = conn.execute(
                        "SELECT MIN(date) as d1, MAX(date) as d2 FROM transactions WHERE statement_id = ?",
                        (stmt_id,),
                    ).fetchone()
                    if date_row and date_row["d1"] and date_row["d1"] != "unknown":
                        conn.execute(
                            "UPDATE statements SET period_start = ?, period_end = ? WHERE id = ?",
                            (date_row["d1"], date_row["d2"], stmt_id),
                        )
                        conn.commit()

                # ── Clean upload summary ──────────────────────────────────────
                charges = sum(t["amount"] for t in transactions if t["amount"] < 0)
                credits_total = sum(t["amount"] for t in transactions if t["amount"] > 0)
                final_label = config.ACCOUNTS.get(account_id, {}).get("label", account_id)
                period_display = f"{period_start} to {period_end}" if period_start and period_end else "Unknown period"
                dup_note = f" (skipped {skipped} duplicates)" if skipped > 0 else ""

                with st.container():
                    st.success(
                        f"**{final_label}** | {period_display} | "
                        f"**{inserted}** transactions imported{dup_note} | "
                        f"Charges: \\${abs(charges):,.2f}"
                    )
                    if result.get("analysis_notes"):
                        st.caption(result["analysis_notes"])

                    # Category breakdown (collapsed)
                    from collections import Counter
                    cat_counts = Counter(t["category"] for t in transactions if t["amount"] < 0)
                    cat_totals = {}
                    for t in transactions:
                        if t["amount"] < 0:
                            cat_totals[t["category"]] = cat_totals.get(t["category"], 0) + abs(t["amount"])
                    with st.expander(f"Category breakdown ({len(cat_counts)} categories)"):
                        for cat, total in sorted(cat_totals.items(), key=lambda x: -x[1]):
                            st.write(f"**{cat}**: \\${total:,.2f} ({cat_counts[cat]} txns)")

    # If no transactions after upload section, stop here
    txn_count = database.get_transaction_count(conn)
    if txn_count == 0:
        st.info("No transactions yet. Upload a statement above to get started.")
        conn.close()
        st.stop()

    active_categories = category_engine.get_active_categories(conn)

    tab_txns, tab_analysis, tab_recat = st.tabs(["Transactions", "Category Analysis", "Recategorize"])

    # ── Tab 1: Transaction Browser ──────────────────────────────────────
    with tab_txns:
        date_range = database.get_date_range(conn)
        _fc1, _fc2 = st.columns(2)
        with _fc1:
            start = st.date_input("From", value=date.fromisoformat(date_range[0]) if date_range[0] else date.today() - timedelta(days=90))
        with _fc2:
            end = st.date_input("To", value=date.fromisoformat(date_range[1]) if date_range[1] else date.today())
        _fc3, _fc4 = st.columns(2)
        with _fc3:
            acct = st.selectbox("Account", ["All"] + list(config.ACCOUNTS.keys()))
        with _fc4:
            cat = st.selectbox("Category", ["All"] + active_categories)

        # Exclude non-spending categories by default
        _exclude_cats = {"Transfers & Payments", "Credit Card Payments"}
        hide_transfers = st.checkbox("Hide transfers & CC payments", value=True)

        txns = database.get_transactions(
            conn, start_date=start.isoformat(), end_date=end.isoformat(),
            account_id=acct if acct != "All" else None,
            category=cat if cat != "All" else None,
        )
        if txns:
            df = pd.DataFrame([dict(t) for t in txns])
            if hide_transfers and cat == "All":
                df = df[~df["category"].isin(_exclude_cats)]
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Spent", f"${abs(df[df['amount']<0]['amount'].sum()):,.0f}")
            c2.metric("Credits", f"${df[df['amount']>0]['amount'].sum():,.0f}")
            c3.metric("Count", len(df))

            st.dataframe(
                df[["date", "description", "amount", "category", "account_id"]].rename(
                    columns={"date": "Date", "description": "Description", "amount": "Amount", "category": "Category", "account_id": "Account"}
                ),
                use_container_width=True, hide_index=True, height=500,
            )

            csv_data = df.to_csv(index=False)
            st.download_button("Export CSV", csv_data, "transactions.csv", "text/csv")
        else:
            st.info("No transactions match these filters.")

    # ── Tab 2: Category Analysis ────────────────────────────────────────
    with tab_analysis:
        # Category stats summary
        cat_stats = category_engine.get_category_stats(conn)
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Category Coverage", f"{cat_stats['coverage_pct']}%")
        sc2.metric("Uncategorized (Other)", f"{cat_stats['other_count']} txns ({cat_stats['other_pct']}%)")
        sc3.metric("Low Confidence", f"{cat_stats['low_confidence_count']} txns ({cat_stats['low_confidence_pct']}%)")

        st.markdown(f"**{cat_stats['coverage_pct']}%** of spending transactions are categorized. "
                    f"**{cat_stats['other_count']}** transactions remain as 'Other'.")

        # Treemap — only show active categories (respects recategorization)
        st.markdown("#### Category Distribution")
        _active_cats = category_engine.get_active_categories(conn)
        _active_placeholder = ",".join(f"'{c}'" for c in _active_cats)
        cat_rows = conn.execute(f"""
            SELECT category, COUNT(*) as txn_count, ABS(SUM(amount)) as total_spend
            FROM transactions WHERE amount < 0 AND category IN ({_active_placeholder})
            GROUP BY category ORDER BY total_spend DESC
        """).fetchall()

        if cat_rows:
            cat_df = pd.DataFrame([dict(r) for r in cat_rows])
            fig_tree = px.treemap(
                cat_df, path=["category"], values="total_spend",
                color="total_spend", color_continuous_scale="Blues",
                hover_data={"txn_count": True, "total_spend": ":.2f"},
            )
            fig_tree.update_layout(**CHART_LAYOUT, height=450, coloraxis_showscale=False)
            fig_tree.update_traces(
                textinfo="label+value",
                texttemplate="%{label}<br>$%{value:,.0f}",
                hovertemplate="<b>%{label}</b><br>Spend: $%{value:,.0f}<br>Transactions: %{customdata[0]}<extra></extra>",
            )
            st.plotly_chart(fig_tree, use_container_width=True, config={"displayModeBar": False})

        # Stacked area chart — category evolution over time
        st.markdown("#### Category Trends Over Time")
        monthly_cat_rows = conn.execute(f"""
            SELECT strftime('%Y-%m', date) as month, category, ABS(SUM(amount)) as total
            FROM transactions WHERE amount < 0 AND category IN ({_active_placeholder})
            GROUP BY month, category ORDER BY month
        """).fetchall()

        if monthly_cat_rows:
            mc_df = pd.DataFrame([dict(r) for r in monthly_cat_rows])
            # Keep top categories, group rest into "Other (small)"
            top_cats = mc_df.groupby("category")["total"].sum().nlargest(10).index.tolist()
            mc_df["category_display"] = mc_df["category"].apply(lambda x: x if x in top_cats else "Other (small)")
            mc_agg = mc_df.groupby(["month", "category_display"])["total"].sum().reset_index()

            fig_area = px.area(
                mc_agg, x="month", y="total", color="category_display",
                color_discrete_sequence=CATEGORY_PALETTE,
                labels={"month": "Month", "total": "Spend", "category_display": "Category"},
            )
            fig_area.update_layout(
                **CHART_LAYOUT, height=400,
                xaxis_title=None, yaxis_title="Monthly Spend",
                legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig_area, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Not enough data for trend analysis.")

    # ── Tab 3: Recategorize ─────────────────────────────────────────────
    with tab_recat:
        st.markdown("#### Manage Categories")

        # Initialize session state
        if "recat_proposals" not in st.session_state:
            st.session_state.recat_proposals = None
        if "recat_applied" not in st.session_state:
            st.session_state.recat_applied = None

        # ── Step 1: Current categories (editable) ─────────────────────
        st.markdown("##### Current Categories")
        st.caption("Edit names, add rows, or delete rows. Changes take effect when you click 'Save Categories'.")

        # Load current categories into an editable dataframe
        current_cats = category_engine.get_active_categories(conn)
        cat_hierarchy = category_engine.get_category_hierarchy(conn)
        edit_data = []
        for c in current_cats:
            info = cat_hierarchy.get(c, {})
            edit_data.append({"Category": c, "Description": info.get("description", ""), "Keep": True})

        edit_df = pd.DataFrame(edit_data)
        edited = st.data_editor(
            edit_df,
            num_rows="dynamic",  # Allow adding new rows
            use_container_width=True,
            hide_index=True,
            column_config={
                "Category": st.column_config.TextColumn("Category", width="medium"),
                "Description": st.column_config.TextColumn("Description", width="large"),
                "Keep": st.column_config.CheckboxColumn("Keep", default=True, width="small"),
            },
        )

        col_save, col_reset = st.columns(2)
        with col_save:
            if st.button("Save Categories", type="primary"):
                # Apply edits: keep only checked rows, save to DB
                kept = edited[edited["Keep"] == True]
                saved_count = 0
                for _, row in kept.iterrows():
                    name = str(row["Category"]).strip()
                    desc = str(row["Description"]).strip() if pd.notna(row["Description"]) else ""
                    if name:
                        database.upsert_category_definition(conn, name=name, description=desc, sort_order=saved_count + 1)
                        saved_count += 1
                # Deactivate unchecked categories
                removed = edited[edited["Keep"] == False]
                for _, row in removed.iterrows():
                    name = str(row["Category"]).strip()
                    if name:
                        conn.execute("UPDATE category_definitions SET is_active = 0 WHERE name = ?", (name,))
                conn.commit()
                analytics_cache.invalidate(conn)
                st.success(f"Saved {saved_count} categories. New uploads will use these categories.")
                st.rerun()

        with col_reset:
            if st.button("Reset to Default"):
                conn.execute("DELETE FROM category_definitions")
                conn.commit()
                analytics_cache.invalidate(conn)
                st.success("Reset to default categories.")
                st.rerun()

        st.divider()

        # ── Step 2: Ask Claude for suggestions ─────────────────────────
        st.markdown("##### Ask Claude for Suggestions")
        st.caption("Claude will analyze your spending patterns and suggest an optimal category structure.")

        guide_text = st.text_area(
            "Guide Claude (optional)",
            placeholder="e.g., I don't want Transfers & Payments. Split Costco into groceries vs non-food. Merge small categories.",
            height=80,
        )

        if st.button("Get Suggestions from Claude"):
            advisor = get_advisor()
            if advisor is None:
                st.error("Claude API key not configured.")
            else:
                with st.spinner("Claude is analyzing your transactions..."):
                    try:
                        result = category_engine.generate_categories(conn, advisor, user_guidance=guide_text)
                        # If user provided guidance, add it to result for display
                        if guide_text:
                            result["user_guidance"] = guide_text
                        st.session_state.recat_proposals = result
                        st.session_state.recat_applied = None
                    except Exception as e:
                        st.error(f"Failed: {e}")
                        st.caption("Try again — Claude sometimes needs a second attempt.")

        if st.session_state.recat_proposals is not None:
            result = st.session_state.recat_proposals

            if result.get("changes_summary"):
                st.info(f"**Claude's suggestion:** {result['changes_summary']}")

            proposed = result.get("proposed_categories", [])
            if proposed:
                st.markdown(f"**Proposed ({len(proposed)} categories):**")
                prop_df = pd.DataFrame(proposed)
                display_cols = [c for c in ["name", "description"] if c in prop_df.columns]
                if display_cols:
                    st.dataframe(
                        prop_df[display_cols].rename(columns={"name": "Category", "description": "Description"}),
                        use_container_width=True, hide_index=True,
                    )

            rename_mapping = result.get("rename_mapping", {})
            if rename_mapping:
                st.markdown(f"**Renames:** {len(rename_mapping)} categories")
                for old, new in rename_mapping.items():
                    st.caption(f"{old} → **{new}**")

            tags = result.get("subcategory_tags", [])
            if tags:
                st.caption(f"Suggested tags: {', '.join(tags)}")

            col_apply, col_clear = st.columns(2)
            with col_apply:
                if st.session_state.recat_applied is None:
                    if st.button("Apply Claude's Suggestions", type="primary"):
                        with st.spinner("Applying..."):
                            applied = category_engine.apply_recategorization(conn, result)
                            st.session_state.recat_applied = applied
                        st.rerun()
                else:
                    st.success(
                        f"Applied! {st.session_state.recat_applied['categories_created']} categories created, "
                        f"{st.session_state.recat_applied['transactions_updated']} transactions updated."
                    )
            with col_clear:
                if st.button("Dismiss"):
                    st.session_state.recat_proposals = None
                    st.session_state.recat_applied = None
                    st.rerun()

    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# PAGE: INSIGHTS & ADVISOR
# ═══════════════════════════════════════════════════════════════════════════
elif page == "Insights & Advisor":
    import analytics

    st.markdown("## Insights & Advisor")
    conn = get_conn()

    tab_cashflow, tab_forecast, tab_goals, tab_scenarios, tab_advisor = st.tabs([
        "Cash Flow", "Forecasts", "Goals", "Scenarios", "AI Advisor"
    ])

    # ── Cash Flow tab ─────────────────────────────────────────────────
    with tab_cashflow:
        df = models.project_cash_flow()
        savings_target = int(database.get_setting(conn, "monthly_savings_target", "1000"))
        savings_status = models.compute_savings_status(conn, savings_target)

        # Summary metrics — 2 columns, 2 rows
        _r1c1, _r1c2 = st.columns(2)
        _r1c1.metric("Savings Target", f"\\${savings_target:,}/mo")
        _r1c2.metric("Current Avg Net", f"\\${savings_status['actual_avg_net']:,.0f}/mo",
                  delta="On track" if savings_status["on_track"] else f"\\${savings_status['current_gap']:,.0f} short",
                  delta_color="normal" if savings_status["on_track"] else "inverse")
        _r2c1, _r2c2 = st.columns(2)
        _r2c1.metric("Projected Avg Net", f"\\${savings_status['projected_avg_net']:,.0f}/mo")
        _r2c2.metric("Months Analyzed", savings_status["months_analyzed"])

        st.plotly_chart(make_monthly_net_chart(df, height=300), use_container_width=True, config={"displayModeBar": False})
        st.plotly_chart(make_cumulative_chart(df, height=370), use_container_width=True, config={"displayModeBar": False})

    # ── Forecasts tab ─────────────────────────────────────────────────
    with tab_forecast:
        st.markdown("#### ML Spending Forecast (Facebook Prophet)")
        forecast_conn = get_conn()
        try:
            prophet_result = analytics.prophet_forecast_total_spending(forecast_conn, periods=6)
            if prophet_result:
                # Historical + forecast chart
                hist_rows = forecast_conn.execute("""
                    SELECT strftime('%Y-%m', date) as month,
                           SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) as spending
                    FROM transactions GROUP BY month ORDER BY month
                """).fetchall()
                hist_months = [r["month"] for r in hist_rows]
                hist_vals = [abs(r["spending"]) for r in hist_rows if r["spending"]]

                fig = go.Figure()
                # Historical
                fig.add_trace(go.Scatter(
                    x=hist_months, y=hist_vals, mode="lines+markers",
                    name="Actual", line=dict(color=PALETTE["blue"], width=2),
                    marker=dict(size=6),
                    hovertemplate="<b>%{x}</b><br>Actual: $%{y:,.0f}<extra></extra>",
                ))
                # Forecast — bridge from last actual point
                last_hist_month = hist_months[-1] if hist_months else None
                last_hist_val = hist_vals[-1] if hist_vals else 0

                fc_months = ([last_hist_month] if last_hist_month else []) + [f["month"] for f in prophet_result["forecast"]]
                fc_vals = ([last_hist_val] if last_hist_month else []) + [f["predicted"] for f in prophet_result["forecast"]]
                fc_lower = ([last_hist_val] if last_hist_month else []) + [f["lower"] for f in prophet_result["forecast"]]
                fc_upper = ([last_hist_val] if last_hist_month else []) + [f["upper"] for f in prophet_result["forecast"]]

                # Confidence band (connected from last actual)
                fig.add_trace(go.Scatter(
                    x=fc_months + fc_months[::-1],
                    y=fc_upper + fc_lower[::-1],
                    fill="toself", fillcolor="rgba(139,92,246,0.12)",
                    line=dict(width=0), showlegend=True, name="80% confidence",
                    hoverinfo="skip",
                ))
                fig.add_trace(go.Scatter(
                    x=fc_months, y=fc_vals, mode="lines+markers",
                    name="Prophet Forecast", line=dict(color=PALETTE["purple"], width=2.5, dash="dash"),
                    marker=dict(size=7, symbol="diamond"),
                    hovertemplate="<b>%{x}</b><br>Forecast: $%{y:,.0f}<extra></extra>",
                ))
                # Average line
                avg = prophet_result["historical_avg"]
                fig.add_hline(y=avg, line_dash="dot", line_color=PALETTE["gray"],
                             annotation_text=f"Historical avg: ${avg:,.0f}", annotation_font_size=9)

                fig.update_layout(**CHART_LAYOUT, height=360,
                                 legend=dict(orientation="h", yanchor="bottom", y=1.02, font_size=10),
                                 yaxis=dict(title="Monthly Spending ($)", gridcolor="#f3f4f6", tickformat="$,.0f"),
                                 xaxis=dict(gridcolor="#f3f4f6"))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                c1, c2, c3 = st.columns(3)
                c1.metric("Model Accuracy (MAPE)", f"{prophet_result['mape']:.1f}%")
                c2.metric("Data Points", prophet_result["data_points"])
                next_fc = prophet_result["forecast"][0]
                c3.metric(f"Next Month ({next_fc['month']})",
                          f"${next_fc['predicted']:,.0f}",
                          delta=f"${next_fc['predicted'] - avg:+,.0f} vs avg")
            else:
                st.info("Need at least 4 months of data for Prophet forecasting. Upload more statements.")
        except Exception as e:
            st.caption(f"Prophet forecast unavailable: {e}")
        forecast_conn.close()

    # ── Goals tab ─────────────────────────────────────────────────────
    with tab_goals:
        goals_conn = get_conn()
        objectives = database.get_active_objectives(goals_conn)

        for obj in objectives:
            target = obj["target"] or 0
            if target > 0:
                current = 0
                pct = min(1.0, max(0.0, current / target)) if target > 0 else 0
                st.progress(pct, text=f"**{obj['label']}**: ${current:,.0f} / ${target:,.0f} ({pct*100:.0f}%)")
            else:
                st.write(f"**{obj['label']}**: {obj['description'] or ''}")

        st.divider()
        st.markdown("#### Add Goal")
        with st.form("new_goal"):
            label = st.text_input("Goal name", placeholder="e.g., Emergency fund $10k")
            target = st.number_input("Target ($)", min_value=0, value=0, step=500)
            deadline = st.date_input("Deadline", value=None)
            if st.form_submit_button("Create", type="primary") and label:
                oid = label.lower().replace(" ", "_")[:30]
                database.create_objective(goals_conn, oid, label, target=target if target > 0 else None,
                                         deadline=deadline.isoformat() if deadline else None)
                st.rerun()
        goals_conn.close()

    # ── Scenarios tab ─────────────────────────────────────────────────
    with tab_scenarios:
        st.markdown("#### What-If Scenarios")
        st.caption("Adjust the sliders to see how spending cuts change your trajectory.")

        scenario_df = models.project_cash_flow()
        savings_target = int(database.get_setting(conn, "monthly_savings_target", "1000"))
        savings_status = models.compute_savings_status(conn, savings_target)

        c1, c2 = st.columns(2)
        with c1:
            dining_cut = st.slider("Dining cut $/mo", 0, 500, 92, 10)
            costco_cut = st.slider("Costco cut $/mo", 0, 500, 200, 10)
            clothing_cut = st.slider("Clothing cut $/mo", 0, 400, 167, 10)
        with c2:
            amazon_cut = st.slider("Amazon cut $/mo", 0, 300, 60, 10)
            home_cut = st.slider("Home improvement cut $/mo", 0, 300, 135, 10)

        total_cut = dining_cut + costco_cut + clothing_cut + amazon_cut + home_cut

        adjustments = {"dining": -dining_cut, "costco": -costco_cut, "clothing": -clothing_cut, "amazon": -amazon_cut, "home": -home_cut}
        scenario_result = models.scenario_model(scenario_df, adjustments)

        # Impact summary — 2 columns, 2 rows
        new_net = savings_status["projected_avg_net"] + total_cut
        meets_target = new_net >= savings_target

        _si1, _si2 = st.columns(2)
        _si1.metric("Monthly Cuts", f"\\${total_cut:,}/mo")
        _si2.metric("New Monthly Net", f"\\${new_net:,.0f}/mo",
                  delta=f"+\\${total_cut:,} vs current")
        _si3, _si4 = st.columns(2)
        _si3.metric("Target Status", "Met" if meets_target else f"\\${savings_target - new_net:,.0f} short",
                  delta="On track" if meets_target else "Needs more cuts",
                  delta_color="normal" if meets_target else "inverse")
        annual_impact = total_cut * 12
        _si4.metric("Annual Impact", f"\\${annual_impact:,}")

        # Comparison chart
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=scenario_df["month"], y=scenario_df["cumulative"], mode="lines", name="Current Path",
            line=dict(color=PALETTE["gray"], dash="dash", width=2),
            hovertemplate="Current: $%{y:,.0f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=scenario_result["month"], y=scenario_result["cumulative"], mode="lines", name="With Cuts",
            line=dict(color=PALETTE["green"], width=3),
            fill="tonexty", fillcolor="rgba(34,197,94,0.06)",
            hovertemplate="Scenario: $%{y:,.0f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_color=PALETTE["gray_light"], line_width=1)
        fig.update_layout(**CHART_LAYOUT, height=420,
                         legend=dict(orientation="h", yanchor="bottom", y=1.02),
                         yaxis=dict(title="Cumulative Savings ($)", gridcolor="#f3f4f6", tickformat="$,.0f"),
                         xaxis=dict(gridcolor="#f3f4f6", dtick="M6"))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── AI Advisor tab ────────────────────────────────────────────────
    with tab_advisor:
        advisor = get_advisor()
        if not advisor:
            st.error("Set your Anthropic API key in Settings.")
        else:
            financial_context = database.get_financial_context(conn)
            tactical_context = None
            try:
                tactical_context = spending_intelligence.build_tactical_context(conn)
            except Exception:
                pass

            if not st.session_state.chat_history:
                db_history = database.get_conversation(conn, st.session_state.session_id)
                if db_history:
                    st.session_state.chat_history = db_history
                else:
                    with st.spinner("Claude is reviewing your finances..."):
                        try:
                            welcome = advisor.get_welcome_message(financial_context)
                            st.session_state.chat_history.append({"role": "assistant", "content": welcome})
                            database.save_conversation(conn, st.session_state.session_id, "assistant", welcome)
                        except Exception:
                            st.session_state.chat_history.append({"role": "assistant", "content": "Hello! Upload some statements and let's review your spending."})

            # Quick actions — 2 columns, 2 rows
            _qa1, _qa2 = st.columns(2)
            quick = {
                "Savings Check": "Savings Check: Am I on track to meet my savings target? Show me the numbers.",
                "Save This Week": "What are 3 specific things I can do THIS WEEK to save money?",
                "Spending Check": "Compare this month to our average. What's over budget?",
                "Where to Cut": "Where are the easiest $300/month in cuts?",
            }
            _quick_items = list(quick.items())
            if _qa1.button(_quick_items[0][0], use_container_width=True):
                st.session_state.chat_history.append({"role": "user", "content": _quick_items[0][1]})
                database.save_conversation(conn, st.session_state.session_id, "user", _quick_items[0][1])
                st.session_state["_pending_advisor_msg"] = _quick_items[0][1]
                st.rerun()
            if _qa2.button(_quick_items[1][0], use_container_width=True):
                st.session_state.chat_history.append({"role": "user", "content": _quick_items[1][1]})
                database.save_conversation(conn, st.session_state.session_id, "user", _quick_items[1][1])
                st.session_state["_pending_advisor_msg"] = _quick_items[1][1]
                st.rerun()
            _qa3, _qa4 = st.columns(2)
            if _qa3.button(_quick_items[2][0], use_container_width=True):
                st.session_state.chat_history.append({"role": "user", "content": _quick_items[2][1]})
                database.save_conversation(conn, st.session_state.session_id, "user", _quick_items[2][1])
                st.session_state["_pending_advisor_msg"] = _quick_items[2][1]
                st.rerun()
            if _qa4.button(_quick_items[3][0], use_container_width=True):
                st.session_state.chat_history.append({"role": "user", "content": _quick_items[3][1]})
                database.save_conversation(conn, st.session_state.session_id, "user", _quick_items[3][1])
                st.session_state["_pending_advisor_msg"] = _quick_items[3][1]
                st.rerun()

            # Display chat history (escape $ at display time only)
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    display_text = escape_dollars(msg["content"]) if msg["role"] == "assistant" else msg["content"]
                    st.markdown(display_text)

            # Check if there's an unanswered user message (from quick action or previous rerun)
            needs_response = (
                st.session_state.chat_history
                and st.session_state.chat_history[-1]["role"] == "user"
            )

            def _get_response(user_msg):
                """Call Claude and return response text."""
                try:
                    result = advisor.get_advisor_response(
                        user_message=user_msg,
                        conversation_history=st.session_state.chat_history[:-1],
                        financial_context=financial_context,
                        tactical_context=tactical_context,
                    )
                    text = result.get("response", str(result))
                    return text  # Return raw — escaping happens at display time
                except Exception as e:
                    err = str(e)
                    if "credit balance" in err.lower() or "billing" in err.lower():
                        return "**API credits exhausted.** Please add credits at [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing) to continue using the advisor."
                    return f"**Error:** {err[:200]}. Please try again."

            if needs_response:
                pending_msg = st.session_state.chat_history[-1]["content"]
                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        text = _get_response(pending_msg)
                    st.markdown(escape_dollars(text))
                    st.session_state.chat_history.append({"role": "assistant", "content": text})
                    database.save_conversation(conn, st.session_state.session_id, "assistant", text)

            # Chat input
            user_input = st.chat_input("Ask your advisor...")
            if user_input:
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                database.save_conversation(conn, st.session_state.session_id, "user", user_input)
                with st.chat_message("user"):
                    st.markdown(user_input)
                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        text = _get_response(user_input)
                    st.markdown(escape_dollars(text))
                    st.session_state.chat_history.append({"role": "assistant", "content": text})
                    database.save_conversation(conn, st.session_state.session_id, "assistant", text)

    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# PAGE: SETTINGS
# ═══════════════════════════════════════════════════════════════════════════
elif page == "Settings":
    st.markdown("## Settings")
    conn = get_conn()

    # API Key
    st.markdown("#### Claude API")
    current_key = os.environ.get("ANTHROPIC_API_KEY", "") or database.get_setting(conn, "anthropic_api_key")
    if current_key:
        st.success(f"API key: ...{current_key[-8:]}")
        if st.button("Clear API Key"):
            database.delete_setting(conn, "anthropic_api_key")
            os.environ.pop("ANTHROPIC_API_KEY", None)
            st.session_state.advisor = None
            st.rerun()
    else:
        new_key = st.text_input("Anthropic API Key", type="password")
        if st.button("Save Key") and new_key:
            database.set_setting(conn, "anthropic_api_key", new_key)
            os.environ["ANTHROPIC_API_KEY"] = new_key
            st.session_state.advisor = None
            st.rerun()

    st.divider()

    # Database
    st.markdown("#### Database")
    txn_count = database.get_transaction_count(conn)
    stmts = database.get_all_statements(conn)
    st.write(f"**{txn_count:,}** transactions | **{len(stmts)}** statements | `{DB_PATH}`")

    if stmts:
        stmt_data = [{"Account": config.ACCOUNTS.get(s["account_id"], {}).get("label", s["account_id"]),
                      "Period": f"{s['period_start']} — {s['period_end']}",
                      "Txns": s["transaction_count"], "File": s["filename"]} for s in stmts]
        st.dataframe(pd.DataFrame(stmt_data), use_container_width=True, hide_index=True)

    st.divider()

    # ── Savings & Reporting ──────────────────────────────────────────
    st.markdown("#### Savings & Reporting")
    _set_c1, _set_c2 = st.columns(2)
    _cur_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))
    _new_target = _set_c1.number_input("Monthly Savings Target ($/mo)", min_value=0, max_value=10000, value=_cur_target, step=100, key="settings_savings_target")
    if _new_target != _cur_target:
        database.set_setting(conn, "monthly_savings_target", str(_new_target))

    _period_opts = ["weekly", "biweekly", "monthly"]
    _cur_period = database.get_setting(conn, "report_period", "weekly")
    _p_idx = _period_opts.index(_cur_period) if _cur_period in _period_opts else 0
    _new_period = _set_c2.selectbox("Report Frequency", _period_opts, index=_p_idx,
        format_func=lambda x: {"weekly": "Every Week", "biweekly": "Every 2 Weeks", "monthly": "Monthly"}[x], key="settings_report_period")
    if _new_period != _cur_period:
        database.set_setting(conn, "report_period", _new_period)

    st.divider()

    # ── Income Configuration ──────────────────────────────────────────
    st.markdown("#### Income")
    _inc_c1, _inc_c2 = st.columns(2)

    with _inc_c1:
        st.markdown("**Kero (Premera)**")
        _k_bi = st.number_input("Biweekly take-home", value=config.INCOME["kero"]["biweekly_net"], step=50, key="kero_biweekly")
        _k_bonus = st.number_input("Annual bonus (after tax)", value=config.INCOME["kero"]["bonus_annual_after_tax"], step=500, key="kero_bonus_annual")

    with _inc_c2:
        st.markdown("**Maggie (Boeing)**")
        _m_bi = st.number_input("Biweekly take-home", value=config.INCOME["maggie"]["biweekly_net"], step=50, key="maggie_biweekly")
        _m_bonus = st.number_input("Annual bonus (after tax)", value=config.INCOME["maggie"]["bonus_annual_after_tax"], step=500, key="maggie_bonus_annual")

    # Show computed monthly totals
    _k_monthly = round(_k_bi * 26 / 12)
    _m_monthly = round(_m_bi * 26 / 12)
    _k_bonus_spread = round(_k_bonus / 12)
    _m_bonus_spread = round(_m_bonus / 12)
    _combined = _k_monthly + _k_bonus_spread + _m_monthly + _m_bonus_spread
    st.caption(f"Monthly: Kero ${_k_monthly:,} + ${_k_bonus_spread:,} bonus | Maggie ${_m_monthly:,} + ${_m_bonus_spread:,} bonus | **Combined: ${_combined:,}/mo**")

    if st.button("Save Income Changes", key="save_income"):
        config.INCOME["kero"]["biweekly_net"] = _k_bi
        config.INCOME["kero"]["monthly_net"] = _k_monthly
        config.INCOME["kero"]["bonus_annual_after_tax"] = _k_bonus
        config.INCOME["kero"]["bonus_spread_monthly"] = _k_bonus_spread
        config.INCOME["maggie"]["biweekly_net"] = _m_bi
        config.INCOME["maggie"]["monthly_net"] = _m_monthly
        config.INCOME["maggie"]["bonus_annual_after_tax"] = _m_bonus
        config.INCOME["maggie"]["bonus_spread_monthly"] = _m_bonus_spread
        config.INCOME["combined_monthly_take_home"] = _combined
        # Persist to DB so it survives restarts
        import json as _json
        database.set_setting(conn, "income_config", _json.dumps(config.INCOME))
        st.success(f"Income updated! Combined: ${_combined:,}/mo")

    st.divider()

    # ── Fixed Monthly Expenses ────────────────────────────────────────
    st.markdown("#### Fixed Monthly Expenses")
    _exp_changes = {}
    _exp_cols = st.columns(2)
    _items = list(config.FIXED_MONTHLY_EXPENSES.items())
    _half = (len(_items) + 1) // 2
    for col_idx, col in enumerate(_exp_cols):
        with col:
            _slice = _items[col_idx * _half:(col_idx + 1) * _half]
            for _label, _amt in _slice:
                _short = _label.split("(")[0].strip()[:30]
                _new_val = st.number_input(_short, value=_amt, step=10, key=f"fixed_{_label}")
                if _new_val != _amt:
                    _exp_changes[_label] = _new_val

    _new_fixed_total = sum(_exp_changes.get(k, v) for k, v in config.FIXED_MONTHLY_EXPENSES.items())
    st.caption(f"**Total fixed: ${_new_fixed_total:,}/mo**")

    if _exp_changes and st.button("Save Expense Changes", key="save_expenses"):
        for _label, _val in _exp_changes.items():
            config.FIXED_MONTHLY_EXPENSES[_label] = _val
        import json as _json
        database.set_setting(conn, "fixed_expenses_config", _json.dumps(config.FIXED_MONTHLY_EXPENSES))
        st.success(f"Expenses updated! Total fixed: ${_new_fixed_total:,}/mo")

    st.divider()

    # ── Claude Auto-Update ────────────────────────────────────────────
    st.markdown("#### Auto-Update with Claude")
    st.caption("Claude will analyze your recent transactions and suggest updates to income and expenses.")
    if st.button("Ask Claude to Review My Settings", key="claude_auto_settings"):
        advisor = get_advisor()
        if advisor:
            with st.spinner("Claude is analyzing your transactions..."):
                # Build context from recent transaction data
                _recent_txns = conn.execute("""
                    SELECT date, description, amount, category FROM transactions
                    WHERE date >= date('now', '-90 days') ORDER BY date DESC
                """).fetchall()
                _txn_text = "\n".join(f"{t['date']} | {t['description']} | ${t['amount']:,.2f} | {t['category']}" for t in _recent_txns[:200])

                _prompt = (
                    f"Analyze my last 90 days of transactions and tell me if my budget config is accurate.\n\n"
                    f"CURRENT CONFIG:\n"
                    f"- Kero biweekly: ${config.INCOME['kero']['biweekly_net']:,}\n"
                    f"- Maggie biweekly: ${config.INCOME['maggie']['biweekly_net']:,}\n"
                    f"- Fixed expenses total: ${sum(config.FIXED_MONTHLY_EXPENSES.values()):,}/mo\n"
                    f"- Mortgage: ${config.FIXED_MONTHLY_EXPENSES.get('Mortgage (Mr. Cooper 6.49%)', 0):,}\n"
                    f"- Car loan: ${config.FIXED_MONTHLY_EXPENSES.get('Auto Loan (Chase #2102)', 0):,}\n"
                    f"- Internet: ${config.FIXED_MONTHLY_EXPENSES.get('Internet (Comcast/Xfinity)', 0):,}\n"
                    f"- Phone: ${config.FIXED_MONTHLY_EXPENSES.get('T-Mobile', 0):,}\n\n"
                    f"RECENT TRANSACTIONS:\n{_txn_text}\n\n"
                    f"For each config value, tell me: is it correct based on the data? If not, what should it be? "
                    f"Focus on payroll amounts, recurring bills, and any expenses that changed recently."
                )
                try:
                    result = advisor.get_advisor_response(
                        user_message=_prompt,
                        conversation_history=[],
                        financial_context={"month": "settings_review"},
                        tactical_context={},
                    )
                    response = result.get("response", str(result))
                    st.markdown(escape_dollars(response))
                except Exception as e:
                    st.error(f"Failed: {e}")
        else:
            st.warning("Set your API key above first.")

    st.divider()

    # ── Weekly Reports & Telegram ─────────────────────────────────────
    st.markdown("#### Weekly Reports & Telegram")

    with st.expander("Weekly Report", expanded=False):
        import analytics as _rpt_analytics
        from collections import Counter as _rpt_Counter

        _rpt_advisor = get_advisor()
        data = reports.gather_report_data(conn)
        week_total = abs(data["week_spending_total"])
        week_txns = data["week_transactions"]

        if not week_txns:
            st.info("No transactions this week. Upload a statement to generate a report.")
        else:
            # ── HEADER: Savings target + week summary ──────────────────
            header_col1, header_col2 = st.columns([2, 1])
            with header_col1:
                from calendar import month_name as _mname
                today = date.today()
                st.markdown(f"### Week of {data['week_start']} to {data['report_date']}")
            with header_col2:
                _rpt_savings_target = int(database.get_setting(conn, "monthly_savings_target", "1000"))
                st.metric("Savings Target", f"${_rpt_savings_target:,}/mo")

            # ── SECTION 1: Week at a Glance ───────────────────────────────
            st.markdown("#### This Week at a Glance")

            # Compare to last week
            last_week_txns = database.get_transactions(
                conn,
                start_date=(date.today() - timedelta(days=14)).isoformat(),
                end_date=(date.today() - timedelta(days=7)).isoformat(),
            )
            last_week_total = abs(sum(t["amount"] for t in last_week_txns if t["amount"] < 0))
            wow_change = week_total - last_week_total if last_week_total > 0 else 0

            _wc1, _wc2 = st.columns(2)
            _wc1.metric("Total Spent", f"\\${week_total:,.0f}")
            _wc2.metric("vs Last Week", f"\\${abs(wow_change):,.0f}",
                      delta=f"{'↑' if wow_change > 0 else '↓'} \\${abs(wow_change):,.0f}",
                      delta_color="inverse" if wow_change > 0 else "normal")
            _wc3, _wc4 = st.columns(2)
            _wc3.metric("Transactions", len(week_txns))
            _wc4.metric("Avg per Txn", f"\\${week_total / max(len(week_txns), 1):,.0f}")

            # ── SECTION 2: Top Categories This Week ───────────────────────
            st.markdown("#### Spending Breakdown")
            cat_totals = {}
            cat_counts = _rpt_Counter()
            for t in week_txns:
                if t["amount"] < 0 and t["category"] in category_engine.get_active_categories(conn):
                    cat = t["category"]
                    cat_totals[cat] = cat_totals.get(cat, 0) + abs(t["amount"])
                    cat_counts[cat] += 1
            sorted_cats = sorted(cat_totals.items(), key=lambda x: -x[1])

            if sorted_cats:
                cats_list = [c[0] for c in sorted_cats[:10]]
                vals_list = [c[1] for c in sorted_cats[:10]]
                fig = go.Figure(go.Bar(
                    x=vals_list, y=cats_list, orientation="h",
                    marker_color=CATEGORY_PALETTE[:len(cats_list)],
                    text=[f"${v:,.0f}" for v in vals_list],
                    textposition="auto",
                    hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
                ))
                fig.update_layout(**CHART_LAYOUT, height=max(250, len(cats_list) * 35 + 80),
                                 showlegend=False, yaxis=dict(autorange="reversed"),
                                 xaxis=dict(title="Amount ($)", gridcolor="#f3f4f6", tickformat="$,.0f"))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            # ── SECTION 3: Big Charges ────────────────────────────────────
            big_charges = [t for t in week_txns if t["amount"] < -150]
            if big_charges:
                st.markdown("#### Notable Charges (> \\$150)")
                for t in sorted(big_charges, key=lambda x: x["amount"]):
                    st.markdown(f"- **\\${abs(t['amount']):,.0f}** — {t['description']} ({t['category']}) on {t['date']}")

            # ── SECTION 4: Prophet Forecasts — Preventive Actions ─────────
            st.divider()
            st.markdown("#### Next Month Preview — Preventive Actions")
            st.caption("Prophet ML forecasts based on your spending history. Act now to prevent overspending.")

            forecast_cats = sorted_cats[:8] if sorted_cats else []
            rising_forecasts = []
            falling_forecasts = []

            for cat_name, cat_spent in forecast_cats:
                try:
                    pf = _rpt_analytics.prophet_forecast_category(conn, cat_name, periods=1)
                    if not pf or not pf["forecast"]:
                        continue
                    predicted = pf["forecast"][0]["predicted"]
                    avg = pf.get("historical_avg", 0)
                    if avg <= 0:
                        continue
                    diff = predicted - avg
                    pct_diff = (diff / avg) * 100
                    entry = {"cat": cat_name, "predicted": predicted, "avg": avg,
                             "diff": diff, "pct": pct_diff, "month": pf["forecast"][0]["month"]}
                    if pct_diff > 10:
                        rising_forecasts.append(entry)
                    elif pct_diff < -10:
                        falling_forecasts.append(entry)
                except Exception:
                    pass

            if rising_forecasts:
                for f in sorted(rising_forecasts, key=lambda x: -x["diff"]):
                    st.error(
                        f"**{f['cat']}** — Forecast: **\\${f['predicted']:,.0f}** for {f['month']} "
                        f"(\\${f['diff']:+,.0f} vs avg \\${f['avg']:,.0f}). "
                        f"**Cut back now** to prevent this from happening."
                    )
            if falling_forecasts:
                for f in sorted(falling_forecasts, key=lambda x: x["diff"]):
                    st.success(
                        f"**{f['cat']}** — Trending down to **\\${f['predicted']:,.0f}** "
                        f"(saving \\${abs(f['diff']):,.0f}/mo vs avg). Keep it up!"
                    )
            if not rising_forecasts and not falling_forecasts:
                st.info("All categories forecast within normal range for next month.")

            # ── SECTION 5: Savings Target Progress ───────────────────────
            st.divider()
            st.markdown("#### Savings Target Progress")
            _rpt_savings_target = int(database.get_setting(conn, "monthly_savings_target", "1000"))
            c1, c2, c3 = st.columns(3)
            c1.metric("Monthly Target", f"${_rpt_savings_target:,}/mo")
            c2.metric("This Week", f"${week_total:,.0f}")
            c3.metric("Transactions", len(week_txns))

            # ── SECTION 6: Claude's Analysis ──────────────────────────────
            if _rpt_advisor:
                st.divider()
                st.markdown("#### Claude's Take")
                if st.button("Get Claude's Analysis", type="primary"):
                    with st.spinner("Claude is analyzing your week..."):
                        try:
                            # Build a focused context for Claude
                            analysis_context = {
                                "week_total": week_total,
                                "last_week_total": last_week_total,
                                "wow_change": wow_change,
                                "top_categories": sorted_cats[:5],
                                "big_charges": [{"desc": t["description"], "amount": t["amount"],
                                                "category": t["category"]} for t in big_charges[:5]],
                                "rising_forecasts": rising_forecasts,
                                "falling_forecasts": falling_forecasts,
                                "savings_target": int(database.get_setting(conn, "monthly_savings_target", "1000")),
                            }

                            stat_ctx = None
                            try:
                                stat_ctx = _rpt_analytics.build_statistical_context(conn)
                            except Exception:
                                pass

                            report_result = _rpt_advisor.generate_weekly_report(
                                week_transactions=[dict(t) for t in week_txns[:30]],
                                monthly_context=data["mtd_summary"],
                                objective_progress=data["objective_progress"],
                                alerts=data["alerts"],
                                statistical_context=stat_ctx,
                            )

                            # Display Claude's insights
                            keep = report_result.get("keep", "")
                            stop = report_result.get("stop", "")
                            start = report_result.get("start", "")
                            actions = report_result.get("action_items", [])
                            concern = report_result.get("top_concern", "")
                            win = report_result.get("top_win", "")

                            if keep or stop or start:
                                k_col, s_col, st_col = st.columns(3)
                                with k_col:
                                    st.success(f"**KEEP**\n\n{keep}")
                                with s_col:
                                    st.error(f"**STOP**\n\n{stop}")
                                with st_col:
                                    st.info(f"**START**\n\n{start}")

                            if actions:
                                st.markdown("**This Week's Action Items:**")
                                for i, action in enumerate(actions[:3], 1):
                                    st.markdown(f"{i}. {action}")

                            if concern:
                                st.warning(f"**Top concern:** {concern}")
                            if win:
                                st.success(f"**Top win:** {win}")

                            # Save for future reference
                            plain = report_result.get("plain_text", "")
                            if plain:
                                database.save_weekly_report(
                                    conn, date.today().isoformat(),
                                    report_result.get("subject", "Weekly Report"),
                                    report_result.get("html_body", ""), plain,
                                )
                        except Exception as e:
                            st.error(f"Claude analysis failed: {e}")

            # ── Send to Telegram ──────────────────────────────────────────
            st.divider()
            bot_token = database.get_setting(conn, "telegram_bot_token")
            chat_id = database.get_setting(conn, "telegram_chat_id")
            if bot_token and chat_id:
                if st.button("Send Report to Telegram"):
                    with st.spinner("Generating report with forecasts..."):
                        try:
                            from telegram_bot import TelegramReporter, format_weekly_report_html
                            import chart_generator

                            # Build preventive actions with forecast data
                            data["preventive_actions"] = []
                            _active = category_engine.get_active_categories(conn)
                            for cat_name in _active[:10]:
                                try:
                                    pf = _rpt_analytics.prophet_forecast_category(conn, cat_name, periods=1)
                                    if pf and pf["forecast"]:
                                        predicted = pf["forecast"][0]["predicted"]
                                        avg = pf.get("historical_avg", 0)
                                        if avg > 0:
                                            diff = predicted - avg
                                            data["preventive_actions"].append({
                                                "category": cat_name, "predicted": predicted,
                                                "avg": avg, "diff": diff,
                                                "forecast": f"${predicted:,.0f} (avg ${avg:,.0f})",
                                            })
                                except Exception:
                                    pass

                            # Build red card data (categories over 115% of average)
                            _current_month = date.today().strftime("%Y-%m")
                            _mb = database.get_monthly_category_breakdown(conn, _current_month)
                            _active_for_report = category_engine.get_active_categories(conn)
                            _mb = [c for c in _mb if c["category"] in _active_for_report]

                            red_cards = []
                            for cd in _mb:
                                cat = cd["category"]
                                spent = abs(cd["total"])
                                t = analytics_cache.get_cached_trend(conn, cat)
                                if t:
                                    avg = float(t.get("mean", 0))
                                    if avg > 0 and spent > avg * 1.15:
                                        red_cards.append({
                                            "category": cat, "spent": spent, "avg": avg,
                                            "pct_above": (spent / avg - 1) * 100,
                                        })
                            red_cards.sort(key=lambda x: -x["pct_above"])

                            # Generate a chart image for each red card category
                            charts = []
                            for rc in red_cards[:3]:
                                try:
                                    cat = rc["category"]
                                    history = database.get_category_monthly_history(conn, cat, months=12)
                                    if len(history) >= 3:
                                        import plotly.graph_objects as _go
                                        hist_months = [h["month"] for h in reversed(history)]
                                        hist_vals = [abs(h["total"]) for h in reversed(history)]

                                        fig_rc = _go.Figure()
                                        fig_rc.add_trace(_go.Scatter(
                                            x=hist_months, y=hist_vals, mode="lines+markers",
                                            line=dict(color="#ef4444", width=3),
                                            marker=dict(size=8, color="#ef4444"),
                                        ))
                                        avg = rc["avg"]
                                        fig_rc.add_hline(y=avg, line_dash="dot", line_color="#94a3b8",
                                                        annotation_text=f"avg ${avg:,.0f}")
                                        fig_rc.update_layout(
                                            title=f"{cat}: ${rc['spent']:,.0f} (+{rc['pct_above']:.0f}% above avg)",
                                            title_font=dict(size=16, color="#ef4444"),
                                            margin=dict(t=50, b=30, l=50, r=30),
                                            height=300, width=600,
                                            yaxis=dict(tickformat="$,.0f"),
                                            paper_bgcolor="white", plot_bgcolor="white",
                                            font=dict(size=12),
                                        )
                                        import plotly.io as _pio
                                        png = _pio.to_image(fig_rc, format="png", width=600, height=300, scale=2)
                                        charts.append((png, f"{cat}: ${rc['spent']:,.0f}"))
                                except Exception:
                                    pass

                            # Generate Claude report for Telegram
                            _cached = analytics_cache.get_cached(conn)
                            _tg_report = None
                            try:
                                _tg_advisor = get_advisor()
                                if _tg_advisor:
                                    _tg_report = _tg_advisor.generate_weekly_report(
                                        week_transactions=data.get("week_transactions", []),
                                        monthly_context=data.get("mtd_summary"),
                                        objective_progress=data.get("objective_progress", {}),
                                        alerts=data.get("alerts", []),
                                    )
                            except Exception:
                                pass
                            summary = (_tg_report.get("plain_text", "") if _tg_report else "") or format_weekly_report_html(data, cached_analytics=_cached, red_cards=red_cards)
                            telegram = TelegramReporter(bot_token, chat_id)
                            telegram.send_weekly_report(summary, charts)
                            maggie_chat = database.get_setting(conn, "telegram_chat_id_maggie")
                            if maggie_chat and maggie_chat != chat_id:
                                TelegramReporter(bot_token, maggie_chat).send_weekly_report(summary, charts)
                            st.success("Sent to Kero & Maggie!")
                        except Exception as e:
                            st.error(f"Failed: {e}")

        # Past reports
        past = database.get_weekly_reports(conn)
        if past:
            st.divider()
            st.markdown("#### Past Reports")
            for r in past:
                with st.expander(f"{r['report_date']} — {r['subject'] or 'Weekly Report'}"):
                    st.markdown(r["plain_text"] or "")

    # ── Telegram Setup ────────────────────────────────────────────────
    st.markdown("##### Telegram Bot Setup")
    st.markdown("""
    1. Open Telegram, search **@BotFather**, send `/newbot`
    2. Copy the **bot token**
    3. Start a chat with your bot, send any message
    4. Get your chat ID: `https://api.telegram.org/bot<TOKEN>/getUpdates`
    """)

    token = st.text_input("Bot Token", value=database.get_setting(conn, "telegram_bot_token"), type="password")
    chat = st.text_input("Chat ID", value=database.get_setting(conn, "telegram_chat_id"))

    c1, c2 = st.columns(2)
    if c1.button("Save", key="save_telegram"):
        if token and chat:
            database.set_setting(conn, "telegram_bot_token", token)
            database.set_setting(conn, "telegram_chat_id", chat)
            st.success("Saved!")
    if c2.button("Test Connection", key="test_telegram"):
        if token:
            try:
                from telegram_bot import TelegramReporter
                bot = TelegramReporter(token, chat or "test")
                info = bot.test_connection()
                if info.get("ok"):
                    st.success(f"Connected: @{info['result']['username']}")
                    if chat:
                        bot.send_message("Connected! Your Budget Tracker is ready.")
            except Exception as e:
                st.error(f"Failed: {e}")

    st.divider()

    # ── Monarch Money Integration ────────────────────────────────────────
    st.markdown("#### Monarch Money")
    import monarch_sync

    _mm_enabled = database.get_setting(conn, "monarch_enabled", "0") == "1"
    _mm_stats = monarch_sync.get_sync_stats(conn)

    # Connection status
    if _mm_enabled and _mm_stats["last_sync"]:
        _sync_ago = ""
        try:
            _sync_dt = datetime.fromisoformat(_mm_stats["last_sync"])
            _sync_delta = datetime.now() - _sync_dt
            if _sync_delta.days > 0:
                _sync_ago = f"{_sync_delta.days}d ago"
            elif _sync_delta.seconds >= 3600:
                _sync_ago = f"{_sync_delta.seconds // 3600}h ago"
            else:
                _sync_ago = f"{_sync_delta.seconds // 60}m ago"
        except (ValueError, TypeError):
            _sync_ago = "unknown"
        st.success(f"Connected — {_mm_stats['transaction_count']:,} transactions synced (last: {_sync_ago})")
    elif _mm_enabled:
        st.info("Connected — no sync yet. Click **Sync Now** below.")
    else:
        st.info("Connect your Monarch Money account to auto-import transactions.")

    # Credentials
    with st.expander("Credentials", expanded=not _mm_enabled):
        _mm_email = database.get_setting(conn, "monarch_email", "")
        _mm_password = database.get_setting(conn, "monarch_password", "")

        _new_email = st.text_input("Monarch Email", value=_mm_email, key="mm_email")
        _new_password = st.text_input("Monarch Password", type="password",
                                       value=_mm_password if _mm_password else "",
                                       key="mm_password")

        _mm_device_uuid = database.get_setting(conn, "monarch_device_uuid", "")
        _new_device_uuid = st.text_input(
            "Device UUID",
            value=_mm_device_uuid,
            key="mm_device_uuid",
            help="Required: Open Monarch in browser → DevTools Console → run: localStorage.getItem('monarchDeviceUUID')",
        )
        if _new_device_uuid != _mm_device_uuid and _new_device_uuid:
            database.set_setting(conn, "monarch_device_uuid", _new_device_uuid)

        _mm_c1, _mm_c2 = st.columns(2)

        if _mm_c1.button("Connect to Monarch", key="mm_connect"):
            if _new_email and _new_password:
                database.set_setting(conn, "monarch_email", _new_email)
                database.set_setting(conn, "monarch_password", _new_password)
                with st.spinner("Authenticating..."):
                    try:
                        _mm_client = monarch_sync.get_client(conn)
                        database.set_setting(conn, "monarch_enabled", "1")
                        st.success("Connected to Monarch Money!")

                        # Auto-fetch accounts and suggest mapping
                        _mm_accounts = monarch_sync.fetch_accounts(_mm_client)
                        _suggested = monarch_sync.auto_suggest_mapping(_mm_accounts)
                        if _suggested:
                            monarch_sync.set_account_mapping(conn, _suggested)

                        # Auto-fetch categories and build default mapping
                        _mm_cats = monarch_sync.fetch_categories(_mm_client)
                        _default_cat_map = monarch_sync.build_default_category_mapping(_mm_cats)
                        monarch_sync.set_category_mapping(conn, _default_cat_map)

                        st.rerun()
                    except monarch_sync.MonarchEmailOTPRequired:
                        st.session_state.mm_email_otp_needed = True
                        st.rerun()
                    except monarch_sync.MonarchMFARequired:
                        st.session_state.mm_mfa_needed = True
                        st.rerun()
                    except monarch_sync.MonarchAuthFailed as e:
                        st.error(f"Authentication failed: {e}")
                    except Exception as e:
                        st.error(f"Connection error: {e}")
            else:
                st.warning("Enter both email and password.")

        if _mm_c2.button("Disconnect", key="mm_disconnect", disabled=not _mm_enabled):
            monarch_sync.disconnect()
            database.set_setting(conn, "monarch_enabled", "0")
            database.set_setting(conn, "monarch_email", "")
            database.set_setting(conn, "monarch_password", "")
            database.set_setting(conn, "monarch_last_sync", "")
            database.set_setting(conn, "monarch_account_map", "{}")
            database.set_setting(conn, "monarch_category_map", "{}")
            st.session_state.monarch_synced = False
            st.success("Disconnected from Monarch Money.")
            st.rerun()

        # Email OTP flow (Monarch sends a code to your email for device verification)
        if st.session_state.get("mm_email_otp_needed", False):
            st.warning("Monarch sent a verification code to your email. Check your inbox and enter it below.")
            _otp_code = st.text_input("Email Verification Code", key="mm_email_otp_code", max_chars=6)
            if st.button("Verify Code", key="mm_email_otp_verify"):
                if _otp_code:
                    try:
                        _mm_client = monarch_sync.complete_email_otp(conn, _otp_code)
                        database.set_setting(conn, "monarch_enabled", "1")
                        st.session_state.mm_email_otp_needed = False

                        # Auto-setup accounts and categories
                        _mm_accounts = monarch_sync.fetch_accounts(_mm_client)
                        _suggested = monarch_sync.auto_suggest_mapping(_mm_accounts)
                        if _suggested:
                            monarch_sync.set_account_mapping(conn, _suggested)
                        _mm_cats = monarch_sync.fetch_categories(_mm_client)
                        _default_cat_map = monarch_sync.build_default_category_mapping(_mm_cats)
                        monarch_sync.set_category_mapping(conn, _default_cat_map)

                        st.success("Verified! Connected to Monarch Money.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Verification failed: {e}")

        # MFA/TOTP flow
        if st.session_state.get("mm_mfa_needed", False):
            st.warning("Monarch Money requires a multi-factor authentication code.")
            _mfa_code = st.text_input("Enter MFA Code", key="mm_mfa_code", max_chars=6)
            if st.button("Verify MFA", key="mm_mfa_verify"):
                if _mfa_code:
                    try:
                        _mm_client = monarch_sync.complete_mfa(conn, _mfa_code)
                        database.set_setting(conn, "monarch_enabled", "1")
                        st.session_state.mm_mfa_needed = False

                        _mm_accounts = monarch_sync.fetch_accounts(_mm_client)
                        _suggested = monarch_sync.auto_suggest_mapping(_mm_accounts)
                        if _suggested:
                            monarch_sync.set_account_mapping(conn, _suggested)
                        _mm_cats = monarch_sync.fetch_categories(_mm_client)
                        _default_cat_map = monarch_sync.build_default_category_mapping(_mm_cats)
                        monarch_sync.set_category_mapping(conn, _default_cat_map)

                        st.success("MFA verified! Connected to Monarch Money.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"MFA verification failed: {e}")

    # Account mapping (only when connected)
    if _mm_enabled:
        with st.expander("Account Mapping"):
            _acct_map = monarch_sync.get_account_mapping(conn)
            _vw_options = ["-- Skip --"] + list(config.ACCOUNTS.keys())
            _vw_labels = {"-- Skip --": "-- Skip --"}
            for k, v in config.ACCOUNTS.items():
                _vw_labels[k] = f"{v['label']} ({v['owner']})"

            try:
                _mm_client = monarch_sync.get_client(conn)
                _mm_accounts = monarch_sync.fetch_accounts(_mm_client)
            except Exception:
                _mm_accounts = []
                st.warning("Could not fetch Monarch accounts. Try reconnecting.")

            if _mm_accounts:
                _new_map = {}
                for macct in _mm_accounts:
                    _current = _acct_map.get(macct["id"], "-- Skip --")
                    _idx = _vw_options.index(_current) if _current in _vw_options else 0
                    _label = f"{macct['institution']} — {macct['name']}"
                    if macct["mask"]:
                        _label += f" (...{macct['mask']})"
                    _label += f"  |  bal: ${macct['balance']:,.0f}"

                    _selected = st.selectbox(
                        _label,
                        _vw_options,
                        index=_idx,
                        format_func=lambda x: _vw_labels.get(x, x),
                        key=f"mm_acct_{macct['id']}",
                    )
                    if _selected != "-- Skip --":
                        _new_map[macct["id"]] = _selected

                if st.button("Save Account Mapping", key="mm_save_acct_map"):
                    monarch_sync.set_account_mapping(conn, _new_map)
                    st.success(f"Mapped {len(_new_map)} accounts.")

        # Category mapping
        with st.expander("Category Mapping"):
            _cat_map = monarch_sync.get_category_mapping(conn)
            _vw_cats = config.CATEGORIES

            if _cat_map:
                _new_cat_map = {}
                for mcat, vcat in sorted(_cat_map.items()):
                    _idx = _vw_cats.index(vcat) if vcat in _vw_cats else _vw_cats.index("Other")
                    _selected = st.selectbox(
                        mcat,
                        _vw_cats,
                        index=_idx,
                        key=f"mm_cat_{mcat}",
                    )
                    _new_cat_map[mcat] = _selected

                if st.button("Save Category Mapping", key="mm_save_cat_map"):
                    monarch_sync.set_category_mapping(conn, _new_cat_map)
                    st.success("Category mapping saved.")
            else:
                st.info("Connect and sync to see Monarch categories.")

        # Manual sync button
        _sync_c1, _sync_c2 = st.columns(2)
        if _sync_c1.button("Sync Now", key="mm_sync_now"):
            with st.spinner("Syncing transactions from Monarch..."):
                try:
                    _result = monarch_sync.sync_transactions(conn)
                    if _result["new"] > 0:
                        st.success(f"Imported {_result['new']} new transactions! ({_result['skipped']} duplicates skipped)")
                        st.session_state.monarch_synced = True
                    elif _result["errors"]:
                        st.warning(f"Sync issue: {_result['errors'][0]}")
                    else:
                        st.info(f"Already up to date ({_result['skipped']} duplicates skipped)")
                except Exception as e:
                    st.error(f"Sync failed: {e}")

        if _sync_c2.button("Full Re-sync", key="mm_full_sync", help="Re-fetch all history (ignores last sync date)"):
            with st.spinner("Full re-sync from Monarch..."):
                try:
                    _result = monarch_sync.sync_transactions(conn, force_full=True)
                    if _result["new"] > 0:
                        st.success(f"Imported {_result['new']} new transactions! ({_result['skipped']} duplicates skipped)")
                    else:
                        st.info(f"No new transactions ({_result['skipped']} duplicates skipped)")
                except Exception as e:
                    st.error(f"Full sync failed: {e}")

    st.divider()

    # Token usage
    advisor = get_advisor()
    if advisor:
        st.markdown("#### API Usage (this session)")
        usage = advisor.get_usage()
        c1, c2, c3 = st.columns(3)
        c1.metric("Input Tokens", f"{usage['total_input_tokens']:,}")
        c2.metric("Output Tokens", f"{usage['total_output_tokens']:,}")
        c3.metric("Cost", f"${usage['estimated_cost']:.4f}")

    st.divider()
    st.markdown("#### Phone Access")
    st.code("Open http://<your-ip>:8501 in Safari → Share → Add to Home Screen")

    conn.close()
