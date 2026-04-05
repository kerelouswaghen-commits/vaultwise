"""Home page — Savings mission control (v4 redesign).

Layout: Hero → Explainer → Metrics → Insight → Flex weekly bars → Budget Math → Chat
"""

from calendar import month_name as _mn, monthrange as _monthrange
from datetime import date, timedelta
import re

import streamlit as st

import analytics
import analytics_cache
import config
import database
import models
from shared.charts import DEFAULT_TREND_DICT, PALETTE
from shared.components import render_category_card, get_category_icon
from shared.state import get_conn, get_advisor, escape_dollars
from shared.filters import (
    get_filtered_breakdown, get_fixed_categories, get_flex_categories,
    get_flex_breakdown, get_excluded_categories,
)

# ── Color constants (matching mock exactly) ────────────────────────
_GRN = "#10b981"; _GRNS = "#d1fae5"
_AMB = "#f59e0b"; _AMBS = "#fef3c7"
_RED = "#ef4444"; _REDS = "#fee2e2"
_BLU = "#6366f1"; _BLUS = "#e0e7ff"
_PUR = "#8b5cf6"
_TX = "#111827"; _TX2 = "#374151"; _TX3 = "#6b7280"; _TX4 = "#9ca3af"
_BORDER = "#ebedf0"; _BS = "#f3f4f6"; _TRK = "#f3f4f6"
_CARD = "#ffffff"; _SURFACE = "#f7f8fa"
_R = "16px"; _RS = "10px"
_SH = "0 1px 3px rgba(0,0,0,0.05)"


def _week_color(actual, forecast, upper=None, lower=None):
    """Return (bg_color, badge_text, badge_css_class) for a week or month bar."""
    if forecast <= 0:
        return _BLU, "on pace", "bb"
    _upper = upper or forecast * 1.3
    _lower = lower or forecast * 0.7
    if actual > _upper:
        return _RED, "way over", "br"
    elif actual > forecast:
        return _AMB, "elevated", "ba"
    elif actual > _lower:
        return _BLU, "on pace", "bb"
    elif actual > _lower * 0.5:
        return _GRN, "under pace", "bg"
    else:
        return _GRN, "low", "bg"


def home_page():
    conn = get_conn()
    txn_count = database.get_transaction_count(conn)

    # Data freshness
    latest_txn = analytics._get_latest_transaction_date(conn)
    data_age = (date.today() - latest_txn).days
    if data_age > 30:
        st.warning(f"Your transaction data is **{data_age} days old** (latest: {latest_txn.isoformat()}). Upload recent statements.")
    elif data_age > 7:
        st.info(f"Data as of {latest_txn.isoformat()} ({data_age} days ago).")

    if txn_count == 0:
        st.info("Upload statements to see monthly spending breakdown.")
        conn.close(); st.stop()

    available_months = database.get_available_months(conn)
    if not available_months:
        st.info("No transaction data yet.")
        conn.close(); st.stop()

    # ═══════════════════════════════════════════════════════════════
    # 1. MONTH NAV
    # ═══════════════════════════════════════════════════════════════
    selected_month = st.selectbox(
        "Month", available_months, index=0,
        format_func=lambda m: f"{_mn[int(m.split('-')[1])]} {m.split('-')[0]}",
        label_visibility="collapsed",
    )
    _y, _m = selected_month.split("-")
    _sel_year, _sel_month = int(_y), int(_m)
    month_display = f"{_mn[_sel_month]} {_y}"

    # Apply merchant overrides
    _overrides = getattr(config, 'MERCHANT_CATEGORY_OVERRIDES', {})
    if _overrides:
        for _pat, _tcat in _overrides.items():
            conn.execute(
                "UPDATE transactions SET category = ? WHERE strftime('%Y-%m', date) = ? AND LOWER(description) LIKE ? AND category != ?",
                (_tcat, selected_month, f"%{_pat.lower()}%", _tcat),
            )
        conn.commit()

    # Get breakdown
    month_breakdown = get_filtered_breakdown(conn, selected_month)
    if not month_breakdown:
        st.info(f"No spending data for {month_display}.")
        conn.close(); st.stop()

    # ═══════════════════════════════════════════════════════════════
    # 2. CORE DATA COMPUTATION
    # ═══════════════════════════════════════════════════════════════
    _income_data = models.get_income_for_month(_sel_year, _sel_month)
    _monthly_income = _income_data["total_income"] if isinstance(_income_data, dict) else _income_data
    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))

    # Bonus toggles
    with st.expander("Bonus income toggles", expanded=False):
        _bc1, _bc2 = st.columns(2)
        _ik = list(config.INCOME.keys())
        _l1 = config.INCOME_LABELS.get(_ik[0], {}).get("bonus_label", "Include primary bonus") if _ik else "Include primary bonus"
        _l2 = config.INCOME_LABELS.get(_ik[1] if len(_ik) > 1 else "", {}).get("bonus_label", "Include secondary bonus")
        _b1d = database.get_setting(conn, "bonus_toggle_1", "0") == "1"
        _b2d = database.get_setting(conn, "bonus_toggle_2", "0") == "1"
        _b1 = _bc1.checkbox(_l1, value=_b1d, key="dash_kero_bonus")
        _b2 = _bc2.checkbox(_l2, value=_b2d, key="dash_maggie_bonus")
        if _b1 != _b1d: database.set_setting(conn, "bonus_toggle_1", "1" if _b1 else "0")
        if _b2 != _b2d: database.set_setting(conn, "bonus_toggle_2", "1" if _b2 else "0")
    _kb = _income_data.get("kero_bonus", 0) if isinstance(_income_data, dict) else 0
    _mb = _income_data.get("maggie_bonus", 0) if isinstance(_income_data, dict) else 0
    if not _b1: _monthly_income -= _kb
    if not _b2: _monthly_income -= _mb

    _fixed_cats = get_fixed_categories(conn)
    _flex_cats = get_flex_categories(conn)
    _excluded_cats = get_excluded_categories(conn)
    _effective_fixed = database.get_effective_fixed_total(conn)

    _txn_fixed = sum(abs(c["total"]) for c in month_breakdown if c["category"] in _fixed_cats)
    _txn_disc = sum(abs(c["total"]) for c in month_breakdown if c["category"] in _flex_cats)
    _total_outflow = _effective_fixed + _txn_disc
    _saved = _monthly_income - _total_outflow
    _gap = _saved - savings_target
    _disc_budget = _monthly_income - _effective_fixed - savings_target
    _disc_left = max(_disc_budget - _txn_disc, 0)
    _over_budget = max(_txn_disc - _disc_budget, 0)

    _days_in_month = _monthrange(_sel_year, _sel_month)[1]
    _is_current = (date.today().year, date.today().month) == (_sel_year, _sel_month)
    _days_left = max(_days_in_month - min(date.today().day, _days_in_month), 1) if _is_current else 0
    _days_elapsed = _days_in_month - _days_left if _is_current else _days_in_month

    # Hero color
    if _saved >= savings_target:
        _hero_cls = "hero-ok"; _hero_grad = f"linear-gradient(135deg,{_GRN},#059669)"
    elif _saved > 0:
        _hero_cls = "hero-warn"; _hero_grad = f"linear-gradient(135deg,{_AMB},#d97706)"
    else:
        _hero_cls = "hero-bad"; _hero_grad = f"linear-gradient(135deg,{_RED},#dc2626)"

    # Weekly projection
    _current_week = min((_days_elapsed - 1) // 7 + 1, 5) if _days_elapsed > 0 else 1
    if _days_elapsed > 0 and _days_left > 0:
        _daily_flex = _txn_disc / _days_elapsed
        _projected_flex = _txn_disc + (_daily_flex * _days_left)
        _projected_saved = _monthly_income - _effective_fixed - _projected_flex
        _proj_text = f"&#x1F4C5; As of W{_current_week} &middot; {_days_left}d left &middot; projected end: <strong>~${_projected_saved:,.0f}</strong>"
    elif _days_left == 0:
        _proj_text = f"&#x1F4C5; Month complete"
    else:
        _proj_text = ""

    # 6-month sparkline data — OPTIMIZED: single bulk query for flex totals
    _monthly_flex = database.get_monthly_flex_totals(conn, months=7)
    _monthly_flex_map = {r["month"]: r["flex_total"] for r in _monthly_flex}
    _spark_data = []
    for _ym in available_months[:6]:
        _sy, _sm = int(_ym.split("-")[0]), int(_ym.split("-")[1])
        _inc = models.get_income_for_month(_sy, _sm)
        _mo_inc = _inc["total_income"] if isinstance(_inc, dict) else _inc
        if not _b1: _mo_inc -= (_inc.get("kero_bonus", 0) if isinstance(_inc, dict) else 0)
        if not _b2: _mo_inc -= (_inc.get("maggie_bonus", 0) if isinstance(_inc, dict) else 0)
        _mo_flex = _monthly_flex_map.get(_ym, 0)
        _mo_saved = _mo_inc - _effective_fixed - _mo_flex
        _spark_data.append({"month": _ym, "saved": _mo_saved, "hit": _mo_saved >= savings_target})
    _spark_data.reverse()  # oldest first
    _max_spark = max(abs(s["saved"]) for s in _spark_data) if _spark_data else 1

    # Sparkline HTML
    _spark_html = '<div style="text-align:right;"><div style="font-size:8px;opacity:0.45;letter-spacing:0.5px;margin-bottom:4px;">6 MO</div><div style="display:flex;align-items:flex-end;gap:3px;height:36px;justify-content:flex-end;">'
    for _sd in _spark_data:
        _h = max(int(abs(_sd["saved"]) / _max_spark * 32), 3)
        _cls = "h" if _sd["hit"] else ""
        _lbl = _mn[int(_sd["month"].split("-")[1])][:1]
        _spark_html += f'<div><div style="width:5px;height:{_h}px;border-radius:2px 2px 0 0;background:rgba(255,255,255,{"0.6" if _cls else "0.2"});"></div><div style="font-size:7px;opacity:0.45;text-align:center;margin-top:2px;">{_lbl}</div></div>'
    _spark_html += '</div></div>'

    # Hero label + sub text — reframe based on savings health
    if _gap >= 0:
        _hero_label = "MONTHLY SAVINGS"
        _hero_amount = f"${_saved:,.0f}"
        _sub = f'Target ${savings_target:,} &middot; <strong>${_gap:,.0f} above goal</strong><br>You\'re on track &mdash; great month!'
    elif _saved > 0:
        _hero_label = "SAVINGS SHORTFALL"
        _hero_amount = f"&minus;${abs(_gap):,.0f}"
        _sub = (
            f'You kept only <strong>${_saved:,.0f}</strong> of your <strong>${savings_target:,}</strong> goal<br>'
            f'Overspending ate <strong>${_over_budget:,.0f}</strong> from your target savings'
        )
    else:
        _hero_label = "IN THE RED"
        _hero_amount = f"&minus;${abs(_saved):,.0f}"
        _sub = (
            f'You spent <strong>${abs(_saved):,.0f} more</strong> than you earned<br>'
            f'No savings this month &mdash; ${abs(_saved):,.0f} added to debt'
        )

    # Waterfall proportions
    _wf_total = _monthly_income if _monthly_income > 0 else 1
    _wf_fixed = int(_effective_fixed / _wf_total * 100)
    _wf_target = int(savings_target / _wf_total * 100)
    _wf_flex = 100 - _wf_fixed - _wf_target

    _wf_flex_label = f'Flex ${_txn_disc/1000:,.1f}k'
    if _over_budget > 0:
        _wf_flex_label += f' (+${_over_budget:,.0f} over)'

    # ═══════════════════════════════════════════════════════════════
    # 3. HERO CARD
    # ═══════════════════════════════════════════════════════════════
    _hero_html = (
        f'<div style="background:{_hero_grad};border-radius:{_R};padding:20px;color:#fff;margin-bottom:12px;position:relative;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.12);">'
        f'<div style="position:absolute;top:-40px;right:-40px;width:140px;height:140px;background:rgba(255,255,255,0.06);border-radius:50%;"></div>'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
        f'<div>'
        f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:1.2px;opacity:0.7;font-weight:600;">{_hero_label}</div>'
        f'<div style="font-size:38px;font-weight:800;letter-spacing:-1px;margin:2px 0;">{_hero_amount}</div>'
        f'<div style="font-size:12px;opacity:0.85;line-height:1.5;">{_sub}</div>'
        + (f'<div style="display:inline-block;margin-top:8px;padding:4px 10px;border-radius:8px;background:rgba(0,0,0,0.15);font-size:11px;font-weight:600;">{_proj_text}</div>' if _proj_text else '')
        + f'</div>'
        f'{_spark_html}'
        f'</div>'
        f'<div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin:14px 0 6px;gap:1px;">'
        f'<div style="flex:{_wf_fixed};border-radius:2px;background:rgba(255,255,255,0.2);"></div>'
        f'<div style="flex:{_wf_target};border-radius:2px;background:rgba(255,255,255,0.35);"></div>'
        f'<div style="flex:{_wf_flex};border-radius:2px;background:rgba(255,255,255,0.7);"></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;font-size:9px;opacity:0.6;">'
        f'<span>Fixed ${_effective_fixed/1000:,.1f}k</span>'
        f'<span>Target ${savings_target/1000:,.1f}k</span>'
        f'<span>{_wf_flex_label}</span>'
        f'</div>'
        f'</div>'
    )
    st.markdown(_hero_html, unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════
    # 4. RICH EXPLAINER CARD — data-driven breakdown
    # ═══════════════════════════════════════════════════════════════
    _saved_color = _GRN if _saved >= savings_target else (_AMB if _saved > 0 else _RED)

    # Find top 3 overspending categories vs their average
    _flex_bd_explain = get_flex_breakdown(conn, selected_month)
    _cat_deviations = []
    for c in _flex_bd_explain:
        _t = analytics_cache.get_cached_trend(conn, c["category"])
        _mean = float(_t.get("mean", 0)) if _t else 0
        _spent_c = abs(c["total"])
        if _mean > 0:
            _dev = _spent_c - _mean
            _cat_deviations.append({"name": c["category"], "spent": _spent_c, "avg": _mean, "dev": _dev, "pct": (_dev / _mean) * 100})
    _cat_deviations.sort(key=lambda x: x["dev"], reverse=True)
    _top_over = [c for c in _cat_deviations if c["dev"] > 0][:3]
    _top_under = [c for c in _cat_deviations if c["dev"] < 0][:3]

    # Find heaviest FLEX spending week (exclude fixed + excluded categories)
    _flex_cat_names = get_flex_categories(conn)
    _flex_cat_placeholders = ",".join("?" for _ in _flex_cat_names)
    _flex_cat_list = list(_flex_cat_names)

    _week_totals = []
    _month_start_d = date(_sel_year, _sel_month, 1)
    _month_end_d = date(_sel_year, _sel_month, _days_in_month)
    _ws_d = _month_start_d
    _wn_d = 1
    while _ws_d <= _month_end_d:
        _we_d = min(_ws_d + timedelta(days=6), _month_end_d)
        _wk_total = conn.execute(
            f"SELECT SUM(ABS(amount)) as total FROM transactions WHERE date >= ? AND date <= ? AND amount < 0 AND category IN ({_flex_cat_placeholders})",
            [_ws_d.isoformat(), _we_d.isoformat()] + _flex_cat_list,
        ).fetchone()
        # Get top spending categories for this week (for root cause)
        _wk_top = conn.execute(
            f"SELECT category, SUM(ABS(amount)) as total FROM transactions WHERE date >= ? AND date <= ? AND amount < 0 AND category IN ({_flex_cat_placeholders}) GROUP BY category ORDER BY total DESC LIMIT 3",
            [_ws_d.isoformat(), _we_d.isoformat()] + _flex_cat_list,
        ).fetchall()
        _wk_val = _wk_total["total"] or 0
        _wk_drivers = [f"{r['category']} ${r['total']:,.0f}" for r in _wk_top]
        _week_totals.append({"week": _wn_d, "total": _wk_val, "start": _ws_d, "end": _we_d, "drivers": _wk_drivers})
        _ws_d = _we_d + timedelta(days=1)
        _wn_d += 1
    _heaviest_week = max(_week_totals, key=lambda x: x["total"]) if _week_totals else None

    # Build rich explainer
    _title = f"✅ How you saved ${_saved:,.0f}" if _gap >= 0 else f"⚠️ Why you&#39;re ${abs(_gap):,.0f} short of your goal"

    _explain_html = f'<div style="background:{_CARD};border:1px solid {_BORDER};border-radius:{_R};padding:14px 16px;margin-bottom:12px;box-shadow:{_SH};font-size:12px;line-height:1.6;color:{_TX2};">'
    _explain_html += f'<div style="font-size:12px;font-weight:700;color:{_TX};margin-bottom:8px;">{_title}</div>'

    # Math breakdown
    _explain_html += f'<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">Income</span><span style="font-weight:600;">${_monthly_income:,.0f}</span></div>'
    _explain_html += f'<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">Fixed bills</span><span style="font-weight:600;color:{_RED};">&minus;${_effective_fixed:,.0f}</span></div>'
    _explain_html += f'<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">Flex spending</span><span style="font-weight:600;color:{_RED};">&minus;${_txn_disc:,.0f}</span></div>'
    _explain_html += f'<div style="display:flex;justify-content:space-between;padding:6px 0 3px;border-top:2px solid {_TX};margin-top:4px;"><span style="font-weight:700;color:{_TX};">= Savings</span><span style="font-weight:800;font-size:14px;color:{_saved_color};">${_saved:,.0f}</span></div>'

    # Categories that drove the overspend
    if _top_over:
        _explain_html += f'<div style="margin-top:10px;padding-top:8px;border-top:1px solid {_BS};">'
        _explain_html += f'<div style="font-size:10px;font-weight:700;color:{_RED};text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">🔺 Categories over average</div>'
        for _co in _top_over:
            _bar_w = min(abs(_co["pct"]), 100)
            _explain_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
                f'<span style="font-size:11px;color:{_TX2};width:110px;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{_co["name"]}</span>'
                f'<div style="flex:1;height:6px;background:{_BS};border-radius:3px;overflow:hidden;">'
                f'<div style="width:{_bar_w:.0f}%;height:100%;background:{_RED};border-radius:3px;opacity:0.7;"></div></div>'
                f'<span style="font-size:10px;color:{_RED};font-weight:600;white-space:nowrap;">+${_co["dev"]:,.0f}</span>'
                f'<span style="font-size:9px;color:{_TX4};white-space:nowrap;">(${_co["spent"]:,.0f} vs ${_co["avg"]:,.0f})</span>'
                f'</div>'
            )
        _explain_html += '</div>'

    # Categories that saved you money
    if _top_under:
        _total_saved_by = sum(abs(c["dev"]) for c in _top_under)
        _explain_html += f'<div style="margin-top:8px;padding-top:8px;border-top:1px solid {_BS};">'
        _explain_html += f'<div style="font-size:10px;font-weight:700;color:{_GRN};text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">🔻 Categories under average (saved you ${_total_saved_by:,.0f})</div>'
        for _cu in _top_under:
            _bar_w = min(abs(_cu["pct"]), 100)
            _explain_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
                f'<span style="font-size:11px;color:{_TX2};width:110px;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{_cu["name"]}</span>'
                f'<div style="flex:1;height:6px;background:{_BS};border-radius:3px;overflow:hidden;">'
                f'<div style="width:{_bar_w:.0f}%;height:100%;background:{_GRN};border-radius:3px;opacity:0.7;"></div></div>'
                f'<span style="font-size:10px;color:{_GRN};font-weight:600;white-space:nowrap;">&minus;${abs(_cu["dev"]):,.0f}</span>'
                f'<span style="font-size:9px;color:{_TX4};white-space:nowrap;">(${_cu["spent"]:,.0f} vs ${_cu["avg"]:,.0f})</span>'
                f'</div>'
            )
        _explain_html += '</div>'

    # Heaviest flex spending week with root cause
    if _heaviest_week and _heaviest_week["total"] > 0:
        _hw = _heaviest_week
        _hw_pct = _hw["total"] / _txn_disc * 100 if _txn_disc > 0 else 0
        _hw_drivers_str = " &middot; ".join(_hw.get("drivers", []))
        _explain_html += (
            f'<div style="margin-top:8px;padding:8px 10px;background:#fefce8;border-radius:8px;font-size:11px;color:#854d0e;line-height:1.5;">'
            f'&#x1F4C5; <strong>Heaviest week:</strong> W{_hw["week"]} ({_hw["start"].strftime("%b %d")}&ndash;{_hw["end"].strftime("%d")}) &mdash; '
            f'<strong>${_hw["total"]:,.0f}</strong> flex ({_hw_pct:.0f}% of total)'
            + (f'<br><span style="color:#92400e;">Driven by: {_hw_drivers_str}</span>' if _hw_drivers_str else '')
            + f'</div>'
        )

    # Bottom line callout
    if _over_budget > 0:
        _explain_html += (
            f'<div style="background:#fef2f2;border-radius:8px;padding:8px 10px;margin-top:8px;font-size:11px;color:#991b1b;line-height:1.5;">'
            f'<strong>Bottom line:</strong> Your flex budget was ${_disc_budget:,.0f}. You spent ${_txn_disc:,.0f} &mdash; '
            f'the extra ${_over_budget:,.0f} came directly out of your ${savings_target:,} savings target.'
            f'</div>'
        )
    else:
        _explain_html += (
            f'<div style="background:#f0fdf4;border-radius:8px;padding:8px 10px;margin-top:8px;font-size:11px;color:#166534;line-height:1.5;">'
            f'<strong>Bottom line:</strong> Flex budget was ${_disc_budget:,.0f}, you spent ${_txn_disc:,.0f} &mdash; ${_disc_left:,.0f} remaining. On track!'
            f'</div>'
        )

    _explain_html += '</div>'
    st.markdown(_explain_html, unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════
    # 5. SAFE TO SPEND + SAVINGS HISTORY
    # ═══════════════════════════════════════════════════════════════
    _m1, _m2 = st.columns(2)

    with _m1:
        _sts_color = _GRN if _disc_left > 0 else _RED
        _sts_border = f"1px solid {'#bbf7d0' if _disc_left > 0 else '#fecaca'}"
        _sts_sub = f"${_disc_left:,.0f} remaining" if _disc_left > 0 else f"${_over_budget:,.0f} over flex budget"
        st.markdown(
            f'<div style="background:{_CARD};border:{_sts_border};border-radius:{_R};padding:14px;box-shadow:{_SH};">'
            f'<div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:{_TX4};font-weight:600;margin-bottom:6px;">Safe to Spend</div>'
            f'<div style="font-size:26px;font-weight:800;letter-spacing:-0.5px;text-align:center;color:{_sts_color};">${_disc_left:,.0f}</div>'
            f'<div style="font-size:10px;color:{_sts_color};text-align:center;margin-top:2px;">{_sts_sub}</div>'
            f'</div>', unsafe_allow_html=True)

    with _m2:
        # Savings history horizontal bars — REUSE sparkline data (no extra queries)
        _sav_hist = []
        for _sd in reversed(_spark_data):
            _sav_hist.append({"month": _sd["month"], "saved": _sd["saved"], "is_current": _sd["month"] == selected_month})
        _max_sav = max(max(abs(s["saved"]) for s in _sav_hist), savings_target, 1)
        _target_pct = min(savings_target / _max_sav * 100, 100)

        _sav_html = f'<div style="background:{_CARD};border:1px solid {_BORDER};border-radius:{_R};padding:14px;box-shadow:{_SH};">'
        _sav_html += f'<div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:{_TX4};font-weight:600;margin-bottom:6px;">Savings History</div>'
        _sav_html += '<div style="margin-top:6px;">'
        for _sh_item in _sav_hist:
            _mo_lbl = _mn[int(_sh_item["month"].split("-")[1])][:3]
            _is_cur = _sh_item["is_current"]
            _s_val = _sh_item["saved"]
            _hit = _s_val >= savings_target
            _bar_w = min(max(abs(_s_val) / _max_sav * 100, 2), 100)
            if _is_cur:
                _fill_cls = f"background:{_AMB};"
            elif _hit:
                _fill_cls = f"background:{_GRN};"
            else:
                _fill_cls = f"background:{_RED};opacity:0.6;"
            _mo_cls = f"color:{_TX};font-weight:700;" if _is_cur else f"color:{_TX4};font-weight:500;"
            _amt_cls = f"color:{_TX};font-weight:600;" if _is_cur else f"color:{_TX3};font-weight:600;"
            _amt_str = f"${abs(_s_val)/1000:,.1f}k" if abs(_s_val) >= 1000 else f"${abs(_s_val):,.0f}"
            _sav_html += (
                f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
                f'<span style="font-size:10px;{_mo_cls}width:24px;text-align:right;flex-shrink:0;">{_mo_lbl}</span>'
                f'<div style="flex:1;height:8px;background:{_TRK};border-radius:4px;overflow:visible;position:relative;">'
                f'<div style="height:100%;width:{_bar_w:.0f}%;border-radius:4px;min-width:2px;{_fill_cls}"></div>'
                f'<div style="position:absolute;top:-2px;left:{_target_pct:.0f}%;height:12px;width:1.5px;background:{_TX};opacity:0.2;border-radius:1px;"></div>'
                f'</div>'
                f'<span style="font-size:10px;{_amt_cls}width:36px;font-variant-numeric:tabular-nums;">{_amt_str}</span>'
                f'</div>'
            )
        _sav_html += '</div>'
        _sav_html += f'<div style="display:flex;gap:8px;font-size:9px;color:{_TX4};margin-top:6px;justify-content:center;">'
        _sav_html += f'<span><span style="color:{_GRN};">&#9632;</span> hit</span>'
        _sav_html += f'<span><span style="color:{_RED};">&#9632;</span> miss</span>'
        _sav_html += f'<span><span style="color:{_AMB};">&#9632;</span> now</span>'
        _sav_html += f'<span><span style="opacity:0.3;">|</span> ${savings_target/1000:,.1f}k goal</span>'
        _sav_html += '</div></div>'
        st.markdown(_sav_html, unsafe_allow_html=True)

    # Weeks in month (needed for insight + flex bars)
    import math
    _num_weeks = math.ceil(_days_in_month / 7)

    # ═══════════════════════════════════════════════════════════════
    # 6. AI-GENERATED WEEKLY INSIGHT (Claude writes the narrative)
    # ═══════════════════════════════════════════════════════════════
    _flex_bd = _flex_bd_explain  # reuse cached flex breakdown

    # Gather per-week FLEX-ONLY totals with top categories per week
    _insight_week_totals = []
    for _wt in _week_totals:
        _drivers = ", ".join(_wt.get("drivers", []))
        _insight_week_totals.append(
            f"W{_wt['week']}: ${_wt['total']:,.0f} flex ({_wt['start'].strftime('%b %d')}-{_wt['end'].strftime('%d')})"
            + (f" — top: {_drivers}" if _drivers else "")
        )

    # Gather top category deviations with merchants for root cause
    _cat_lines = []
    for c in sorted(_flex_bd, key=lambda x: abs(x["total"]), reverse=True)[:8]:
        _t = analytics_cache.get_cached_trend(conn, c["category"])
        _mean = float(_t.get("mean", 0)) if _t else 0
        _spent_c = abs(c["total"])
        _dev = _spent_c - _mean if _mean > 0 else 0
        # Get top merchants for root cause
        _merch = database.get_merchant_breakdown_for_month(conn, c["category"], selected_month, limit=3)
        _merch_str = ", ".join(f"{m['name'][:20]} ${abs(m['total']):,.0f}" for m in _merch) if _merch else ""
        _cat_lines.append(
            f"  {c['category']}: ${_spent_c:,.0f} (avg ${_mean:,.0f}, {'+'  if _dev > 0 else ''}{f'${_dev:,.0f}' if _mean > 0 else 'no history'})"
            + (f"\n    Merchants: {_merch_str}" if _merch_str else "")
        )

    # Phase label
    _day_of_month = date.today().day if _is_current else _days_in_month
    if _day_of_month <= 7:
        _phase_label = f"Week {_current_week} &middot; Month start"
    elif _day_of_month <= 21:
        _phase_label = f"Week {_current_week} &middot; Mid-month"
    else:
        _phase_label = f"Week {_current_week} &middot; Final stretch"

    # Build Claude prompt — flex-only with root cause analysis
    _insight_prompt = (
        f"Write a 3-4 sentence financial insight for {month_display}.\n\n"
        f"IMPORTANT: All numbers below are FLEX spending only (groceries, shopping, dining, etc.). "
        f"Fixed bills (mortgage, loans, insurance) are already accounted for separately.\n\n"
        f"BUDGET SNAPSHOT:\n"
        f"- Flex budget for the month: ${_disc_budget:,.0f}\n"
        f"- Flex spent so far: ${_txn_disc:,.0f}\n"
        f"- {'OVER flex budget by $' + f'{_over_budget:,.0f}' if _over_budget > 0 else 'Under budget, $' + f'{_disc_left:,.0f} remaining'}\n"
        f"- Savings: ${_saved:,.0f} vs ${savings_target:,} target (gap: ${_gap:+,.0f})\n"
        f"- Day {_day_of_month} of {_days_in_month}, Week {_current_week} of {_num_weeks}, {_days_left} days left\n\n"
        f"WEEKLY FLEX SPENDING (what they can control):\n" + "\n".join(_insight_week_totals) + "\n\n"
        f"FLEX CATEGORIES vs HISTORICAL AVERAGE (with merchant breakdown):\n" + "\n".join(_cat_lines) + "\n\n"
        f"ROOT CAUSE ANALYSIS INSTRUCTIONS:\n"
        f"- Identify the 1-2 categories that caused the most damage (biggest $ over average)\n"
        f"- Name the specific merchants that drove those categories\n"
        f"- Explain whether the overspend was a one-time event (e.g. immigration fee, jewelry) or a recurring pattern\n"
        f"- Compare week-over-week: which week was the spike and what happened that week?\n"
        f"- If a category is way under average, mention it as a bright spot\n\n"
        f"WRITING STYLE:\n"
        f"- Write as a personal financial coach — warm, direct, specific\n"
        f"- Lead with the root cause, not the symptoms\n"
        f"- Reference specific merchant names and dollar amounts\n"
        f"- End with one concrete action for next month (or remaining days if mid-month)\n"
        f"- Use <strong> tags for key numbers and merchant names\n"
        f"- 3-4 sentences max. No bullet points. No greeting. No 'Overall' opener."
    )

    # Try to get Claude insight, fall back to simple rule-based
    _insight_text = None
    _cache_key = f"insight_{selected_month}_{_day_of_month}_{int(_txn_disc)}"
    if _cache_key not in st.session_state:
        advisor = get_advisor()
        if advisor:
            try:
                _result = advisor.get_advisor_response(
                    user_message=_insight_prompt,
                    conversation_history=[],
                    financial_context={},
                    tactical_context={},
                )
                _insight_text = _result.get("response", "").strip()
                # Clean up any markdown artifacts
                _insight_text = _insight_text.replace("**", "<strong>").replace("**", "</strong>")
                if _insight_text:
                    st.session_state[_cache_key] = _insight_text
            except Exception:
                pass

    _insight_text = st.session_state.get(_cache_key)

    if not _insight_text:
        # Fallback: simple rule-based
        if _over_budget > 0:
            _insight_text = f"You're <strong>${_over_budget:,.0f} over</strong> your flex budget. Savings this month: <strong>${_saved:,.0f}</strong> vs your <strong>${savings_target:,}</strong> goal."
        elif _gap >= 0:
            _insight_text = f"You saved <strong>${_saved:,.0f}</strong> against a <strong>${savings_target:,}</strong> goal — <strong>${_gap:,.0f} above target</strong>."
        else:
            _insight_text = f"You saved <strong>${_saved:,.0f}</strong>, falling <strong>${abs(_gap):,.0f} short</strong> of your ${savings_target:,} goal."

    # Render
    st.markdown(
        f'<div style="background:{_CARD};border:1px solid {_BORDER};border-left:3px solid {_PUR};border-radius:2px {_RS} {_RS} 2px;padding:12px 14px;margin-bottom:14px;box-shadow:{_SH};">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
        f'<span style="font-size:11px;font-weight:700;color:{_PUR};">&#9733; Weekly Insight</span>'
        f'<span style="font-size:9px;color:{_TX4};font-weight:500;">{_phase_label}</span>'
        f'</div>'
        f'<div style="font-size:13px;line-height:1.65;color:{_TX2};">{_insight_text}</div>'
        f'</div>', unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════
    # 7. FLEX SPENDING WITH WEEKLY BARS
    # ═══════════════════════════════════════════════════════════════
    _flex_breakdown = _flex_bd_explain  # reuse cached flex breakdown
    _flex_total = sum(abs(c["total"]) for c in _flex_breakdown)

    # Trend data
    trend_results = {}
    for c in _flex_breakdown:
        cached_t = analytics_cache.get_cached_trend(conn, c["category"])
        trend_results[c["category"]] = cached_t if cached_t else {**DEFAULT_TREND_DICT, "category": c["category"]}

    # Week boundaries
    _month_start = date(_sel_year, _sel_month, 1)
    _month_end = date(_sel_year, _sel_month, _days_in_month)
    _week_bounds = []
    _ws = _month_start
    _wn = 1
    while _ws <= _month_end:
        _we = min(_ws + timedelta(days=6), _month_end)
        _week_bounds.append((_wn, _ws, _we, _is_current and _ws <= date.today() <= _we))
        _ws = _we + timedelta(days=1)
        _wn += 1

    # Per-week spending per category — SINGLE bulk query instead of per-week loop
    _bulk_weekly = database.get_weekly_category_spending(
        conn, _month_start.isoformat(), _month_end.isoformat())
    _pw = {}  # {cat: [{label, actual, is_current, is_future}, ...]}
    for _wn, _ws, _we, _is_cur_wk in _week_bounds:
        _is_future = _is_current and _ws > date.today()
        for c in _flex_breakdown:
            _pw.setdefault(c["category"], []).append({
                "label": f"W{_wn}",
                "actual": _bulk_weekly.get((c["category"], _wn), 0),
                "is_current": _is_cur_wk, "is_future": _is_future,
            })

    # Pace
    _pace_frac = _days_elapsed / _days_in_month if _days_in_month > 0 else 1.0
    _num_weeks = len(_week_bounds)

    # Build flex list
    _flex_list = []
    for c in _flex_breakdown:
        cat_name = c["category"]
        spent = abs(c["total"])
        t = trend_results.get(cat_name, DEFAULT_TREND_DICT)
        t_mean = float(t.get("mean", 0))

        if t_mean <= 0:
            _hist = database.get_category_monthly_history(conn, cat_name, months=6)
            if _hist and len(_hist) >= 2:
                t_mean = sum(abs(h["total"]) for h in _hist) / len(_hist)

        _pf = analytics_cache.get_cached_prophet(conn, cat_name)
        if _pf and _pf.get("forecast"):
            month_forecast = _pf["forecast"][0]["predicted"]
            _upper = _pf["forecast"][0].get("upper", month_forecast * 1.3)
            _lower = _pf["forecast"][0].get("lower", month_forecast * 0.7)
        else:
            month_forecast = t_mean if t_mean > 0 else spent
            _upper = month_forecast * 1.3
            _lower = month_forecast * 0.7

        # Pace-based severity for the whole month
        _exp_so_far = month_forecast * _pace_frac
        _upper_sf = _upper * _pace_frac
        _lower_sf = _lower * _pace_frac
        _mo_color, _badge_text, _badge_cls = _week_color(spent, _exp_so_far, _upper_sf, _lower_sf)

        _wk_forecast = month_forecast / max(_num_weeks, 1)
        _wk_upper = _upper / max(_num_weeks, 1)
        _wk_lower = _lower / max(_num_weeks, 1)

        _flex_list.append({
            "name": cat_name, "spent": spent,
            "mo_color": _mo_color, "badge_text": _badge_text, "badge_cls": _badge_cls,
            "weeks": _pw.get(cat_name, []),
            "month_forecast": month_forecast, "wk_forecast": _wk_forecast,
            "wk_upper": _wk_upper, "wk_lower": _wk_lower,
            "pace_frac": _pace_frac,
        })

    # Render flex section
    _show_count = 5

    def _render_flex_group(cats, total, show_popover=True):
        # ── Card container ────────────────────────────────────────
        st.markdown(
            f'<div style="margin-bottom:12px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 14px 8px;">'
            f'<span style="font-size:9px;text-transform:uppercase;letter-spacing:1.2px;color:{_TX4};font-weight:700;">Flex Spending</span>'
            f'<span style="font-size:18px;font-weight:800;letter-spacing:-0.3px;">${total:,.0f}</span>'
            f'</div>', unsafe_allow_html=True)

        _badge_colors = {"br": f"background:{_REDS};color:#dc2626;", "ba": f"background:{_AMBS};color:#b45309;", "bg": f"background:{_GRNS};color:#059669;", "bb": f"background:{_BLUS};color:#4f46e5;"}
        _vibrant = ["#7c3aed", "#2563eb", "#059669", "#d97706", "#dc2626", "#ec4899"]

        for cat in cats:
            _amt_style = f"color:{_RED};" if cat["badge_cls"] == "br" else ""
            _bdg_style = _badge_colors.get(cat["badge_cls"], _badge_colors["bb"])
            _emoji, _icon_bg = get_category_icon(cat["name"])

            # ── 1. Category header row ────────────────────────────
            _header_html = (
                f'<div style="padding:14px 16px 0;border-bottom:0;">'
                f'<div style="display:flex;align-items:center;gap:10px;">'
                f'<div style="width:36px;height:36px;border-radius:10px;background:{_icon_bg};display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;">{_emoji}</div>'
                f'<div style="flex:1;min-width:0;">'
                f'<div style="font-size:15px;font-weight:600;">{cat["name"]}</div>'
                f'<div style="display:inline-flex;align-items:center;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;margin-top:2px;{_bdg_style}">{cat["badge_text"]}</div>'
                f'</div>'
                f'<div style="font-size:16px;font-weight:700;flex-shrink:0;{_amt_style}">${cat["spent"]:,.0f}</div>'
                f'</div></div>'
            )

            # ── 2. Horizontal week chips ──────────────────────────
            _chips_html = '<div class="vw-chip-row">'
            for wk in cat["weeks"]:
                _wk_actual = wk["actual"]
                _wk_pct = min(_wk_actual / cat["wk_forecast"] * 100, 100) if cat["wk_forecast"] > 0 else 0
                _wk_color, _, _ = _week_color(_wk_actual, cat["wk_forecast"], cat["wk_upper"], cat["wk_lower"])
                _is_cur = wk["is_current"]
                _is_fut = wk["is_future"]

                if _is_fut:
                    _chip_cls = "vw-chip future"
                    _chip_amt = "&mdash;"
                    _chip_amt_style = ""
                    _chip_fill = ""
                elif _is_cur:
                    _chip_cls = "vw-chip active"
                    _chip_amt = f"${_wk_actual:,.0f}"
                    _chip_amt_style = f"color:{_wk_color};" if _wk_color in (_RED, _AMB) else ""
                    _chip_fill = f'<div class="chip-fill" style="width:{_wk_pct:.0f}%;background:{_wk_color};"></div>'
                else:
                    _chip_cls = "vw-chip"
                    _chip_amt = f"${_wk_actual:,.0f}"
                    _chip_amt_style = f"color:{_wk_color};" if _wk_color in (_RED, _AMB) else ""
                    _chip_fill = f'<div class="chip-fill" style="width:{_wk_pct:.0f}%;background:{_wk_color};opacity:0.6;"></div>'

                _chips_html += (
                    f'<div class="{_chip_cls}">'
                    f'<div class="chip-label">{wk["label"]}</div>'
                    f'<div class="chip-amount" style="{_chip_amt_style}">{_chip_amt}</div>'
                    f'<div class="chip-bar">{_chip_fill}</div>'
                    f'</div>'
                )
            _chips_html += '</div>'

            # ── 3. Monthly progress bar ───────────────────────────
            _mo_pct = min(cat["spent"] / cat["month_forecast"] * 100, 100) if cat["month_forecast"] > 0 else 0
            _pace_marker_pct = min(cat["pace_frac"] * 100, 100)
            _month_html = (
                f'<div class="vw-month-bar">'
                f'<span class="mo-label">Mo</span>'
                f'<div class="mo-track">'
                f'<div class="mo-fill" style="width:{_mo_pct:.0f}%;background:{cat["mo_color"]};"></div>'
                f'<div class="mo-pace" style="left:{_pace_marker_pct:.0f}%;"></div>'
                f'</div>'
                f'<span class="mo-nums">${cat["spent"]:,.0f} / ${cat["month_forecast"]:,.0f}</span>'
                f'</div>'
            )

            # Render card + expander inside one bordered container
            _accent = cat["mo_color"]

            with st.container(border=True):
                # Top accent bar + card content
                _cat_html = (
                    f'<div style="margin:-1rem -1rem 0 -1rem;overflow:hidden;border-radius:14px 14px 0 0;">'
                    f'<div style="height:4px;background:{_accent};"></div>'
                    f'</div>'
                    f'{_header_html}{_chips_html}{_month_html}'
                )
                st.markdown(_cat_html, unsafe_allow_html=True)

                # Expander inside the same container
                if not show_popover:
                    continue
                with st.expander("🔮 Forecast & Details"):
                    _t = trend_results.get(cat["name"], DEFAULT_TREND_DICT)
                    _t_mean = float(_t.get("mean", 0))
                    _t_direction = _t.get("direction", "stable")
                    _t_slope = float(_t.get("slope_per_month", 0))

                    # Fallback: compute from history when cache is empty
                    _detail_hist = database.get_category_monthly_history(conn, cat["name"], months=12)
                    if _t_mean <= 0 and _detail_hist and len(_detail_hist) >= 2:
                        _dh_vals = [abs(h["total"]) for h in _detail_hist]
                        _t_mean = sum(_dh_vals) / len(_dh_vals)
                        # Compute simple trend from history
                        if len(_dh_vals) >= 3:
                            _recent = sum(_dh_vals[:3]) / 3
                            _older = sum(_dh_vals[-3:]) / 3
                            _t_slope = (_recent - _older) / max(len(_dh_vals) - 1, 1)
                            if _t_slope > _t_mean * 0.05:
                                _t_direction = "rising"
                            elif _t_slope < -_t_mean * 0.05:
                                _t_direction = "falling"
                            else:
                                _t_direction = "stable"

                    # Forecast row
                    _pf = analytics_cache.get_cached_prophet(conn, cat["name"])
                    if _pf and _pf.get("forecast"):
                        _fc = _pf["forecast"][0]
                        _fc_pred = _fc["predicted"]
                        _fc_lower = _fc.get("lower", _fc_pred * 0.8)
                        _fc_upper = _fc.get("upper", _fc_pred * 1.2)
                        _fc_dir = "↑" if _fc_pred > cat["spent"] else "↓"
                        _fc_html = (
                            f'<div class="vw-forecast-row">'
                            f'<div class="fc-icon">🔮</div>'
                            f'<div>'
                            f'<div class="fc-label">Prophet Forecast</div>'
                            f'<div class="fc-value">${_fc_pred:,.0f} next month {_fc_dir}</div>'
                            f'<div class="fc-range">Range: ${_fc_lower:,.0f} &ndash; ${_fc_upper:,.0f} (80% CI)</div>'
                            f'</div></div>'
                        )
                    else:
                        _fc_html = (
                            f'<div class="vw-forecast-row">'
                            f'<div class="fc-icon">📊</div>'
                            f'<div>'
                            f'<div class="fc-label">Monthly Forecast</div>'
                            f'<div class="fc-value">${cat["month_forecast"]:,.0f} expected</div>'
                            f'<div class="fc-range">Based on historical average</div>'
                            f'</div></div>'
                        )

                    # Stats grid
                    _pct_vs = ((cat["spent"] / _t_mean) - 1) * 100 if _t_mean > 0 else 0
                    _pct_color = _RED if _pct_vs > 15 else (_AMB if _pct_vs > 0 else _GRN)
                    _pct_sign = "+" if _pct_vs > 0 else ""
                    _sev_color = cat["mo_color"]
                    _stats_html = (
                        f'<div class="vw-stats-grid">'
                        f'<div class="stat-cell"><div class="stat-label">This Month</div>'
                        f'<div class="stat-value" style="color:{_sev_color};">${cat["spent"]:,.0f}</div></div>'
                        f'<div class="stat-cell"><div class="stat-label">Average</div>'
                        f'<div class="stat-value">${_t_mean:,.0f}</div></div>'
                        f'<div class="stat-cell"><div class="stat-label">vs Avg</div>'
                        f'<div class="stat-value" style="color:{_pct_color};">{_pct_sign}{_pct_vs:.0f}%</div></div>'
                        f'</div>'
                    )

                    # Top merchants
                    _merch = database.get_merchant_breakdown_for_month(conn, cat["name"], selected_month, limit=5)
                    _merch_html = ""
                    if _merch:
                        _max_m = max(abs(m["total"]) for m in _merch) if _merch else 1
                        _merch_html = '<div style="margin-top:2px;"><div style="font-size:10px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.3px;margin-bottom:6px;">Top Merchants</div>'
                        for _mi, _m in enumerate(_merch):
                            _mname = _m["name"] or ""
                            _mname = re.sub(r'[A-Z0-9]{8,}', '', _mname).strip()
                            _mname = re.sub(r'\s+', ' ', _mname).strip().rstrip(',').strip()
                            if not _mname or len(_mname) <= 2:
                                _mname = "Other"
                            _mname = _mname.title() if _mname.isupper() else _mname
                            _mname = _mname[:25]
                            _mamt = abs(_m["total"])
                            _mw = min(_mamt / _max_m * 100, 100) if _max_m > 0 else 0
                            _mc = _vibrant[_mi % len(_vibrant)]
                            # If bar is too narrow (<35%), show name outside the bar
                            if _mw < 35:
                                _merch_html += (
                                    f'<div class="vw-merchant-row">'
                                    f'<div class="merch-bar"><div class="merch-fill" style="width:{_mw:.0f}%;background:{_mc};"></div>'
                                    f'<span class="merch-name-outside" style="position:absolute;left:{_mw:.0f}%;padding-left:6px;top:50%;transform:translateY(-50%);font-size:11px;font-weight:600;color:{_mc};white-space:nowrap;">{_mname}</span></div>'
                                    f'<span class="merch-amt">${_mamt:,.0f}</span>'
                                    f'</div>'
                                )
                            else:
                                _merch_html += (
                                    f'<div class="vw-merchant-row">'
                                    f'<div class="merch-bar"><div class="merch-fill" style="width:{_mw:.0f}%;background:{_mc};"><span class="merch-name">{_mname}</span></div></div>'
                                    f'<span class="merch-amt">${_mamt:,.0f}</span>'
                                    f'</div>'
                                )
                        _merch_html += '</div>'

                    # Trend line (reuse _detail_hist from above)
                    _dir_icons = {"rising": "📈", "falling": "📉", "stable": "→"}
                    _dir_icon = _dir_icons.get(_t_direction, "→")
                    _slope_dir = "↑" if _t_slope > 0 else ("↓" if _t_slope < 0 else "")
                    if _detail_hist and len(_detail_hist) >= 2:
                        _h_vals = [abs(h["total"]) for h in _detail_hist]
                        _h_min, _h_max = min(_h_vals), max(_h_vals)
                        _range_str = f"Range: <strong>${_h_min:,.0f}&ndash;${_h_max:,.0f}</strong>"
                    else:
                        _range_str = ""
                    _trend_html = (
                        f'<div class="vw-trend-line">'
                        f'<span>{_dir_icon} Trend: <strong>{_t_direction.title()} {_slope_dir} ${abs(_t_slope):,.0f}/mo</strong></span>'
                        + (f'<span>&bull;</span><span>{_range_str}</span>' if _range_str else '')
                        + f'</div>'
                    )

                    st.markdown(_fc_html + _stats_html + _merch_html + _trend_html, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    if _flex_list:
        _render_flex_group(_flex_list[:_show_count], _flex_total)

        if len(_flex_list) > _show_count:
            _extra = _flex_list[_show_count:]
            _extra_total = sum(c["spent"] for c in _extra)
            with st.expander(f"Show {len(_extra)} more categories (${_extra_total:,.0f})"):
                _render_flex_group(_extra, _extra_total)

    # ═══════════════════════════════════════════════════════════════
    # 8. BUDGET MATH (expander)
    # ═══════════════════════════════════════════════════════════════
    _kero_net = _income_data.get("kero_net", 0) if isinstance(_income_data, dict) else 0
    _maggie_net = _income_data.get("maggie_net", 0) if isinstance(_income_data, dict) else 0
    if _b1: _kero_net += _kb
    if _b2: _maggie_net += _mb
    _ik = list(config.INCOME.keys())
    _inc_l1 = config.INCOME_LABELS.get(_ik[0], {}).get("label", "Primary") if _ik else "Primary"
    _inc_l2 = config.INCOME_LABELS.get(_ik[1] if len(_ik) > 1 else "", {}).get("label", "Secondary")

    with st.expander("📊 Budget Math", expanded=False):
        _bm_left, _bm_right = st.columns(2)
        with _bm_left:
            _money_html = (
                f'<div style="font-size:12px;font-weight:700;color:{_TX2};margin-bottom:8px;">💵 Money In</div>'
                f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">{_inc_l1}</span><span style="font-weight:600;">${_kero_net:,.0f}</span></div>'
                f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">{_inc_l2}</span><span style="font-weight:600;">${_maggie_net:,.0f}</span></div>'
                f'<div style="display:flex;justify-content:space-between;padding:6px 0;font-size:12px;border-top:2px solid {_TX};margin-top:2px;"><span style="font-weight:700;color:{_TX};">Total Income</span><span style="font-weight:800;">${_monthly_income:,.0f}</span></div>'
            )
            st.markdown(_money_html, unsafe_allow_html=True)

            # Fixed bills detail
            _fixed_detail = database.get_effective_fixed_detail(conn)
            st.markdown(f'<div style="font-size:12px;font-weight:700;color:{_TX2};margin:12px 0 8px;">🏠 Fixed Monthly Bills</div>', unsafe_allow_html=True)
            _fb_html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 16px;">'
            for _fd in _fixed_detail:
                if _fd["effective"] > 0:
                    _fb_html += f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">{_fd["name"]}</span><span style="font-weight:600;">${_fd["effective"]:,.0f}</span></div>'
            _fb_html += '</div>'
            _fb_html += f'<div style="display:flex;justify-content:space-between;padding:6px 0;font-size:12px;border-top:2px solid {_TX};margin-top:2px;max-width:200px;"><span style="font-weight:700;color:{_TX};">Total Fixed</span><span style="font-weight:800;">${_effective_fixed:,.0f}</span></div>'
            st.markdown(_fb_html, unsafe_allow_html=True)

        with _bm_right:
            _hl_bg = "#f0fdf4" if _disc_left > 0 else "#f0fdf4"
            _hl_r_bg = "#fef2f2" if _over_budget > 0 else "#f0fdf4"
            _result_color = _RED if _over_budget > 0 else _GRN
            _result_label = f"= Over by" if _over_budget > 0 else "= Remaining"
            _result_val = f"&minus;${_over_budget:,.0f}" if _over_budget > 0 else f"${_disc_left:,.0f}"

            _math_html = (
                f'<div style="font-size:12px;font-weight:700;color:{_TX2};margin-bottom:8px;">🧮 The Math</div>'
                f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">Income</span><span style="font-weight:600;">${_monthly_income:,.0f}</span></div>'
                f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">&minus; Fixed bills</span><span style="font-weight:600;color:{_RED};">&minus;${_effective_fixed:,.0f}</span></div>'
                f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">&minus; Savings target</span><span style="font-weight:600;color:{_PUR};">&minus;${savings_target:,.0f}</span></div>'
                f'<div style="display:flex;justify-content:space-between;padding:4px 8px;font-size:12px;background:#f0fdf4;border-radius:6px;margin:2px -8px;"><span style="color:{_TX3};">= Flex budget</span><span style="font-weight:800;color:{_GRN};">${_disc_budget:,.0f}</span></div>'
                f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:12px;border-bottom:1px solid {_BS};"><span style="color:{_TX3};">&minus; Flex spent</span><span style="font-weight:600;color:{_RED};">&minus;${_txn_disc:,.0f}</span></div>'
                f'<div style="display:flex;justify-content:space-between;padding:4px 8px;font-size:12px;background:{_hl_r_bg};border-radius:6px;margin:2px -8px;"><span style="color:{_TX3};">{_result_label}</span><span style="font-weight:800;color:{_result_color};">{_result_val}</span></div>'
            )
            st.markdown(_math_html, unsafe_allow_html=True)

            # Summary cards
            _gap_bg = "#fef2f2" if _gap < 0 else _SURFACE
            _gap_color = _RED if _gap < 0 else _GRN
            _gap_str = f"&minus;${abs(_gap):,.0f}" if _gap < 0 else f"${_gap:,.0f}"
            _summ_html = (
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:12px;">'
                f'<div style="text-align:center;padding:10px 8px;border-radius:{_RS};background:{_SURFACE};"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:{_TX4};font-weight:600;">Saved</div><div style="font-size:18px;font-weight:800;margin-top:2px;color:{_saved_color};">${_saved:,.0f}</div></div>'
                f'<div style="text-align:center;padding:10px 8px;border-radius:{_RS};background:{_SURFACE};"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:{_TX4};font-weight:600;">Target</div><div style="font-size:18px;font-weight:800;margin-top:2px;">${savings_target:,}</div></div>'
                f'<div style="text-align:center;padding:10px 8px;border-radius:{_RS};background:{_gap_bg};"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.8px;color:{_TX4};font-weight:600;">Gap</div><div style="font-size:18px;font-weight:800;margin-top:2px;color:{_gap_color};">{_gap_str}</div></div>'
                f'</div>'
            )
            st.markdown(_summ_html, unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════
    # 9. REFRESH ANALYTICS
    # ═══════════════════════════════════════════════════════════════
    _cache_stale = analytics_cache.is_stale(conn)
    if _cache_stale:
        st.warning(f"Analytics cache is stale ({analytics_cache.get_last_refresh_display(conn)}). Refresh to update trends.")
    if st.button("Refresh Analytics", type="primary" if _cache_stale else "secondary"):
        with st.spinner("Refreshing analytics cache..."):
            analytics_cache.refresh_all(conn)
        st.rerun()

    # ═══════════════════════════════════════════════════════════════
    # 10. CHAT
    # ═══════════════════════════════════════════════════════════════
    if "dashboard_chat_history" not in st.session_state:
        st.session_state.dashboard_chat_history = []
    if "dashboard_chat_month" not in st.session_state:
        st.session_state.dashboard_chat_month = ""
    if "chat_mode" not in st.session_state:
        st.session_state.chat_mode = "This Month"
    if "suggested_questions" not in st.session_state:
        st.session_state.suggested_questions = []
    if st.session_state.dashboard_chat_month != selected_month:
        st.session_state.dashboard_chat_history = []
        st.session_state.suggested_questions = []
        st.session_state.dashboard_chat_month = selected_month

    st.markdown(
        f'<div style="background:{_CARD};border:1px solid {_BORDER};border-radius:{_R};padding:14px 16px;box-shadow:{_SH};">'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">'
        f'<span style="font-size:15px;">💬</span>'
        f'<span style="font-size:13px;font-weight:700;color:{_TX2};">Ask Anything</span>'
        f'</div></div>', unsafe_allow_html=True)

    _is_historical = st.session_state.chat_mode == "Historical"

    for msg in st.session_state.dashboard_chat_history:
        with st.chat_message(msg["role"]):
            display_text = escape_dollars(msg["content"]) if msg["role"] == "assistant" else msg["content"]
            st.markdown(display_text)

    needs_response = (
        st.session_state.dashboard_chat_history
        and st.session_state.dashboard_chat_history[-1]["role"] == "user"
    )

    if needs_response:
        pending_msg = st.session_state.dashboard_chat_history[-1]["content"]

        # Detect year-level questions (e.g. "in 2025", "for 2024")
        _year_match = re.search(r'\b(20[0-9]{2})\b', pending_msg)

        if _year_match:
            _target_year = _year_match.group(1)
            _annual_breakdown = database.get_annual_category_breakdown(conn, _target_year)
            _excluded = get_excluded_categories(conn)
            _annual_breakdown = [c for c in _annual_breakdown if c['category'] not in _excluded]
            _annual_total = sum(abs(r['total']) for r in _annual_breakdown)
            _annual_cat_summary = "\n".join(
                f"  {c['category']}: ${abs(c['total']):,.2f} ({c['txn_count']} txns)"
                for c in _annual_breakdown
            )
            _trend_data = database.get_spending_trend_filtered(conn, months=24, excluded_categories=_excluded)
            _year_months = sorted(
                [r for r in _trend_data if r['month'].startswith(_target_year)],
                key=lambda x: x['month'],
            )
            _year_trend = "\n".join(
                f"  {r['month']}: spent ${abs(r['spending']):,.0f}"
                for r in _year_months
            )
            _completeness = f"Data covers {len(_year_months)} month(s) of {_target_year}."
            _unified_context = (
                f"ANNUAL DATA — {_target_year}\n{_completeness}\n"
                f"Savings target: ${savings_target:,}/mo\n\n"
                f"TOTAL SPENDING IN {_target_year}: ${_annual_total:,.2f}\n\n"
                f"CATEGORY BREAKDOWN (full year, expenses only):\n{_annual_cat_summary}\n\n"
                f"MONTHLY TOTALS FOR {_target_year}:\n{_year_trend}\n\n"
                f"This is COMPLETE data for the available months. Use these exact numbers — do not estimate or extrapolate.\n\n"
                f"FOLLOW_UP: After your answer, add 4 follow-up questions starting with '- '."
            )
        elif _is_historical:
            _excluded_hist = get_excluded_categories(conn)
            _trend_data = database.get_spending_trend_filtered(conn, months=12, excluded_categories=_excluded_hist)
            _trend_summary = "\n".join(f"  {r['month']}: spent ${abs(r['spending']):,.0f}" for r in _trend_data)
            _cat_history_lines = ""
            _all_hist_cats = conn.execute("""
                SELECT category, SUM(amount) as total FROM transactions
                WHERE date >= date('now', '-12 months') AND amount < 0
                GROUP BY category ORDER BY total ASC
            """).fetchall()
            _all_hist_cat_names = [r[0] for r in _all_hist_cats if r[0] not in _excluded_hist]
            for _cat_name in _all_hist_cat_names[:20]:
                _hist = database.get_category_monthly_history(conn, _cat_name, months=12)
                if _hist:
                    _cat_history_lines += f"  {_cat_name}: " + ", ".join(f"{h['month']}: ${abs(h['total']):,.0f}" for h in _hist) + "\n"
            _cat_summary = "\n".join(f"  {c['category']}: ${abs(c['total']):,.2f} ({c['txn_count']} txns)" for c in month_breakdown)
            _unified_context = (
                f"HISTORICAL DATA — Last 12 Months\nCurrent month: {month_display}\nSavings target: ${savings_target:,}/mo\n\n"
                f"MONTHLY TOTALS:\n{_trend_summary}\n\nCATEGORY HISTORY:\n{_cat_history_lines}\nCURRENT MONTH:\n{_cat_summary}\n\n"
                f"Answer comparisons, rank months, identify patterns. Reference specific months and amounts.\n\n"
                f"FOLLOW_UP: After your answer, add 4 follow-up questions starting with '- '."
            )
        else:
            _excl_cats = get_excluded_categories(conn)
            _excl_ph = ",".join("?" * len(_excl_cats)) if _excl_cats else "''"
            _all_txns = conn.execute(
                f"SELECT date, description, amount, category FROM transactions "
                f"WHERE strftime('%Y-%m', date) = ? AND amount < 0 AND category NOT IN ({_excl_ph}) "
                f"ORDER BY category, date",
                (selected_month, *_excl_cats),
            ).fetchall()
            _txn_context = "\n".join(f"{t['date']} | {t['description']} | ${t['amount']:,.2f} | {t['category']}" for t in _all_txns)
            _cat_summary = "\n".join(f"  {c['category']}: ${abs(c['total']):,.2f} ({c['txn_count']} txns)" for c in month_breakdown)
            _total_cat_spending = sum(abs(c['total']) for c in month_breakdown)
            _total_txn_count = sum(c['txn_count'] for c in month_breakdown)
            _unified_context = (
                f"DASHBOARD DATA for {month_display}:\n- Income: ${_monthly_income:,.0f}\n- Fixed: ${_effective_fixed:,.0f}\n"
                f"- Savings target: ${savings_target:,}/mo\n- Flex budget: ${_disc_budget:,.0f}\n- Flex spent: ${_txn_disc:,.0f}\n"
                f"- Over budget: ${_over_budget:,.0f}\n- Saved: ${_saved:,.0f}\n- Gap: ${_gap:+,.0f}\n"
                f"- Total category spending (all categories below): ${_total_cat_spending:,.2f} ({_total_txn_count} transactions)\n\n"
                f"CATEGORIES:\n{_cat_summary}\n\nTRANSACTIONS:\n{_txn_context}\n\n"
                f"FOLLOW_UP: After your answer, add 4 follow-up questions starting with '- '."
            )

        advisor = get_advisor()
        if advisor:
            with st.chat_message("assistant"):
                with st.spinner("Analyzing..."):
                    try:
                        result = advisor.get_advisor_response(
                            user_message=f"{_unified_context}\n\nUser question: {pending_msg}",
                            conversation_history=st.session_state.dashboard_chat_history[:-1],
                            financial_context={"month": selected_month, "month_display": month_display, "savings_target": savings_target, "gap": _over_budget},
                            tactical_context={},
                        )
                        response = result.get("response", str(result))
                        _followups = []
                        _lines = response.rstrip().split("\n")
                        for _ln in reversed(_lines):
                            _stripped = _ln.strip()
                            if _stripped.startswith("- ") and 10 < len(_stripped) < 80:
                                _followups.insert(0, _stripped[2:].strip().rstrip("?") + "?")
                            elif _followups:
                                break
                        _display_response = response
                        if len(_followups) >= 2:
                            _cut = response.rfind("- " + _followups[0].rstrip("?")[:15])
                            if _cut > 0:
                                _display_response = response[:_cut].rstrip()
                                if _display_response.rstrip().endswith(":"):
                                    _display_response = _display_response[:_display_response.rstrip().rfind("\n")].rstrip()
                            st.session_state.suggested_questions = _followups[:4]
                        st.markdown(escape_dollars(_display_response))
                        st.session_state.dashboard_chat_history.append({"role": "assistant", "content": _display_response})
                    except Exception:
                        st.error("Could not get a response. Please try again.")
        else:
            with st.chat_message("assistant"):
                st.warning("Set your Anthropic API key in Settings to use the chat.")

    # Quick actions
    if st.session_state.suggested_questions and len(st.session_state.suggested_questions) >= 4:
        _qa = {q: q for q in st.session_state.suggested_questions[:4]}
    elif _is_historical:
        _qa = {"6-Month Trend": "How has spending changed over 6 months?", "Best Month": "Which was my best savings month?",
               "Biggest Changes": "Which categories changed most?", "Seasonal Patterns": "Any seasonal spending patterns?"}
    else:
        _qa = {"Am I on track?": "Am I on track to meet my savings target?", "Can I spend $200?": "Can I afford $200 this weekend?",
               "Cut $100 where?": "Where are the easiest $100 in cuts?", "vs Last Month": "Compare this month to last month."}

    def _ask_q(q): st.session_state.dashboard_chat_history.append({"role": "user", "content": q})

    _qi = list(_qa.items())
    _c1, _c2 = st.columns(2)
    _c1.button(_qi[0][0], width="stretch", key="q0", on_click=_ask_q, args=(_qi[0][1],))
    _c2.button(_qi[1][0], width="stretch", key="q1", on_click=_ask_q, args=(_qi[1][1],))
    _c3, _c4 = st.columns(2)
    _c3.button(_qi[2][0], width="stretch", key="q2", on_click=_ask_q, args=(_qi[2][1],))
    _c4.button(_qi[3][0], width="stretch", key="q3", on_click=_ask_q, args=(_qi[3][1],))

    _chat_mode = st.segmented_control("chat_mode_toggle", ["This Month", "Historical"], default=st.session_state.chat_mode, label_visibility="collapsed")
    if _chat_mode and _chat_mode != st.session_state.chat_mode:
        st.session_state.chat_mode = _chat_mode
        st.session_state.dashboard_chat_history = []
        st.session_state.suggested_questions = []
        st.rerun()

    _ph = "Ask about this month..." if not _is_historical else "Compare months, spot trends..."
    _q = st.chat_input(_ph)
    if _q:
        st.session_state.dashboard_chat_history.append({"role": "user", "content": _q})
        st.rerun()

    conn.close()
