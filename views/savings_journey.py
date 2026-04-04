"""Plan page — The Math, Savings Meter, Find Your Savings."""

import json
import random
import calendar as _cal
from datetime import date as _date

import streamlit as st

import category_engine
import config
import database
import models
from shared.state import get_conn, get_advisor

# Category colors for the stacked bar
_CAT_COLORS = [
    "#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6",
    "#8b5cf6", "#ef4444", "#14b8a6", "#f97316", "#64748b",
]


def _get_flexible_spending(conn, year_month: str, fixed_cats, muted_cats, merges):
    """Get flexible spending for a month using centralized filtering.

    Returns (total_flexible, category_totals_dict).
    """
    from shared.filters import get_filtered_breakdown
    _cats = get_filtered_breakdown(conn, year_month)

    _flex = [c for c in _cats if c["category"] not in fixed_cats]
    _total = sum(abs(c["total"]) for c in _flex)
    _by_cat = {c["category"]: abs(c["total"]) for c in _flex}
    return _total, _by_cat


def savings_journey_page():
    """Render the Plan page: The Math, Savings Meter, Find Your Savings."""
    conn = get_conn()

    # ── Recompute key variables ───────────────────────────────────────
    savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))
    _today = _date.today()
    _income_data = models.get_income_for_month(_today.year, _today.month)
    _monthly_income = _income_data["total_income"] if isinstance(_income_data, dict) else _income_data
    _kero_bonus = _income_data.get("kero_bonus", 0) if isinstance(_income_data, dict) else 0
    _maggie_bonus = _income_data.get("maggie_bonus", 0) if isinstance(_income_data, dict) else 0
    # Note: bonuses always excluded here for conservative estimate (dashboard has toggles)
    _monthly_income -= (_kero_bonus + _maggie_bonus)
    # Use the same DB-driven effective fixed total as Home/sidebar/reports
    from shared.filters import get_excluded_categories, get_fixed_categories
    _muted_cats = get_excluded_categories(conn)
    _fixed_cats = get_fixed_categories(conn)
    _merges = getattr(config, 'CATEGORY_MERGES', {})
    _effective_fixed = database.get_effective_fixed_total(conn)
    _current_month = _today.strftime("%Y-%m")
    _savings_target = savings_target
    _flex_budget = _monthly_income - _effective_fixed - _savings_target

    # ── Get last 6 months of flexible spending ─────────────────────────
    _month_keys = conn.execute("""
        SELECT DISTINCT strftime('%Y-%m', date) as month
        FROM transactions WHERE amount < 0
        ORDER BY month DESC LIMIT 6
    """).fetchall()

    _month_cat_totals = {}
    for _mk in _month_keys:
        _ym = _mk["month"]
        _, _by_cat = _get_flexible_spending(
            conn, _ym, _fixed_cats, _muted_cats, _merges)
        _month_cat_totals[_ym] = _by_cat

    # ── Compute category averages ──────────────────────────────────────
    _all_cats = {}
    for _ym, _by_cat in _month_cat_totals.items():
        for _cat_name, _amt in _by_cat.items():
            _all_cats.setdefault(_cat_name, []).append(_amt)

    _cat_avg_sorted = []
    for _cat_name, _amounts in _all_cats.items():
        _avg = int(round(sum(_amounts) / len(_amounts)))
        if _avg > 20:
            _cat_avg_sorted.append((_cat_name, _avg))
    _cat_avg_sorted.sort(key=lambda x: -x[1])

    _total_typical = sum(avg for _, avg in _cat_avg_sorted)

    # ── Load saved targets + minimums ────────────────────────────────
    if "plan_targets" not in st.session_state:
        _saved_raw = database.get_setting(conn, "flex_category_targets", "")
        _saved = json.loads(_saved_raw) if _saved_raw else {}
        st.session_state.plan_targets = {
            cat: _saved.get(cat, avg) for cat, avg in _cat_avg_sorted
        }
    if "plan_minimums" not in st.session_state:
        _mins_raw = database.get_setting(conn, "category_min_targets", "")
        st.session_state.plan_minimums = json.loads(_mins_raw) if _mins_raw else {}

    # ══════════════════════════════════════════════════════════════════
    # SECTION 1: HERO + PROJECTIONS (placeholders filled after sliders)
    # ══════════════════════════════════════════════════════════════════
    from shared.components import (
        render_plan_hero_v2, render_plan_year_pills,
        render_plan_sliders_header, render_plan_impact_bar,
    )
    _month_label = _today.strftime("%B %Y")
    _hero_placeholder = st.empty()
    _year_placeholder = st.empty()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 2: RECOMMEND + MINIMUMS + SLIDERS
    # ══════════════════════════════════════════════════════════════════

    # ── Recommend a Plan button (above sliders for prominence) ──────
    _cat_mins = st.session_state.plan_minimums
    _min_total = sum(_cat_mins.get(cat, 0) for cat, _ in _cat_avg_sorted)
    _target_achievable = _min_total <= _flex_budget

    if st.button("✨ Recommend a Plan", use_container_width=True):
        advisor = get_advisor()
        if advisor:
            # Current month actual spending per category
            _current_spending = _month_cat_totals.get(_current_month, {})

            _cat_lines = []
            for cat, avg in _cat_avg_sorted:
                _cur = _current_spending.get(cat, 0)
                _floor = _cat_mins.get(cat, 0)
                _line = f"- {cat}: avg ${avg:,}/mo, this month ${_cur:,.0f}"
                if _floor > 0:
                    _line += f", MIN ${_floor:,} (user set)"
                _cat_lines.append(_line)

            # Top merchants this month for context
            _merchant_ctx = ""
            _top_merchants = conn.execute(
                """SELECT category, description, SUM(ABS(amount)) as total
                   FROM transactions
                   WHERE strftime('%Y-%m', date) = ? AND amount < 0
                   GROUP BY category, description
                   ORDER BY total DESC LIMIT 20""",
                (_current_month,)
            ).fetchall()
            if _top_merchants:
                _merchant_ctx = "TOP MERCHANTS THIS MONTH:\n" + "\n".join(
                    f"  {m['category']}: {m['description'][:30]} ${m['total']:,.0f}"
                    for m in _top_merchants
                ) + "\n\n"

            _days_in = _cal.monthrange(_today.year, _today.month)[1]
            _days_left = max(_days_in - _today.day, 0)

            _achievability = ""
            if not _target_achievable:
                _achievability = (
                    f"\nNOTE: The user's minimum floors total ${_min_total:,}, "
                    f"which exceeds the flex budget of ${_flex_budget:,.0f}. "
                    f"The savings target is NOT fully achievable with these "
                    f"constraints. Set each category to its minimum floor. "
                    f'Add a "warning" field to your JSON explaining this.\n'
                )

            _rec_prompt = (
                "You are a smart budget planner. Analyze the user's ACTUAL "
                "spending this month and their historical patterns to create "
                "a realistic plan that hits their savings target.\n\n"
                f"INCOME: ${_monthly_income:,.0f}/mo\n"
                f"FIXED BILLS: ${_effective_fixed:,.0f}/mo\n"
                f"SAVINGS TARGET: ${savings_target:,}/mo\n"
                f"FLEX BUDGET: ${_flex_budget:,.0f}/mo — MAXIMUM total for "
                f"all categories combined\n"
                f"DAY {_today.day} of {_days_in} ({_days_left} days left)\n\n"
                f"CATEGORIES (avg = 6-month average, this month = actual):\n"
                + "\n".join(_cat_lines) + "\n\n"
                + _merchant_ctx
                + f"TOTAL TYPICAL: ${_total_typical:,.0f}/mo\n"
                f"NEEDED CUTS: ${max(_total_typical - _flex_budget, 0):,.0f}\n"
                + _achievability + "\n"
                "CRITICAL CONSTRAINTS:\n"
                f"- Sum of ALL targets MUST be <= ${_flex_budget:,.0f}.\n"
                "- Categories with MIN values MUST NOT go below that minimum.\n"
                "- Include EVERY category. No exceptions.\n\n"
                "BE SMART:\n"
                "- Look at this month's ACTUAL spending. If a category is "
                "already low this month, set the target near that level.\n"
                "- If a category has a big one-time expense (home improvement, "
                "immigration fees), target $0 or its minimum — it won't recur.\n"
                "- Groceries are essential — cut modestly (10-25%).\n"
                "- Healthcare: cut very little.\n"
                "- Dining Out, Entertainment: highly cuttable (40-70%).\n"
                "- Online Shopping: cuttable (30-60%).\n"
                "- Look at the merchants — if spending is spread across many "
                "small purchases, it's cuttable. If it's one big purchase, "
                "it may be one-time.\n"
                "- Round to nearest $25.\n"
                f"- SEED {random.randint(1, 999)}: vary your approach.\n\n"
                "VERIFY: Add your targets. "
                f"Total must be <= ${_flex_budget:,.0f}.\n\n"
                "Return ONLY valid JSON. No markdown. No code fences.\n"
                'Example: {"Groceries": 1750, "Dining Out": 300, ...}'
            )
            with st.spinner("Claude is thinking..."):
                try:
                    _rec = advisor.generate_coach_response(
                        _rec_prompt, max_tokens=512)

                    # Handle nested response wrappers
                    if isinstance(_rec, dict) and "response" in _rec:
                        _inner = _rec["response"]
                        if isinstance(_inner, dict):
                            _rec = _inner
                        elif isinstance(_inner, str):
                            try:
                                _rec = json.loads(_inner)
                            except (json.JSONDecodeError, ValueError):
                                pass

                    if isinstance(_rec, dict):
                        # Show warning from Claude if present
                        _warning = _rec.pop("warning", None)

                        # Apply Claude's targets with min floors
                        _targets = {}
                        _avg_map = dict(_cat_avg_sorted)
                        for cat, avg in _cat_avg_sorted:
                            _floor = _cat_mins.get(cat, 0)
                            _raw = _rec.get(cat)
                            if _raw is not None:
                                _val = int(float(_raw))
                            else:
                                _val = _floor  # missing = use floor
                            _val = max(_floor, min(_val, avg))
                            _val = round(_val / 25) * 25
                            _val = max(_floor, _val)  # re-enforce after rounding
                            _targets[cat] = _val

                        # Hard constraint: scale down if over budget
                        _plan_total = sum(_targets.values())
                        if _plan_total > _flex_budget and _plan_total > 0:
                            _excess = _plan_total - _flex_budget
                            # Only scale the cuttable portion (above minimums)
                            _cuttable = {c: _targets[c] - _cat_mins.get(c, 0)
                                         for c in _targets
                                         if _targets[c] > _cat_mins.get(c, 0)}
                            _cuttable_total = sum(_cuttable.values())
                            if _cuttable_total > 0:
                                _cut_ratio = min(_excess / _cuttable_total, 1.0)
                                for c, headroom in _cuttable.items():
                                    _cut = round(headroom * _cut_ratio / 25) * 25
                                    _targets[c] = max(
                                        _cat_mins.get(c, 0),
                                        _targets[c] - _cut
                                    )

                        st.session_state.plan_targets.update(_targets)
                        # Also update slider widget keys so they reflect new values
                        for c, v in _targets.items():
                            st.session_state[f"plan_slider_{c}"] = v

                        if _warning:
                            st.warning(f"Claude says: {_warning}")

                        st.rerun()
                    else:
                        st.error("Unexpected response format. Try again.")
                except Exception as e:
                    st.error(f"Could not generate a plan: {str(e)[:120]}")
        else:
            st.warning("Set your Anthropic API key in Settings first.")

    # ── Set minimum spending per category ────────────────────────────
    with st.expander("⚙ Set minimum spending per category"):
        _mins_changed = False
        for _row_start in range(0, len(_cat_avg_sorted), 2):
            _row_cats = _cat_avg_sorted[_row_start:_row_start + 2]
            _cols = st.columns(len(_row_cats))
            for _col, (cat, avg) in zip(_cols, _row_cats):
                _min_key = f"min_{cat}"
                _cur_min = min(_cat_mins.get(cat, 0), avg)
                _short = cat[:18] + "…" if len(cat) > 18 else cat
                _new_min = _col.number_input(
                    _short, min_value=0, max_value=avg, value=_cur_min,
                    step=25, key=_min_key,
                )
                if _new_min != _cur_min:
                    _cat_mins[cat] = _new_min
                    _mins_changed = True
        if _mins_changed:
            st.session_state.plan_minimums = _cat_mins
            database.set_setting(conn, "category_min_targets",
                                 json.dumps(_cat_mins))
            for cat, avg in _cat_avg_sorted:
                _floor = _cat_mins.get(cat, 0)
                if st.session_state.plan_targets.get(cat, avg) < _floor:
                    st.session_state.plan_targets[cat] = _floor

    # Realism check
    _min_total = sum(_cat_mins.get(cat, 0) for cat, _ in _cat_avg_sorted)
    _target_achievable = _min_total <= _flex_budget
    if not _target_achievable:
        _shortfall = _min_total - _flex_budget
        st.warning(
            f"With your minimum floors (totaling ${_min_total:,}), "
            f"the ${savings_target:,}/mo savings target is ${_shortfall:,.0f} "
            f"short. Claude will get as close as possible."
        )

    # ── Sliders inside a bordered container ───────────────────────
    _main_cats = _cat_avg_sorted[:5]
    _extra_cats = _cat_avg_sorted[5:]

    _total_planned = 0
    _slider_results = []

    _slider_container = st.container(border=True)
    with _slider_container:
        render_plan_sliders_header(_flex_budget)

    # Main 5 category sliders (inside the container)
    with _slider_container:
        for i, (cat, typical) in enumerate(_main_cats):
            _key = f"plan_slider_{cat}"
            _floor = _cat_mins.get(cat, 0)
            if _key not in st.session_state:
                _init = st.session_state.plan_targets.get(cat, typical)
                st.session_state[_key] = max(_floor, min(_init, typical))
            _current = min(st.session_state[_key], typical)
            st.session_state[_key] = _current
            _color = _CAT_COLORS[i % len(_CAT_COLORS)]

            _cut_preview = typical - _current
            _badge = ""
            if _cut_preview > 0:
                _badge = (
                    f'<span style="font-size:11px;font-weight:600;color:#0d9488;'
                    f'background:#f0fdfa;padding:2px 6px;border-radius:4px;'
                    f'margin-left:6px;">−${_cut_preview:,}</span>'
                )
            _val_color = "#0d9488" if _current < typical else "#64748b"
            st.markdown(
                f'<div style="display:flex;align-items:center;'
                f'justify-content:space-between;margin-bottom:-10px;'
                f'margin-top:8px;">'
                f'<div style="display:flex;align-items:center;">'
                f'<span style="width:10px;height:10px;border-radius:50%;'
                f'background:{_color};display:inline-block;margin-right:6px;'
                f'flex-shrink:0;"></span>'
                f'<span style="font-size:13px;font-weight:500;color:var(--vw-text);">'
                f'{cat}</span>'
                f'<span data-slider-val="{cat}" style="font-size:13px;font-weight:700;color:{_val_color};'
                f'margin-left:8px;">${_current:,}</span></div>'
                f'<div style="display:flex;align-items:center;">'
                f'<span style="font-size:11px;color:#94a3b8;">'
                f'of ${typical:,}</span>'
                f'{_badge}</div></div>',
                unsafe_allow_html=True,
            )

            val = st.slider(
                label=cat,
                min_value=_floor,
                max_value=typical,
                step=25,
                key=_key,
                label_visibility="collapsed",
            )
            st.session_state.plan_targets[cat] = val
            _total_planned += val
            _slider_results.append((cat, typical, val, i))

    # Extra categories behind expander
    if _extra_cats:
        _extra_total_typical = sum(avg for _, avg in _extra_cats)
        with st.expander(
            f"+ {len(_extra_cats)} smaller categories "
            f"(${_extra_total_typical:,}/mo)"
        ):
            for i, (cat, typical) in enumerate(_extra_cats, start=len(_main_cats)):
                _key = f"plan_slider_{cat}"
                _floor = _cat_mins.get(cat, 0)
                if _key not in st.session_state:
                    _init = st.session_state.plan_targets.get(cat, typical)
                    st.session_state[_key] = max(_floor, min(_init, typical))
                _current = min(st.session_state[_key], typical)  # clamp if avg dropped
                st.session_state[_key] = _current
                _color = _CAT_COLORS[i % len(_CAT_COLORS)]

                _cut_preview = typical - _current
                _badge = ""
                if _cut_preview > 0:
                    _badge = (
                        f'<span style="font-size:10px;font-weight:600;'
                        f'color:#0d9488;background:#f0fdfa;padding:2px 6px;'
                        f'border-radius:4px;margin-left:6px;">'
                        f'−${_cut_preview:,}</span>'
                    )
                _val_color = "#0d9488" if _current < typical else "#64748b"
                st.markdown(
                    f'<div style="display:flex;align-items:center;'
                    f'justify-content:space-between;'
                    f'margin-bottom:-10px;margin-top:4px;">'
                    f'<div style="display:flex;align-items:center;">'
                    f'<span style="width:8px;height:8px;border-radius:50%;'
                    f'background:{_color};display:inline-block;'
                    f'margin-right:6px;"></span>'
                    f'<span style="font-size:12px;color:var(--vw-text);">'
                    f'{cat}</span>'
                    f'<span data-slider-val="{cat}" style="font-size:12px;font-weight:700;'
                    f'color:{_val_color};margin-left:6px;">'
                    f'${_current:,}</span></div>'
                    f'<div style="display:flex;align-items:center;">'
                    f'<span style="font-size:10px;color:#94a3b8;">'
                    f'of ${typical:,}</span>'
                    f'{_badge}</div></div>',
                    unsafe_allow_html=True,
                )

                val = st.slider(
                    label=cat,
                    min_value=_floor,
                    max_value=typical,
                    step=25,
                    key=_key,
                    label_visibility="collapsed",
                )
                st.session_state.plan_targets[cat] = val
                _total_planned += val
                _slider_results.append((cat, typical, val, i))

    # ── Live slider value JS ──────────────────────────────────────────
    st.markdown("""
    <script>
    (function() {
        // Update custom value labels in real-time during slider drag
        function attachObservers() {
            const thumbs = document.querySelectorAll('[role="slider"]');
            thumbs.forEach(function(thumb) {
                if (thumb._liveObserver) return;  // already attached
                const observer = new MutationObserver(function() {
                    const raw = parseInt(thumb.getAttribute('aria-valuenow'), 10);
                    if (isNaN(raw)) return;
                    const formatted = '$' + raw.toLocaleString();
                    // Walk up to the stSlider container, then find preceding label
                    let container = thumb.closest('[data-testid="stVerticalBlock"]')
                        || thumb.closest('[data-testid="column"]')
                        || thumb.parentElement;
                    // Search siblings above for the data-slider-val span
                    let el = thumb.closest('[data-testid="stSlider"]');
                    if (!el) return;
                    let prev = el.previousElementSibling;
                    // Walk up through wrappers to find the markdown div
                    while (prev && !prev.querySelector('[data-slider-val]')) {
                        prev = prev.previousElementSibling;
                    }
                    if (prev) {
                        const label = prev.querySelector('[data-slider-val]');
                        if (label) label.textContent = formatted;
                    }
                });
                observer.observe(thumb, { attributes: true, attributeFilter: ['aria-valuenow'] });
                thumb._liveObserver = true;
            });
        }
        // Run on load and re-run periodically (Streamlit re-renders)
        attachObservers();
        setInterval(attachObservers, 1000);
    })();
    </script>
    """, unsafe_allow_html=True)

    # ── Computed values ──────────────────────────────────────────────
    _total_cuts = _total_typical - _total_planned
    _projected_savings = _monthly_income - _effective_fixed - _total_planned

    # Impact bar inside the slider container
    with _slider_container:
        render_plan_impact_bar(_total_cuts)

    # ── Action buttons ──────────────────────────────────────────────
    _btn1, _btn2 = st.columns(2)
    with _btn1:
        if st.button("Reset to Typical", use_container_width=True):
            for cat, avg in _cat_avg_sorted:
                st.session_state.plan_targets[cat] = avg
                st.session_state[f"plan_slider_{cat}"] = avg
            st.rerun()
    with _btn2:
        if st.button("Accept Plan", type="primary", use_container_width=True):
            database.set_setting(conn, "flex_category_targets", json.dumps(st.session_state.plan_targets))
            st.success(f"Plan saved! Targeting ${_projected_savings:,}/mo in savings.")

    # ══════════════════════════════════════════════════════════════════
    # FILL PLAN HERO + YEAR PROJECTION placeholders
    # ══════════════════════════════════════════════════════════════════
    with _hero_placeholder.container():
        render_plan_hero_v2(
            _monthly_income, _effective_fixed, _savings_target,
            _flex_budget, _projected_savings, _month_label,
        )

    with _year_placeholder.container():
        _daycare_amt = config.FIXED_MONTHLY_EXPENSES.get("Daycare", 0)
        render_plan_year_pills(_projected_savings, daycare_amount=_daycare_amt)

    # ══════════════════════════════════════════════════════════════════
    # SECTION 4: REAL TALK (conditional)
    # ══════════════════════════════════════════════════════════════════
    if (_total_cuts > 0
            and _projected_savings < _savings_target
            and _total_planned < _total_typical * 0.5):
        _still_short = _savings_target - _projected_savings
        _actual_saving = max(0, _projected_savings)
        st.markdown(
            f'<div style="background:#fffbeb;border:1px solid #fde68a;'
            f'border-radius:12px;padding:14px 16px;margin-top:16px;">'
            f'<p style="font-size:14px;font-weight:600;color:#92400e;'
            f'margin:0 0 6px;">💡 Real talk</p>'
            f'<p style="font-size:13px;color:#92400e;margin:0;'
            f'line-height:1.5;">'
            f'You\'ve cut hard and you\'re still ${_still_short:,} short '
            f'of your ${_savings_target:,} target. Consider: is '
            f'${_savings_target:,}/mo realistic right now, or would '
            f'saving ${_actual_saving:,}/mo actually be a win?</p></div>',
            unsafe_allow_html=True,
        )

    conn.close()
