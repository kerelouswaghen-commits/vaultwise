"""Transactions page — Upload statements, browse, fix categories."""

import re
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
import pdf_parser
from shared.charts import CHART_LAYOUT, CATEGORY_PALETTE
from shared.state import get_conn, get_advisor, normalize_date, normalize_transactions


def transactions_page():
    st.markdown("## Transactions")
    conn = get_conn()
    txn_count = database.get_transaction_count(conn)

    # ── Upload Statements (always visible at top) ─────────────────────
    st.markdown("#### Upload Statements")
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

            st.markdown("##### Coverage Heatmap")
            st.caption(f"**{completeness_pct:.0f}%** complete ({filled_cells} of {total_cells} account-months)")

            fig_heat = go.Figure(data=go.Heatmap(
                z=z_data, x=month_labels, y=acct_labels,
                colorscale=[[0, '#ef4444'], [1, '#22c55e']],
                showscale=True,
                colorbar=dict(title="", tickvals=[0, 1], ticktext=["Missing", "Has Data"], len=0.5, thickness=12),
                hovertemplate="<b>%{y}</b><br>%{x}<br>%{customdata}<extra></extra>",
                customdata=[["Has data" if cell == 1 else "Missing" for cell in row] for row in z_data],
                xgap=3, ygap=4,
            ))
            tick_interval = max(1, len(month_labels) // 15)
            fig_heat.update_layout(
                **CHART_LAYOUT,
                height=max(180, 55 * len(all_acct_ids)),
                xaxis=dict(side="top", tickangle=-45, dtick=tick_interval),
                yaxis=dict(autorange="reversed"),
            )
            st.plotly_chart(fig_heat, use_container_width=True, config={"displayModeBar": False})

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
        st.info("No transactions yet. Upload a statement above to get started.")
        conn.close()
        st.stop()

    st.divider()
    active_categories = category_engine.get_active_categories(conn)

    # Only 2 tabs now (Recategorize moved to Settings)
    tab_txns, tab_analysis = st.tabs(["Transactions", "Category Analysis"])

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
        cat_stats = category_engine.get_category_stats(conn)
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Category Coverage", f"{cat_stats['coverage_pct']}%")
        sc2.metric("Uncategorized (Other)", f"{cat_stats['other_count']} txns ({cat_stats['other_pct']}%)")
        sc3.metric("Low Confidence", f"{cat_stats['low_confidence_count']} txns ({cat_stats['low_confidence_pct']}%)")

        st.markdown(f"**{cat_stats['coverage_pct']}%** of spending transactions are categorized. "
                    f"**{cat_stats['other_count']}** transactions remain as 'Other'.")

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
            st.plotly_chart(fig_area, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Not enough data for trend analysis.")

    conn.close()
