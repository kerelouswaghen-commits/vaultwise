"""Transactions page — Upload statements, browse, fix categories."""

import re
from calendar import monthrange as _monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import analytics_cache
import category_engine
import chase_report_parser
import config
import csv_parser
import database
import models
import pdf_parser
from shared.charts import CHART_LAYOUT, CATEGORY_PALETTE
from shared.components import (
    render_dark_summary, render_txn_group, render_txn_group_v2,
    render_txn_summary, render_txn_quick_stats, get_category_icon,
)
from shared.state import get_conn, get_advisor, normalize_date, normalize_transactions

# ── Spending-type classification (shared across the page) ─────────────
# Initialized lazily once conn is available (see transactions_page)
_muted_cats = set()
_fixed_cats = set()


def _init_category_sets(conn):
    global _muted_cats, _fixed_cats
    from shared.filters import get_excluded_categories, get_fixed_categories
    _muted_cats = get_excluded_categories(conn)
    _fixed_cats = get_fixed_categories(conn)


def _get_tag(category):
    if category in _muted_cats:
        return "muted"
    elif category in _fixed_cats:
        return "fixed"
    else:
        return "flex"


_TAG_PILLS = {
    "flex":  '<span style="background:#22c55e22;color:#16a34a;padding:1px 8px;border-radius:10px;font-size:0.82em">flex</span>',
    "fixed": '<span style="background:#71717a22;color:#71717a;padding:1px 8px;border-radius:10px;font-size:0.82em">fixed</span>',
    "muted": '<span style="background:#ef444422;color:#ef4444;padding:1px 8px;border-radius:10px;font-size:0.82em">muted</span>',
}


def _upload_section(conn, coverage):
    """Upload statements logic — extracted so it can live in an expander."""
    if coverage is None:
        coverage = database.get_account_coverage(conn)
    if coverage:
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

            month_labels = [datetime.strptime(m, "%Y-%m").strftime("%b %y") for m in all_months_range]
            completeness_pct = (filled_cells / total_cells * 100) if total_cells > 0 else 0

            st.caption(f"**{completeness_pct:.0f}%** coverage ({filled_cells} of {total_cells} account-months)")

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

    # File uploader — always visible
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

            _old_statement = False
            if period_start and period_start != "unknown":
                try:
                    _ps = date.fromisoformat(period_start)
                    _age_days = (date.today() - _ps).days
                    if _age_days > 365:
                        st.warning(f"This statement is from **{period_start}** ({_age_days // 30} months ago). "
                                   f"Old data may reduce forecast accuracy.")
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

            # STEP 4: Auto-import
            transactions = result.get("transactions", [])
            if not transactions:
                st.warning("No transactions found.")
                continue

            year_hint = (period_start or "")[:4] if period_start and period_start != "unknown" else ""
            transactions = normalize_transactions(transactions, year_hint)
            period_start = normalize_date(period_start or "unknown", year_hint)
            period_end = normalize_date(period_end or "unknown", year_hint)

            valid_txns = []
            bad_dates = 0
            for txn in transactions:
                d = txn.get("date", "")
                if d and d != "unknown" and re.match(r'^\d{4}-\d{2}-\d{2}$', d):
                    valid_txns.append(txn)
                else:
                    bad_dates += 1
            if bad_dates > 0:
                st.warning(f"Skipped {bad_dates} transactions with invalid dates.")
            transactions = valid_txns

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
            database.apply_merchant_overrides(conn)
            skipped = len(transactions) - inserted

            analytics_cache.invalidate(conn)
            st.session_state['analytics_stale'] = True

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

            charges = sum(t["amount"] for t in transactions if t["amount"] < 0)
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

                from collections import Counter
                cat_counts = Counter(t["category"] for t in transactions if t["amount"] < 0)
                cat_totals = {}
                for t in transactions:
                    if t["amount"] < 0:
                        cat_totals[t["category"]] = cat_totals.get(t["category"], 0) + abs(t["amount"])
                with st.expander(f"Category breakdown ({len(cat_counts)} categories)"):
                    for cat, total in sorted(cat_totals.items(), key=lambda x: -x[1]):
                        st.write(f"**{cat}**: \\${total:,.2f} ({cat_counts[cat]} txns)")

    # If no transactions, stop
    txn_count = database.get_transaction_count(conn)
    if txn_count == 0:
        st.info("No transactions yet. Upload a statement below to get started.")
        with st.expander("📤 Upload Statements", expanded=True):
            _upload_section(conn, None)
        conn.close()
        st.stop()


def _category_analysis_section(conn, hide_transfers):
    """Category Analysis — extracted for the bottom expander."""
    cat_stats = category_engine.get_category_stats(conn)
    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("Category Coverage", f"{cat_stats['coverage_pct']}%")
    sc2.metric("Uncategorized (Other)", f"{cat_stats['other_count']} txns ({cat_stats['other_pct']}%)")
    sc3.metric("Low Confidence", f"{cat_stats['low_confidence_count']} txns ({cat_stats['low_confidence_pct']}%)")

    _active_cats = category_engine.get_active_categories(conn)
    if hide_transfers:
        _active_cats = [c for c in _active_cats if c not in _muted_cats]
    _active_placeholder = ",".join(f"'{c}'" for c in _active_cats)

    st.markdown("#### Category Distribution")
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
        st.plotly_chart(fig_tree, width="stretch", config={"displayModeBar": False})

    st.markdown("#### Category Trends Over Time")
    monthly_cat_rows = conn.execute(f"""
        SELECT strftime('%Y-%m', date) as month, category, ABS(SUM(amount)) as total
        FROM transactions WHERE amount < 0 AND category IN ({_active_placeholder})
        GROUP BY month, category ORDER BY month
    """).fetchall()

    if monthly_cat_rows:
        mc_df = pd.DataFrame([dict(r) for r in monthly_cat_rows])
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
        st.plotly_chart(fig_area, width="stretch", config={"displayModeBar": False})
    else:
        st.info("Not enough data for trend analysis.")


def transactions_page():
    conn = get_conn()
    _init_category_sets(conn)
    txn_count = database.get_transaction_count(conn)
    coverage = database.get_account_coverage(conn)

    if txn_count == 0:
        st.info("No transactions yet. Upload a statement below to get started.")
        with st.expander("📤 Upload Statements", expanded=True):
            _upload_section(conn, coverage)
        conn.close()
        st.stop()

    # ══════════════════════════════════════════════════════════════════
    # 1. FILTERS (compact row)
    # ══════════════════════════════════════════════════════════════════
    active_categories = category_engine.get_active_categories(conn)
    date_range = database.get_date_range(conn)

    _search_q = st.text_input("🔍 Search transactions", placeholder="Search merchants, categories...", label_visibility="collapsed")

    _fc1, _fc2 = st.columns(2)
    with _fc1:
        start = st.date_input("From", value=date.fromisoformat(date_range[0]) if date_range[0] else date.today() - timedelta(days=90), label_visibility="collapsed")
    with _fc2:
        end = st.date_input("To", value=date.fromisoformat(date_range[1]) if date_range[1] else date.today(), label_visibility="collapsed")

    _fc3, _fc4 = st.columns(2)
    with _fc3:
        _acct_ids = ["All"] + list(config.ACCOUNTS.keys())
        def _fmt_acct(a):
            if a == "All":
                return "All Accounts"
            return config.ACCOUNTS.get(a, {}).get("label", a)
        acct = st.selectbox("Account", _acct_ids, format_func=_fmt_acct, label_visibility="collapsed")
    with _fc4:
        _cat_list = ["All"] + active_categories
        def _fmt_cat(c):
            if c == "All":
                return "All Categories"
            return c
        cat = st.selectbox("Category", _cat_list, format_func=_fmt_cat, label_visibility="collapsed")

    hide_transfers = st.checkbox("Hide transfers & CC payments", value=True)

    # ══════════════════════════════════════════════════════════════════
    # 2. FETCH & FILTER DATA
    # ══════════════════════════════════════════════════════════════════
    txns = database.get_transactions(
        conn, start_date=start.isoformat(), end_date=end.isoformat(),
        account_id=acct if acct != "All" else None,
        category=cat if cat != "All" else None,
    )

    if not txns:
        st.info("No transactions match these filters.")
        # Still show upload + analysis at bottom
        with st.expander("📤 Upload Statements"):
            _upload_section(conn, coverage)
        with st.expander("📊 Category Analysis"):
            _category_analysis_section(conn, hide_transfers)
        conn.close()
        return

    df = pd.DataFrame([dict(t) for t in txns])
    df["tag"] = df["category"].apply(_get_tag)

    if hide_transfers and cat == "All":
        _hide_cats = set(_muted_cats)  # _muted_cats = get_excluded_categories(conn) which includes config
        df = df[~df["category"].isin(_hide_cats)]

    if _search_q:
        df = df[df["description"].str.contains(_search_q, case=False, na=False) |
                df["category"].str.contains(_search_q, case=False, na=False)]

    if df.empty:
        st.info("No transactions match these filters.")
        conn.close()
        return

    # ══════════════════════════════════════════════════════════════════
    # 3. SPENDING SUMMARY HERO
    # ══════════════════════════════════════════════════════════════════
    _spending_df = df[df["amount"] < 0]
    _total_spent = abs(_spending_df["amount"].sum()) if not _spending_df.empty else 0
    _txn_count = len(df)

    _from_mo = start.strftime("%Y-%m")
    _to_mo = end.strftime("%Y-%m")
    _single_month = (_from_mo == _to_mo)

    if _single_month:
        from calendar import month_name
        _month_label = f"{month_name[start.month]} {start.year}"
    else:
        _month_label = f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"

    # Category breakdown for the bar
    _cat_totals = {}
    if not _spending_df.empty:
        _cat_totals = _spending_df.groupby("category")["amount"].sum().abs().sort_values(ascending=False).to_dict()

    render_txn_summary(_month_label, _txn_count, _total_spent, _cat_totals)

    # ══════════════════════════════════════════════════════════════════
    # 4. QUICK STATS
    # ══════════════════════════════════════════════════════════════════
    _days_range = max((end - start).days, 1)
    _avg_per_day = _total_spent / _days_range if _total_spent > 0 else 0
    _largest = abs(_spending_df["amount"].min()) if not _spending_df.empty else 0

    _flex_remaining = 0
    if _single_month:
        savings_target = int(database.get_setting(conn, "monthly_savings_target", "2000"))
        _flex_total = abs(df[(df["amount"] < 0) & (~df["category"].isin(_fixed_cats)) & (~df["category"].isin(_muted_cats))]["amount"].sum())
        _inc = models.get_income_for_month(start.year, start.month)
        _txn_page_income = _inc["total_income"] - _inc.get("kero_bonus", 0) - _inc.get("maggie_bonus", 0)
        _spending_money = _txn_page_income - sum(config.FIXED_MONTHLY_EXPENSES.values()) - savings_target
        _flex_remaining = _spending_money - _flex_total

    render_txn_quick_stats(_avg_per_day, _largest, _flex_remaining)

    # ══════════════════════════════════════════════════════════════════
    # 5. TRANSACTION GROUPS (V2 cards)
    # ══════════════════════════════════════════════════════════════════
    df_sorted = df.sort_values("date", ascending=False)
    _grouped = df_sorted.groupby("date", sort=False)

    def _build_txn_rows(group):
        rows = []
        for _, row in group.iterrows():
            _icon, _bg = get_category_icon(row["category"])
            _acct_label = config.ACCOUNTS.get(row.get("account_id", ""), {}).get("label", row.get("account_id", ""))
            rows.append({
                "icon": _icon, "bg_color": _bg,
                "name": str(row["description"])[:40],
                "category": row["category"],
                "account": _acct_label,
                "amount": row["amount"],
                "tag": row.get("tag", "flex"),
            })
        return rows

    def _format_date_label(date_str):
        try:
            _dt = date.fromisoformat(str(date_str))
            if _dt == date.today():
                return f"Today · {_dt.strftime('%b %d')}"
            elif _dt == date.today() - timedelta(days=1):
                return f"Yesterday · {_dt.strftime('%b %d')}"
            else:
                return f"{_dt.strftime('%a')} · {_dt.strftime('%b %d')}"
        except Exception:
            return str(date_str).upper()

    _group_count = 0
    for _date_str, _group in _grouped:
        if _group_count >= 30:
            break
        _date_label = _format_date_label(_date_str)
        _daily_total = _group[_group["amount"] < 0]["amount"].sum()
        _txn_rows = _build_txn_rows(_group)
        render_txn_group_v2(_date_label, _daily_total, _txn_rows)
        _group_count += 1

    _total_groups = len(df_sorted["date"].unique())
    _remaining = _total_groups - 30
    if _remaining > 0:
        if st.button(f"Show {_remaining} more date groups"):
            _extra_count = 0
            for _date_str, _group in _grouped:
                _extra_count += 1
                if _extra_count <= 30:
                    continue
                _date_label = _format_date_label(_date_str)
                _daily_total = _group[_group["amount"] < 0]["amount"].sum()
                _txn_rows = _build_txn_rows(_group)
                render_txn_group_v2(_date_label, _daily_total, _txn_rows)

    # ══════════════════════════════════════════════════════════════════
    # 6. DATA QUALITY CHECKS
    # ══════════════════════════════════════════════════════════════════
    _merchant_cats = defaultdict(set)
    for _, row in df[df["amount"] < 0].iterrows():
        _clean = row["description"].split("*")[0].split("#")[0].strip()[:20]
        _merchant_cats[_clean].add(row["category"])

    _multi_cat = {m: cats for m, cats in _merchant_cats.items() if len(cats) > 1}
    if _multi_cat:
        with st.expander(f"⚠️ {len(_multi_cat)} merchants in multiple categories"):
            for _merchant, _cats in sorted(_multi_cat.items()):
                st.markdown(f'**{_merchant}** → {", ".join(sorted(_cats))}')
            st.caption("These merchants are split across categories. Use 'Recategorize with Claude' to clean them up.")

    try:
        _recurring = conn.execute("""
            SELECT description, category,
                   COUNT(DISTINCT strftime('%Y-%m', date)) as months,
                   ROUND(AVG(ABS(amount)), 2) as avg_amount
            FROM transactions
            WHERE amount < 0 AND date >= date('now', '-6 months')
            GROUP BY description, category
            HAVING months >= 4 AND avg_amount > 50
            ORDER BY avg_amount DESC
        """).fetchall()
        _not_in_fixed = [r for r in _recurring if r["category"] not in _fixed_cats and r["category"] not in _muted_cats]
        if _not_in_fixed:
            with st.expander(f"📋 {len(_not_in_fixed)} possible fixed bills not configured"):
                for r in _not_in_fixed[:10]:
                    st.markdown(f'**{r["description"][:30]}** — ${r["avg_amount"]:,.0f}/mo ({r["months"]} months) — {r["category"]}')
                st.caption("Consider adding them to Fixed Monthly Bills in Setup.")
    except Exception:
        pass

    # ══════════════════════════════════════════════════════════════════
    # 7. EXPORT
    # ══════════════════════════════════════════════════════════════════
    csv_data = df.to_csv(index=False)
    st.download_button("📥 Export CSV", csv_data, "transactions.csv", "text/csv")

    # ══════════════════════════════════════════════════════════════════
    # 8. UPLOAD STATEMENTS (bottom expander)
    # ══════════════════════════════════════════════════════════════════
    with st.expander("📤 Upload Statements"):
        _upload_section(conn, coverage)

    # ══════════════════════════════════════════════════════════════════
    # 9. CATEGORY ANALYSIS (bottom expander)
    # ══════════════════════════════════════════════════════════════════
    with st.expander("📊 Category Analysis"):
        _category_analysis_section(conn, hide_transfers)

    conn.close()
