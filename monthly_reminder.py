#!/usr/bin/env python3
"""
Monthly statement reminder — nags Kero and Maggie until they upload.
Run this daily (via cron/launchd). It checks if this month's data exists
and sends personalized reminders if not.

Usage:
    python monthly_reminder.py          # Check and send reminders
    python monthly_reminder.py --test   # Send test reminder to both
"""

import os
import sys
import argparse
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
import config
from telegram_bot import TelegramReporter

DB_PATH = os.path.join(os.path.dirname(__file__), "data", config.DB_FILENAME)

# ── Reminder configuration ────────────────────────────────────────────────

PEOPLE = {
    "kero": {
        "name": "Kero",
        "account_id": "chase_4730",
        "card_label": "Chase 4730",
        "setting_key": "telegram_chat_id",  # Main chat ID
    },
    "maggie": {
        "name": "Maggie",
        "account_id": "chase_3072",
        "card_label": "Chase 3072",
        "setting_key": "telegram_chat_id_maggie",
    },
}

# Day of month to start reminding
REMINDER_START_DAY = 3

# ── Reminder messages (rotate through these) ──────────────────────────────

KERO_REMINDERS = [
    # Day 3-5: Gentle
    (
        "Hey Kero! Your Chase 4730 statement for {month} should be ready. "
        "Open the Chase app → Statements → Download PDF → Share to me here. "
        "Takes 30 seconds. {motivation_msg}"
    ),
    # Day 6-8: Nudge
    (
        "Kero, still waiting on your {month} Chase 4730 statement. "
        "Can't track your spending without it! "
        "Quick reminder: Chase app → Statements → Share PDF here. {motivation_msg}"
    ),
    # Day 9-12: Firm
    (
        "Kero! It's been {days} days since {month} ended and I still don't have your Chase 4730 data. "
        "Your spending dashboard is getting stale. "
        "Please upload today — accurate tracking is key to hitting your savings target. {motivation_msg}"
    ),
    # Day 13+: Escalation
    (
        "Kero, {days} days without your {month} statement. "
        "I can't give you accurate savings advice without current data. "
        "This is a 30-second task: Chase app → Statements → Share PDF to me. Please do it now."
    ),
]

MAGGIE_REMINDERS = [
    # Day 3-5: Gentle
    (
        "Hey Maggie! Your Chase 3072 statement for {month} should be ready. "
        "Open the Chase app → Statements → Download PDF → Share to me here. "
        "Super quick!"
    ),
    # Day 6-8: Nudge
    (
        "Maggie, I'm still waiting on your {month} Chase 3072 statement. "
        "Kero already uploaded his — just need yours to complete the picture! "
        "Chase app → Statements → Share PDF here."
    ),
    # Day 9-12: Firm
    (
        "Maggie, it's been {days} days and I still don't have your {month} statement. "
        "Without your card data, the budget tracker is missing half the spending. "
        "Please upload today when you get a chance."
    ),
    # Day 13+: Escalation
    (
        "Maggie, {days} days without your {month} data. "
        "The savings tracker can't work without both cards. "
        "30 seconds: Chase app → Statements → Share to Vaultwise bot. Please!"
    ),
]

BOTH_DONE_MSG = {
    "kero": "All caught up, Kero! Both your and Maggie's {month} statements are in. Check the dashboard for the latest spending breakdown.",
    "maggie": "All caught up, Maggie! Both statements are in for {month}. The budget tracker is fully updated.",
}

CHECKING_REMINDER = (
    "Kero, don't forget the joint checking statement for {month} too! "
    "Same process: Chase app → Statements → Checking → Share PDF here."
)


def get_motivation_message() -> str:
    """Motivational message for statement reminders."""
    return "(Consistent tracking is the key to hitting your savings target!)"


def check_month_uploaded(conn, account_id: str, year: int, month: int) -> bool:
    """Check if we have transaction data for a specific month and account."""
    month_str = f"{year}-{month:02d}"
    row = conn.execute("""
        SELECT COUNT(*) as c FROM transactions
        WHERE account_id = ? AND strftime('%Y-%m', date) = ?
    """, (account_id, month_str)).fetchone()
    return row["c"] > 0


def get_reminder_level(day_of_month: int) -> int:
    """Which reminder message to use based on how late we are."""
    if day_of_month <= 5:
        return 0
    elif day_of_month <= 8:
        return 1
    elif day_of_month <= 12:
        return 2
    else:
        return 3


def should_remind_today(day_of_month: int) -> bool:
    """Don't spam every day — remind on specific days."""
    if day_of_month < REMINDER_START_DAY:
        return False
    if day_of_month <= 5:
        return day_of_month == REMINDER_START_DAY  # Once on day 3
    elif day_of_month <= 8:
        return day_of_month == 7  # Once on day 7
    elif day_of_month <= 12:
        return day_of_month == 10  # Once on day 10
    elif day_of_month <= 20:
        return day_of_month == 15  # Once on day 15
    else:
        return day_of_month == 20  # Last nag on day 20


def send_reminders():
    """Check what's missing and send appropriate reminders."""
    today = date.today()
    day = today.day

    if not should_remind_today(day):
        print(f"Day {day}: not a reminder day, skipping.")
        return

    # Check PREVIOUS month (statements come out after month ends)
    if today.month == 1:
        check_year, check_month = today.year - 1, 12
    else:
        check_year, check_month = today.year, today.month - 1

    from calendar import month_name
    month_label = f"{month_name[check_month]} {check_year}"
    days_since = day  # Days into new month = days since prev month ended

    database.init_db(DB_PATH)
    conn = database.get_connection(DB_PATH)

    # Get Telegram settings
    bot_token = database.get_setting(conn, "telegram_bot_token")
    kero_chat = database.get_setting(conn, "telegram_chat_id")
    maggie_chat = database.get_setting(conn, "telegram_chat_id_maggie")

    if not bot_token:
        print("No bot token configured.")
        conn.close()
        return

    bot = TelegramReporter(bot_token, kero_chat)  # Default to Kero
    motivation_msg = get_motivation_message()
    level = get_reminder_level(day)

    # Check each person
    kero_done = check_month_uploaded(conn, "chase_4730", check_year, check_month)
    maggie_done = check_month_uploaded(conn, "chase_3072", check_year, check_month)
    checking_done = check_month_uploaded(conn, "joint_checking", check_year, check_month)

    print(f"Checking {month_label}: Kero={'done' if kero_done else 'MISSING'}, "
          f"Maggie={'done' if maggie_done else 'MISSING'}, "
          f"Checking={'done' if checking_done else 'MISSING'}")

    # Send reminders
    if not kero_done and kero_chat:
        msg = KERO_REMINDERS[level].format(month=month_label, days=days_since, motivation_msg=motivation_msg)
        bot_kero = TelegramReporter(bot_token, kero_chat)
        bot_kero.send_message(msg)
        print(f"  → Sent reminder to Kero (level {level})")

        # Also remind about checking if missing
        if not checking_done:
            bot_kero.send_message(CHECKING_REMINDER.format(month=month_label))
            print(f"  → Also reminded Kero about checking statement")

    elif kero_done and kero_chat and maggie_done:
        # Both done — send congratulations (only once, on the day they complete)
        pass  # Don't spam congrats every reminder day

    if not maggie_done and maggie_chat:
        msg = MAGGIE_REMINDERS[level].format(month=month_label, days=days_since, motivation_msg=motivation_msg)
        bot_maggie = TelegramReporter(bot_token, maggie_chat)
        bot_maggie.send_message(msg)
        print(f"  → Sent reminder to Maggie (level {level})")

    if kero_done and maggie_done and checking_done:
        print("  All statements uploaded for this month!")

    conn.close()


def send_test():
    """Send a test reminder to both."""
    database.init_db(DB_PATH)
    conn = database.get_connection(DB_PATH)
    bot_token = database.get_setting(conn, "telegram_bot_token")
    kero_chat = database.get_setting(conn, "telegram_chat_id")
    maggie_chat = database.get_setting(conn, "telegram_chat_id_maggie")
    conn.close()

    if not bot_token:
        print("No bot token configured.")
        return

    motivation_msg = get_motivation_message()

    if kero_chat:
        bot = TelegramReporter(bot_token, kero_chat)
        bot.send_message(
            f"Hey Kero! This is a test reminder from Vaultwise AI.\n\n"
            f"Every month I'll remind you to upload your Chase 4730 statement. "
            f"Just share the PDF from the Chase app to this chat.\n\n"
            f"{motivation_msg}"
        )
        print(f"✅ Test sent to Kero ({kero_chat})")

    if maggie_chat:
        bot = TelegramReporter(bot_token, maggie_chat)
        bot.send_message(
            f"Hey Maggie! This is a test reminder from Vaultwise AI.\n\n"
            f"Every month I'll remind you to upload your Chase 3072 statement. "
            f"Just share the PDF from the Chase app to this chat.\n\n"
            f"{motivation_msg}"
        )
        print(f"✅ Test sent to Maggie ({maggie_chat})")
    else:
        print("⚠️  No chat ID for Maggie yet. She needs to message @Vaultwise_bot first.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monthly statement reminder")
    parser.add_argument("--test", action="store_true", help="Send test reminder")
    args = parser.parse_args()

    if args.test:
        send_test()
    else:
        send_reminders()
