#!/usr/bin/env python3
"""
Telegram bot listener — receives PDF/CSV files from family members,
auto-parses them, imports to database, and replies with a summary.

Supports multi-chat (Kero + Maggie), weekly upload tracking, and
auto-triggers the weekly report once all accounts are uploaded.

Run alongside the Streamlit app:
    python telegram_listener.py

Uses polling (no webhook needed — works behind NAT/firewall).
"""

import io
import os
import sys
import time
import json
import hashlib
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import database
import pdf_parser
import csv_parser
import chase_report_parser


DB_PATH = os.path.join(os.path.dirname(__file__), "data", config.DB_FILENAME)

# Friendly display names for accounts (from config)
ACCOUNT_LABELS = {acct_id: info.get("label", acct_id) for acct_id, info in config.ACCOUNTS.items()}


def get_settings():
    """Load bot token and allowed chat IDs from database."""
    database.init_db(DB_PATH)
    conn = database.get_connection(DB_PATH)
    token = database.get_setting(conn, "telegram_bot_token")
    chat_id = database.get_setting(conn, "telegram_chat_id")
    conn.close()
    return token, chat_id


def get_allowed_chat_ids():
    """Return set of all known chat IDs (Kero + Maggie)."""
    conn = database.get_connection(DB_PATH)
    ids = set()
    for user_info in config.TELEGRAM_USERS.values():
        cid = database.get_setting(conn, user_info["setting_key"])
        if cid:
            ids.add(str(cid))
    conn.close()
    return ids


def send_message(token, chat_id, text, parse_mode="HTML"):
    """Send a text message."""
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4096], "parse_mode": parse_mode},
        timeout=30,
    )


def download_file(token, file_id):
    """Download a file from Telegram servers."""
    # Get file path
    resp = requests.get(
        f"https://api.telegram.org/bot{token}/getFile",
        params={"file_id": file_id},
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        return None, None

    file_path = data["result"]["file_path"]
    filename = file_path.split("/")[-1]

    # Download
    resp = requests.get(
        f"https://api.telegram.org/file/bot{token}/{file_path}",
        timeout=60,
    )
    return resp.content, filename


def _track_upload(conn, account_id, chat_id, token):
    """Track a successful upload in the weekly cycle and check completion."""
    week_start = database.get_current_week_start()
    database.init_weekly_cycle(conn, week_start)
    database.mark_account_uploaded(conn, week_start, account_id)

    if database.is_week_complete(conn, week_start):
        send_message(token, chat_id, "\u2705 All accounts received! Generating weekly report...")
        _trigger_weekly_report(token, conn)
    else:
        status = database.get_weekly_status(conn, week_start)
        missing = [aid for aid, info in status.items() if not info["uploaded"]]
        done = [aid for aid, info in status.items() if info["uploaded"]]
        lines = ["\U0001f4cb <b>Weekly upload progress:</b>"]
        for aid in done:
            lines.append(f"  \u2705 {ACCOUNT_LABELS.get(aid, aid)}")
        for aid in missing:
            lines.append(f"  \u23f3 {ACCOUNT_LABELS.get(aid, aid)}")
        lines.append(f"\n{len(done)}/{len(done)+len(missing)} uploaded")
        send_message(token, chat_id, "\n".join(lines))


def _trigger_weekly_report(token, conn):
    """Generate and send the weekly report to all chat IDs."""
    try:
        # Import here to avoid circular imports
        import reports
        import spending_intelligence
        import chart_generator
        from claude_advisor import ClaudeAdvisor
        from telegram_bot import TelegramReporter, format_weekly_report_html

        api_key = database.get_setting(conn, "anthropic_api_key")
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            _send_to_all(token, conn, "Cannot generate report: no API key configured.")
            return

        report_data = reports.gather_report_data(conn)
        tactical = spending_intelligence.build_tactical_context(conn)
        report_data["budget_status"] = tactical.get("budget_status", [])
        report_data["savings_tips"] = tactical.get("savings_tips", [])
        report_data["last_week_total"] = tactical.get("last_week", {}).get("total")

        advisor = ClaudeAdvisor(api_key=api_key)
        claude_report = advisor.generate_weekly_report(
            week_transactions=report_data["week_transactions"],
            monthly_context=report_data["mtd_summary"],
            objective_progress=report_data["objective_progress"],
            alerts=report_data["alerts"],
        )
        report_data["action_items"] = claude_report.get("action_items", [])

        # Generate charts (filtered — excludes transfers/payments)
        charts = []
        try:
            from shared.filters import get_fixed_categories, get_excluded_categories
            _chart_excl = get_excluded_categories(conn) | get_fixed_categories(conn)
            this_week = database.get_weekly_spending(conn, exclude_categories=_chart_excl)
            if this_week.get("categories"):
                charts.append((
                    chart_generator.generate_weekly_spending_chart(this_week),
                    "This Week's Spending by Category",
                ))
            trend = database.get_spending_trend(conn, months=6)
            if trend:
                charts.append((
                    chart_generator.generate_monthly_trend_chart(trend),
                    "Monthly Spending Trend",
                ))
            charts.append((
                chart_generator.generate_month_progress_chart(
                    disc_budget=report_data.get("disc_budget", 0),
                    disc_spent=report_data.get("txn_discretionary", 0),
                    saved=report_data.get("saved", 0),
                    target=report_data.get("savings_target", 2000),
                    weekly_breakdown=report_data.get("weekly_breakdown"),
                ),
                "Month at a Glance",
            ))
        except Exception as e:
            print(f"Chart generation failed: {e}")

        # Save report
        from datetime import date as _date
        database.save_weekly_report(
            conn,
            report_date=_date.today().isoformat(),
            subject=claude_report.get("subject", "Weekly Budget Report"),
            html_body=claude_report.get("html_body", ""),
            plain_text=claude_report.get("plain_text", ""),
        )

        # Send Claude-written report (rich, merchant-specific content)
        summary_text = claude_report.get("plain_text", "") or format_weekly_report_html(report_data)
        for user_name, user_info in config.TELEGRAM_USERS.items():
            cid = database.get_setting(conn, user_info["setting_key"])
            if cid:
                try:
                    reporter = TelegramReporter(token, cid)
                    reporter.send_weekly_report(summary_text, charts)
                except Exception as e:
                    print(f"Failed to send report to {user_name}: {e}")

        print("Weekly report sent to all users.")

    except Exception as e:
        print(f"Error generating weekly report: {e}")
        _send_to_all(token, conn, f"Report generation failed: {str(e)[:200]}")


def _send_to_all(token, conn, text):
    """Send a message to all configured chat IDs."""
    for user_info in config.TELEGRAM_USERS.values():
        cid = database.get_setting(conn, user_info["setting_key"])
        if cid:
            send_message(token, cid, text)


def process_file(file_bytes, filename, chat_id, token):
    """Process an uploaded PDF or CSV file."""
    database.init_db(DB_PATH)
    conn = database.get_connection(DB_PATH)

    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # Check duplicate
    if database.check_duplicate_statement(conn, file_hash):
        send_message(token, chat_id, f"Already imported: <b>{filename}</b>")
        conn.close()
        return

    is_csv = filename.lower().endswith(".csv")
    is_pdf = filename.lower().endswith(".pdf")

    if not (is_csv or is_pdf):
        send_message(token, chat_id, "Please send a PDF or CSV file from Chase.")
        conn.close()
        return

    try:
        if is_csv:
            # CSV path
            detected_account = csv_parser.identify_account_from_csv(file_bytes, filename)
            result = csv_parser.parse_chase_csv(file_bytes, account_hint=detected_account)
            account_id = result.get("account_id", detected_account or "unknown")

        elif is_pdf:
            # Check if spending report
            raw_text = pdf_parser.extract_text_from_bytes(file_bytes)

            if chase_report_parser.is_spending_report(raw_text):
                # Spending report — instant parse
                result = chase_report_parser.parse_spending_report(file_bytes, filename, raw_text=raw_text)
                account_id = result.get("account_id") or pdf_parser.identify_account_from_text(raw_text) or "unknown"
            else:
                # Regular statement — use Claude
                api_key = database.get_setting(conn, "anthropic_api_key")
                if not api_key:
                    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    send_message(token, chat_id, "No API key configured. Set it in the app Settings.")
                    conn.close()
                    return

                from claude_advisor import ClaudeAdvisor
                advisor = ClaudeAdvisor(api_key=api_key)

                tables = pdf_parser.extract_tables_from_bytes(file_bytes)
                account_hint = pdf_parser.identify_account_from_text(raw_text)
                is_checking = account_hint == "joint_checking"

                existing_stmts = database.get_all_statements(conn)
                existing_periods = [
                    {"account_id": s["account_id"], "period_start": s["period_start"], "period_end": s["period_end"]}
                    for s in existing_stmts
                ]

                send_message(token, chat_id, f"Parsing <b>{filename}</b> with Claude...")

                result = advisor.extract_transactions(
                    raw_text=raw_text, tables=tables,
                    account_hint=account_hint, existing_periods=existing_periods,
                    is_checking=is_checking,
                )
                account_id = result.get("account_id", account_hint or "unknown")

        # Get transactions
        transactions = result.get("transactions", [])
        if not transactions:
            send_message(token, chat_id, f"No transactions found in <b>{filename}</b>.")
            conn.close()
            return

        # Normalize dates
        period_start = result.get("period_start", "")
        period_end = result.get("period_end", "")

        import re
        def normalize_date(d, year_hint=""):
            if not d or d == "unknown":
                return d
            d = d.strip()
            if len(d) == 10 and d[4] == "-" and d[7] == "-":
                return d
            m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", d)
            if m:
                return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
            m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2})", d)
            if m:
                yr = int(m.group(3))
                year = 2000 + yr if yr < 50 else 1900 + yr
                return f"{year}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
            m = re.match(r"(\d{1,2})/(\d{1,2})$", d)
            if m:
                yr = year_hint or str(datetime.now().year)
                return f"{yr}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
            return d

        year_hint = (period_start or "")[:4] if period_start and period_start != "unknown" else ""
        for txn in transactions:
            if "date" in txn:
                txn["date"] = normalize_date(txn["date"], year_hint)
        period_start = normalize_date(period_start or "unknown", year_hint)
        period_end = normalize_date(period_end or "unknown", year_hint)

        # Import
        stmt_id = database.insert_statement(
            conn, filename, account_id,
            period_start, period_end, file_hash,
            notes="Imported via Telegram",
        )
        for txn in transactions:
            txn["account_id"] = account_id
            txn["statement_id"] = stmt_id

        inserted = database.bulk_insert_transactions(conn, transactions)
        database.update_statement_txn_count(conn, stmt_id, inserted)

        # Auto-fix period if unknown
        if not period_start or period_start == "unknown":
            row = conn.execute(
                "SELECT MIN(date) as d1, MAX(date) as d2 FROM transactions WHERE statement_id = ?",
                (stmt_id,),
            ).fetchone()
            if row and row["d1"] and row["d1"] != "unknown":
                conn.execute("UPDATE statements SET period_start = ?, period_end = ? WHERE id = ?",
                            (row["d1"], row["d2"], stmt_id))
                conn.commit()
                period_start, period_end = row["d1"], row["d2"]

        # Build summary
        acct_label = config.ACCOUNTS.get(account_id, {}).get("label", account_id)
        owner = config.ACCOUNTS.get(account_id, {}).get("owner", "")

        cat_totals = {}
        for t in transactions:
            if t.get("amount", 0) < 0:
                cat = t.get("category", "Other")
                cat_totals[cat] = cat_totals.get(cat, 0) + abs(t["amount"])

        top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:5]
        cat_lines = "\n".join(f"  {c}: ${v:,.0f}" for c, v in top_cats)

        total_charges = sum(abs(t["amount"]) for t in transactions if t.get("amount", 0) < 0)

        msg = (
            f"<b>Imported {inserted} transactions</b>\n"
            f"Account: {acct_label} ({owner})\n"
            f"Period: {period_start} to {period_end}\n"
            f"Total charges: ${total_charges:,.0f}\n\n"
            f"<b>Top categories:</b>\n{cat_lines}"
        )
        send_message(token, chat_id, msg)

        # Track this upload in the weekly cycle
        if account_id in database.WEEKLY_ACCOUNTS:
            _track_upload(conn, account_id, chat_id, token)

    except Exception as e:
        send_message(token, chat_id, f"Error processing {filename}: {str(e)[:200]}")

    conn.close()


def _send_typing_action(token: str, chat_id: str):
    """Show 'typing...' indicator in Telegram chat."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass


def _handle_claude_qa(token: str, chat_id: str, user_message: str, from_name: str):
    """Handle a free-text question by forwarding it to Claude with financial context."""
    try:
        # Show typing indicator immediately
        _send_typing_action(token, chat_id)

        conn = database.get_connection(DB_PATH)

        # Load API key (try DB first, then environment)
        api_key = database.get_setting(conn, "anthropic_api_key")
        if not api_key:
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            send_message(token, chat_id, "Claude API key not set. Configure it in the app Settings.")
            conn.close()
            return

        from claude_advisor import ClaudeAdvisor

        advisor = ClaudeAdvisor(api_key=api_key)

        # Build context
        financial_context = database.get_financial_context(conn)
        tactical_context = None
        try:
            import spending_intelligence
            tactical_context = spending_intelligence.build_tactical_context(conn)
        except Exception:
            pass

        # Load conversation history for this Telegram chat
        session_id = f"tg_{chat_id}"
        history = database.get_conversation(conn, session_id, limit=10)

        # Refresh typing indicator (Claude call takes a few seconds)
        _send_typing_action(token, chat_id)

        # Get Claude's response
        result = advisor.get_advisor_response(
            user_message=user_message,
            conversation_history=history,
            financial_context=financial_context,
            tactical_context=tactical_context,
        )

        response_text = result.get("response", str(result))

        # Save conversation
        database.save_conversation(conn, session_id, "user", user_message)
        database.save_conversation(conn, session_id, "assistant", response_text)

        # Convert markdown to Telegram HTML
        import re
        html_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', response_text)
        html_text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', html_text)
        # Convert markdown bullet points
        html_text = re.sub(r'^- ', '\u2022 ', html_text, flags=re.MULTILINE)

        send_message(token, chat_id, html_text)
        conn.close()
        print(f"  Q&A: '{user_message[:50]}' \u2192 responded ({len(response_text)} chars)")

    except Exception as e:
        print(f"  Q&A error: {e}")
        send_message(token, chat_id, f"Sorry, I couldn't process that. Error: {str(e)[:200]}")


def _handle_status_command(token, chat_id):
    """Show current week's upload progress."""
    conn = database.get_connection(DB_PATH)
    week_start = database.get_current_week_start()
    database.init_weekly_cycle(conn, week_start)
    status = database.get_weekly_status(conn, week_start)

    lines = [f"<b>Week of {week_start} \u2014 Upload Status</b>\n"]
    for acct_id in database.WEEKLY_ACCOUNTS:
        info = status.get(acct_id, {"uploaded": False, "uploaded_ts": None})
        label = ACCOUNT_LABELS.get(acct_id, acct_id)
        if info["uploaded"]:
            ts = info["uploaded_ts"][:16] if info["uploaded_ts"] else ""
            lines.append(f"\u2705 {label}  ({ts})")
        else:
            lines.append(f"\u23f3 {label}  \u2014 not yet uploaded")

    done = sum(1 for i in status.values() if i.get("uploaded"))
    total = len(database.WEEKLY_ACCOUNTS)
    lines.append(f"\n{done}/{total} complete")

    if done == total:
        lines.append("\nAll done! Report was already sent.")

    send_message(token, chat_id, "\n".join(lines))
    conn.close()


def _handle_report_command(token, chat_id):
    """Force-generate and send the weekly report."""
    conn = database.get_connection(DB_PATH)
    send_message(token, chat_id, "Generating weekly report... this may take a minute.")
    _trigger_weekly_report(token, conn)
    conn.close()


def _handle_help_command(token, chat_id):
    """Send help text."""
    send_message(token, chat_id,
        "<b>Commands:</b>\n"
        "/status \u2014 Weekly upload progress\n"
        "/report \u2014 Force generate weekly report\n"
        "/reminder \u2014 Turn upload reminders on/off\n"
        "/help \u2014 This message\n\n"
        "<b>To upload:</b> Just send a PDF or CSV file from Chase.\n\n"
        "<b>Ask anything:</b> Type a question about your finances "
        "and I'll answer using your actual spending data."
    )


def _handle_reminder_command(token, chat_id):
    """Show reminder toggle with inline keyboard button."""
    conn = database.get_connection(DB_PATH)
    enabled = database.get_setting(conn, "weekly_reminder_enabled", "true") == "true"
    conn.close()

    status_text = "ON \u2705" if enabled else "OFF \U0001f515"
    button_text = "Turn OFF \U0001f515" if enabled else "Turn ON \u2705"

    keyboard = {
        "inline_keyboard": [[
            {"text": button_text, "callback_data": "reminder_toggle"}
        ]]
    }

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"<b>Weekly upload reminders: {status_text}</b>\n\n"
                        f"When ON, you'll get daily reminders until all statements are uploaded.",
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
            timeout=30,
        )
    except Exception as e:
        print(f"Failed to send reminder command: {e}")


def _handle_reminder_callback(token, callback_query):
    """Toggle reminder setting and update the inline button."""
    chat_id = str(callback_query["message"]["chat"]["id"])
    message_id = callback_query["message"]["message_id"]
    callback_id = callback_query["id"]

    conn = database.get_connection(DB_PATH)
    current = database.get_setting(conn, "weekly_reminder_enabled", "true")
    new_value = "false" if current == "true" else "true"
    database.set_setting(conn, "weekly_reminder_enabled", new_value)
    conn.close()

    enabled = new_value == "true"
    status_text = "ON \u2705" if enabled else "OFF \U0001f515"
    button_text = "Turn OFF \U0001f515" if enabled else "Turn ON \u2705"

    keyboard = {
        "inline_keyboard": [[
            {"text": button_text, "callback_data": "reminder_toggle"}
        ]]
    }

    # Update the message in-place
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"<b>Weekly upload reminders: {status_text}</b>\n\n"
                        f"When ON, you'll get daily reminders until all statements are uploaded.",
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
            timeout=30,
        )
    except Exception as e:
        print(f"Failed to update reminder message: {e}")

    # Dismiss the loading spinner
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={
                "callback_query_id": callback_id,
                "text": f"Reminders {'enabled' if enabled else 'disabled'}",
            },
            timeout=10,
        )
    except Exception:
        pass


def _try_autodetect_maggie(token, chat_id, from_name, message_text):
    """If an unknown chat sends /start, auto-save as secondary user's chat ID."""
    conn = database.get_connection(DB_PATH)
    maggie_id = database.get_setting(conn, "telegram_chat_id_maggie")
    if not maggie_id:
        # Save this as secondary user's chat ID
        database.set_setting(conn, "telegram_chat_id_maggie", str(chat_id))
        send_message(token, chat_id,
            f"<b>Welcome {from_name}!</b> \U0001f389\n\n"
            f"I've registered your chat. You'll receive:\n"
            f"\u2022 Weekly upload reminders\n"
            f"\u2022 Weekly spending reports\n\n"
            f"Send me your statement CSV anytime!"
        )
        print(f"Auto-detected secondary user's chat ID: {chat_id}")
        conn.close()
        return True
    conn.close()
    return False


def poll_updates(token, allowed_chat_id):
    """Long-poll for new messages from Telegram."""
    offset = 0
    allowed_ids = get_allowed_chat_ids()
    if allowed_chat_id:
        allowed_ids.add(str(allowed_chat_id))
    print(f"Vaultwise AI bot listening... (allowed chats: {allowed_ids})", flush=True)

    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            data = resp.json()

            if not data.get("ok"):
                print(f"Error: {data}")
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                # Handle inline keyboard callbacks (e.g. reminder toggle)
                callback_query = update.get("callback_query")
                if callback_query:
                    cb_chat_id = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))
                    if cb_chat_id in allowed_ids:
                        cb_data = callback_query.get("data", "")
                        if cb_data == "reminder_toggle":
                            _handle_reminder_callback(token, callback_query)
                    continue

                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                from_name = message.get("from", {}).get("first_name", "")

                # Check if this is an allowed chat or a new /start
                if chat_id not in allowed_ids:
                    text = (message.get("text") or "").strip().lower()
                    if text == "/start":
                        if _try_autodetect_maggie(token, chat_id, from_name, text):
                            allowed_ids.add(chat_id)
                            continue
                    # Unknown chat — skip silently
                    print(f"Ignoring message from unknown chat: {chat_id}")
                    continue

                # Handle document (PDF/CSV)
                doc = message.get("document")
                if doc:
                    filename = doc.get("file_name", "file")
                    file_size = doc.get("file_size", 0)
                    print(f"[{datetime.now():%H:%M}] File from {from_name}: {filename} ({file_size:,} bytes)")

                    if not (filename.lower().endswith(".pdf") or filename.lower().endswith(".csv")):
                        send_message(token, chat_id, "Please send a <b>PDF</b> or <b>CSV</b> statement from Chase.")
                        continue

                    if file_size > 50 * 1024 * 1024:
                        send_message(token, chat_id, "File too large (max 50MB).")
                        continue

                    send_message(token, chat_id, f"Received <b>{filename}</b>. Processing...")

                    file_bytes, _ = download_file(token, doc["file_id"])
                    if file_bytes:
                        process_file(file_bytes, filename, chat_id, token)
                    else:
                        send_message(token, chat_id, "Failed to download file. Try again.")

                # Handle text messages
                elif message.get("text"):
                    text = message["text"].strip()
                    text_lower = text.lower()

                    if text_lower in ("/start", "hi", "hello", "hey"):
                        send_message(token, chat_id,
                            f"<b>Hey {from_name}!</b>\n\n"
                            f"I'm Vaultwise AI, your family budget bot.\n\n"
                            f"<b>Send me a PDF or CSV</b> from Chase and I'll:\n"
                            f"- Auto-detect the account from the statement\n"
                            f"- Parse all transactions instantly\n"
                            f"- Import them to your budget tracker\n"
                            f"- Send you a category summary\n\n"
                            f"Just share the file from your Chase app!"
                        )
                    elif text_lower == "/status":
                        _handle_status_command(token, chat_id)

                    elif text_lower == "/report":
                        _handle_report_command(token, chat_id)

                    elif text_lower == "/reminder":
                        _handle_reminder_command(token, chat_id)

                    elif text_lower == "/help":
                        _handle_help_command(token, chat_id)

                    else:
                        # Claude Q&A — forward question to financial advisor
                        _handle_claude_qa(token, chat_id, text, from_name)

        except requests.exceptions.Timeout:
            continue
        except requests.exceptions.ConnectionError:
            print("Connection lost, retrying in 5s...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nBot stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    # Ensure output is flushed immediately (needed for launchd log capture)
    import functools
    print = functools.partial(print, flush=True)

    token, chat_id = get_settings()
    if not token:
        print("No Telegram bot token configured. Set it in the app Settings.")
        sys.exit(1)
    poll_updates(token, chat_id)
