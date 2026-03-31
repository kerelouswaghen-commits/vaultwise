#!/usr/bin/env python3
"""
Weekly upload reminder — runs daily via launchd.
Checks which accounts still need CSV uploads for the current week and
sends targeted Telegram reminders to Kero and/or Maggie.

If all accounts are uploaded the script exits silently (the report was
already triggered by telegram_listener.py on the final upload).

Usage:
    python weekly_reminder.py          # Normal run (daily via launchd)
    python weekly_reminder.py --test   # Force-send reminders regardless of status
"""

import os
import sys
import argparse
import functools

# Ensure flushed output for launchd
print = functools.partial(print, flush=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import database
import config

DB_PATH = os.path.join(os.path.dirname(__file__), "data", config.DB_FILENAME)

# Friendly display names for each account (from config)
ACCOUNT_LABELS = {acct_id: info.get("label", acct_id) for acct_id, info in config.ACCOUNTS.items()}

# Step-by-step CSV download instructions per account
ACCOUNT_INSTRUCTIONS = {
    acct_id: f"Banking app \u2192 {info.get('label', acct_id)} \u2192 \u2b07 Download activity \u2192 CSV \u2192 Share here"
    for acct_id, info in config.ACCOUNTS.items()
}


def send_message(token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Send a Telegram message.  Returns True on success."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4096], "parse_mode": parse_mode},
            timeout=30,
        )
        return resp.json().get("ok", False)
    except Exception as e:
        print(f"Failed to send message to {chat_id}: {e}")
        return False


def _other_users_status(user_name: str, status: dict) -> str:
    """Build a line showing the other user's upload status."""
    lines = []
    for name, info in config.TELEGRAM_USERS.items():
        if name == user_name:
            continue
        user_accounts = info["accounts"]
        all_done = all(
            status.get(acct, {}).get("uploaded", False) for acct in user_accounts
        )
        display = name.capitalize()
        if all_done:
            lines.append(f"{display} has already uploaded \u2705")
        else:
            missing = [
                ACCOUNT_LABELS.get(a, a)
                for a in user_accounts
                if not status.get(a, {}).get("uploaded", False)
            ]
            lines.append(f"Waiting on {display}: {', '.join(missing)}")
    return "\n".join(lines)


def build_reminder(user_name: str, missing_accounts: list, status: dict) -> str:
    """Compose a friendly reminder message for one user."""
    bullet_lines = []
    for acct in missing_accounts:
        label = ACCOUNT_LABELS.get(acct, acct)
        instructions = ACCOUNT_INSTRUCTIONS.get(acct, "Download CSV and share here")
        bullet_lines.append(f"\u2022 {label} \u2014 {instructions}")

    others = _other_users_status(user_name, status)

    msg = (
        "\U0001f4ca Weekly upload time!\n\n"
        "Still need from you:\n"
        + "\n".join(bullet_lines)
        + "\n\n"
        + others
        + "\nOnce everyone uploads, I'll generate the weekly report!"
    )
    return msg


def run(force: bool = False):
    """Main logic: check status and send reminders as needed."""
    database.init_db(DB_PATH)
    conn = database.get_connection(DB_PATH)

    # Check if reminders are enabled (can be toggled via /reminder on Telegram)
    if not force and database.get_setting(conn, "weekly_reminder_enabled", "true") != "true":
        print("Reminders disabled (weekly_reminder_enabled=false). Skipping.")
        conn.close()
        return

    week_start = database.get_current_week_start()
    database.init_weekly_cycle(conn, week_start)
    print(f"Week start: {week_start}")

    # If the week is already complete, nothing to do
    if not force and database.is_week_complete(conn, week_start):
        print("All accounts already uploaded. Skipping reminders.")
        conn.close()
        return

    status = database.get_weekly_status(conn, week_start)
    token = database.get_setting(conn, "telegram_bot_token")
    if not token:
        print("No Telegram bot token configured. Exiting.")
        conn.close()
        return

    for user_name, user_info in config.TELEGRAM_USERS.items():
        chat_id = database.get_setting(conn, user_info["setting_key"])
        if not chat_id:
            print(f"No chat ID for {user_name}, skipping.")
            continue

        missing = [
            acct
            for acct in user_info["accounts"]
            if not status.get(acct, {}).get("uploaded", False)
        ]

        if not missing and not force:
            print(f"{user_name}: all accounts uploaded.")
            continue

        if force and not missing:
            # In test mode, pretend everything is missing
            missing = user_info["accounts"]

        msg = build_reminder(user_name, missing, status)
        ok = send_message(token, chat_id, msg)
        print(f"Sent reminder to {user_name} ({chat_id}): {'OK' if ok else 'FAILED'}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weekly upload reminder")
    parser.add_argument("--test", action="store_true", help="Force-send reminders regardless of status")
    args = parser.parse_args()
    run(force=args.test)
