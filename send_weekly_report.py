#!/usr/bin/env python3
"""
CLI entry point for sending the weekly financial report.
Can be triggered by: GitHub Actions, cron, launchd, or manual run.

Usage:
    python send_weekly_report.py
    python send_weekly_report.py --telegram-only
    python send_weekly_report.py --dry-run

Environment variables required:
    TELEGRAM_BOT_TOKEN   — Telegram bot token from @BotFather
    TELEGRAM_CHAT_ID     — Your Telegram chat ID

Optional:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, REPORT_RECIPIENTS — for email
"""

import argparse
import os
import re
import sys
from datetime import date

# Add project directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
import config
import reports
import chart_generator
from telegram_bot import TelegramReporter, format_weekly_report_html


def main():
    parser = argparse.ArgumentParser(description="Send weekly financial report")
    parser.add_argument("--telegram-only", action="store_true", help="Send only via Telegram")
    parser.add_argument("--email-only", action="store_true", help="Send only via email")
    parser.add_argument("--dry-run", action="store_true", help="Generate report but don't send")
    args = parser.parse_args()

    db_path = os.path.join(os.path.dirname(__file__), "data", config.DB_FILENAME)

    # Check database exists (skip check if using Turso cloud DB)
    if not database._USE_TURSO and not os.path.exists(db_path):
        print("❌ No database found. Upload some statements first via the Streamlit app.")
        sys.exit(1)

    # Initialize
    if not database._USE_TURSO:
        database.init_db(db_path)
    conn = database.get_connection(db_path)

    txn_count = database.get_transaction_count(conn)
    print(f"📊 Database: {txn_count} transactions")

    if txn_count == 0:
        print("⚠️  No transactions in database. Upload statements first.")
        conn.close()
        sys.exit(0)

    # Build report data (includes dashboard-grade metrics: income, savings, trends)
    print("📝 Gathering report data...")
    report_data = reports.gather_report_data(conn)

    # Format the report (data-driven, no Claude needed)
    summary_text = format_weekly_report_html(report_data)

    # Generate charts (focused: weekly spending, monthly trend, month progress)
    print("📊 Generating charts...")
    charts = []
    try:
        # Weekly spending (flex only — excludes transfers AND fixed bills)
        _chart_excl = config.EXCLUDED_CATEGORIES | report_data.get("fixed_categories", set())
        this_week = database.get_weekly_spending(conn, exclude_categories=_chart_excl)
        if this_week.get("categories"):
            charts.append((
                chart_generator.generate_weekly_spending_chart(this_week),
                "This Week's Spending by Category"
            ))

        # Monthly trend
        trend = database.get_spending_trend(conn, months=6)
        if trend:
            charts.append((
                chart_generator.generate_monthly_trend_chart(trend),
                "Monthly Spending Trend"
            ))

        # Month progress bar (budget consumption + savings status)
        charts.append((
            chart_generator.generate_month_progress_chart(
                disc_budget=report_data.get("disc_budget", 0),
                disc_spent=report_data.get("txn_discretionary", 0),
                saved=report_data.get("saved", 0),
                target=report_data.get("savings_target", 2000),
                weekly_breakdown=report_data.get("weekly_breakdown"),
            ),
            "Month at a Glance"
        ))

        print(f"   Generated {len(charts)} charts")
    except Exception as e:
        print(f"⚠️  Chart generation failed: {e}")

    # Save report to DB
    plain_text = re.sub(r'<[^>]+>', '', summary_text)
    db_report_id = database.save_weekly_report(
        conn,
        report_date=date.today().isoformat(),
        subject=f"VaultWise Report — {date.today().strftime('%B %Y')}",
        html_body=summary_text,
        plain_text=plain_text,
    )
    print(f"💾 Report saved to database (ID: {db_report_id})")

    if args.dry_run:
        print("\n🏁 Dry run complete. Report generated but not sent.")
        print(f"\nReport preview:\n{plain_text}")
        conn.close()
        return

    sent_any = False

    # Send via Telegram
    if not args.email_only:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or database.get_setting(conn, "telegram_bot_token")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID") or database.get_setting(conn, "telegram_chat_id")

        if bot_token and chat_id:
            print("📱 Sending via Telegram...")
            try:
                telegram = TelegramReporter(bot_token, chat_id)
                success = telegram.send_weekly_report(summary_text, charts)
                if success:
                    print("✅ Telegram report sent!")
                    sent_any = True
                else:
                    print("⚠️  Telegram send had issues (partial delivery)")
            except Exception as e:
                print(f"❌ Telegram failed: {e}")
        else:
            print("⏭️  Telegram not configured (no bot token or chat ID)")

    # Send via email
    if not args.telegram_only:
        if os.environ.get("SMTP_HOST"):
            print("📧 Sending via email...")
            try:
                email_report = {
                    "subject": f"VaultWise Report — {date.today().strftime('%B %Y')}",
                    "html_body": summary_text,
                    "plain_text": plain_text,
                }
                success = reports.send_email_report(email_report)
                if success:
                    print("✅ Email sent!")
                    sent_any = True
                else:
                    print("⚠️  Email send failed")
            except Exception as e:
                print(f"❌ Email failed: {e}")
        else:
            print("⏭️  Email not configured (no SMTP_HOST)")

    conn.close()

    if sent_any:
        print("\n🎉 Weekly report delivered!")
    else:
        print("\n⚠️  Report generated but no delivery channel configured.")
        print("   Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, or SMTP settings.")


if __name__ == "__main__":
    main()
