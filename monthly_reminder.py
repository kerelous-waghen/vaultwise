#!/usr/bin/env python3
"""
Monthly statement reminder — nags household members until they upload.
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

# Build PEOPLE dict dynamically from config.TELEGRAM_USERS and config.ACCOUNTS
PEOPLE = {}
for _user_key, _user_info in config.TELEGRAM_USERS.items():
    _primary_acct = _user_info["accounts"][0] if _user_info.get("accounts") else None
    if _primary_acct:
        _acct_info = config.ACCOUNTS.get(_primary_acct, {})
        PEOPLE[_user_key] = {
            "name": _user_key.title(),
            "account_id": _primary_acct,
            "card_label": _acct_info.get("label", _primary_acct),
            "setting_key": _user_info["setting_key"],
        }

# Day of month to start reminding
REMINDER_START_DAY = 3

# ── Reminder messages (rotate through these) ──────────────────────────────

# Generic reminder templates — {name} and {card} are filled from PEOPLE dict
REMINDERS = [
    # Day 3-5: Gentle
    (
        "Hey {name}! Your {card} statement for {month} should be ready. "
        "Open the banking app → Statements → Download PDF → Share to me here. "
        "Takes 30 seconds. {motivation_msg}"
    ),
    # Day 6-8: Nudge
    (
        "{name}, still waiting on your {month} {card} statement. "
        "Can't track your spending without it! "
        "Quick reminder: Banking app → Statements → Share PDF here. {motivation_msg}"
    ),
    # Day 9-12: Firm
    (
        "{name}! It's been {days} days since {month} ended and I still don't have your {card} data. "
        "Your spending dashboard is getting stale. "
        "Please upload today — accurate tracking is key to hitting your savings target. {motivation_msg}"
    ),
    # Day 13+: Escalation
    (
        "{name}, {days} days without your {month} statement. "
        "I can't give you accurate savings advice without current data. "
        "This is a 30-second task: Banking app → Statements → Share PDF to me. Please do it now."
    ),
]

BOTH_DONE_MSG = "All caught up, {name}! All {month} statements are in. Check the dashboard for the latest spending breakdown."

CHECKING_REMINDER = (
    "{name}, don't forget the joint checking statement for {month} too! "
    "Same process: Banking app → Statements → Checking → Share PDF here."
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

    motivation_msg = get_motivation_message()
    level = get_reminder_level(day)

    # Check each person dynamically from PEOPLE dict
    upload_status = {}
    for user_key, person in PEOPLE.items():
        done = check_month_uploaded(conn, person["account_id"], check_year, check_month)
        upload_status[user_key] = done
        print(f"Checking {month_label}: {person['name']}={'done' if done else 'MISSING'}")

    checking_done = check_month_uploaded(conn, "joint_checking", check_year, check_month)
    print(f"Checking {month_label}: Joint Checking={'done' if checking_done else 'MISSING'}")

    all_done = all(upload_status.values()) and checking_done

    # Send reminders to each person
    for user_key, person in PEOPLE.items():
        chat_id = database.get_setting(conn, person["setting_key"])
        if not chat_id:
            continue

        if not upload_status[user_key]:
            msg = REMINDERS[level].format(
                name=person["name"], card=person["card_label"],
                month=month_label, days=days_since, motivation_msg=motivation_msg,
            )
            bot_user = TelegramReporter(bot_token, chat_id)
            bot_user.send_message(msg)
            print(f"  → Sent reminder to {person['name']} (level {level})")

            # First user also gets checking reminder if missing
            if not checking_done and user_key == list(PEOPLE.keys())[0]:
                bot_user.send_message(CHECKING_REMINDER.format(name=person["name"], month=month_label))
                print(f"  → Also reminded {person['name']} about checking statement")

    if all_done:
        print("  All statements uploaded for this month!")

    conn.close()


def send_test():
    """Send a test reminder to all configured users."""
    database.init_db(DB_PATH)
    conn = database.get_connection(DB_PATH)
    bot_token = database.get_setting(conn, "telegram_bot_token")

    if not bot_token:
        print("No bot token configured.")
        conn.close()
        return

    motivation_msg = get_motivation_message()

    for user_key, person in PEOPLE.items():
        chat_id = database.get_setting(conn, person["setting_key"])
        if chat_id:
            bot = TelegramReporter(bot_token, chat_id)
            bot.send_message(
                f"Hey {person['name']}! This is a test reminder from VaultWise.\n\n"
                f"Every month I'll remind you to upload your {person['card_label']} statement. "
                f"Just share the PDF from the banking app to this chat.\n\n"
                f"{motivation_msg}"
            )
            print(f"✅ Test sent to {person['name']} ({chat_id})")
        else:
            print(f"⚠️  No chat ID for {person['name']} yet.")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monthly statement reminder")
    parser.add_argument("--test", action="store_true", help="Send test reminder")
    args = parser.parse_args()

    if args.test:
        send_test()
    else:
        send_reminders()
