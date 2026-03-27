"""
VaultWise — Kero & Maggie's Financial Command Center
Upload PDF/CSV statements. Claude analyzes, advises, and forecasts.
"""

import os

import streamlit as st

import config
import database
import models
from shared.css import inject_css
from shared.state import (
    DB_PATH, init_session, load_persisted_config, monarch_auto_sync,
    get_conn, get_advisor,
)
from shared.components import render_savings_gauge

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG & INIT
# ═══════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="VaultWise", page_icon="💰", initial_sidebar_state="auto")

# PWA support
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

inject_css()
database.init_db(DB_PATH)
init_session()
load_persisted_config()
monarch_auto_sync()


# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR — persistent savings widget + status metrics
# ═══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 💰 VaultWise")
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

    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))

    # Compact savings widget in sidebar
    if txn_count > 0:
        from datetime import date
        from calendar import month_name as _mn
        today = date.today()
        month_display = f"{_mn[today.month]} {today.year}"
        current_month = today.strftime("%Y-%m")

        _income_data = models.get_income_for_month(today.year, today.month)
        _monthly_income = _income_data["total_income"] if isinstance(_income_data, dict) else _income_data
        # Exclude bonuses for conservative estimate
        _kero_bonus = _income_data.get("kero_bonus", 0) if isinstance(_income_data, dict) else 0
        _maggie_bonus = _income_data.get("maggie_bonus", 0) if isinstance(_income_data, dict) else 0
        _monthly_income -= (_kero_bonus + _maggie_bonus)

        _fixed_costs = sum(config.FIXED_MONTHLY_EXPENSES.values())

        import category_engine
        _raw_breakdown = database.get_monthly_category_breakdown(conn, current_month)
        _active_cats = category_engine.get_active_categories(conn)
        _mb = [c for c in _raw_breakdown if c["category"] in _active_cats]
        _total_spent = sum(abs(c["total"]) for c in _mb)

        _fixed_cats = {"Housing & Utilities", "Debt Payments", "Giving & Church", "Family Support",
                       "Transportation", "Childcare & Education", "Phone & Internet", "Car Insurance"}
        _txn_fixed = sum(abs(c["total"]) for c in _mb if c["category"] in _fixed_cats)
        _txn_disc = _total_spent - _txn_fixed
        _eff_fixed = max(_fixed_costs, _txn_fixed)
        _total_outflow = _eff_fixed + _txn_disc
        _saved = _monthly_income - _total_outflow

        render_savings_gauge(
            month_display=month_display, saved=_saved, gauge_color="",
            status_icon="", status_text="",
            total_outflow=_total_outflow, budget_limit=_monthly_income - savings_target,
            savings_target=savings_target, effective_fixed=_eff_fixed,
            txn_discretionary=_txn_disc, spent_pct=0,
            compact=True,
        )
    else:
        st.metric("Savings Target", f"${savings_target:,}/mo")

    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# NAVIGATION — st.navigation with st.Page
# ═══════════════════════════════════════════════════════════════════════════
from pages.home import home_page
from pages.transactions import transactions_page
from pages.savings_journey import savings_journey_page
from pages.settings import settings_page

pg = st.navigation([
    st.Page(home_page, title="Home", icon=":material/home:", default=True),
    st.Page(transactions_page, title="Transactions", icon=":material/receipt_long:"),
    st.Page(savings_journey_page, title="Savings Journey", icon=":material/savings:"),
    st.Page(settings_page, title="Settings", icon=":material/settings:"),
])
pg.run()
