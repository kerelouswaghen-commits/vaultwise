"""
Telegram Bot integration — sends rich weekly reports with charts.
Uses raw HTTP requests to Telegram Bot API (no framework needed for send-only).
"""

import json
from typing import Optional

import requests


class TelegramReporter:
    """Send messages and charts to a Telegram chat."""

    def __init__(self, bot_token: str, chat_id: str):
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot_token and chat_id are required")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def test_connection(self) -> dict:
        """Verify the bot token is valid and get bot info."""
        resp = requests.get(f"{self.base_url}/getMe", timeout=10)
        return resp.json()

    def send_message(self, text: str, parse_mode: str = "HTML") -> dict:
        """Send a text message. Supports HTML formatting."""
        # Telegram has a 4096 char limit per message
        if len(text) > 4096:
            # Split into multiple messages
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            result = None
            for chunk in chunks:
                result = self._send_text(chunk, parse_mode)
            return result
        return self._send_text(text, parse_mode)

    def _send_text(self, text: str, parse_mode: str = "HTML") -> dict:
        resp = requests.post(
            f"{self.base_url}/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        return resp.json()

    def send_photo(self, photo_bytes: bytes, caption: str = "") -> dict:
        """Send a single chart image."""
        resp = requests.post(
            f"{self.base_url}/sendPhoto",
            data={
                "chat_id": self.chat_id,
                "caption": caption[:1024],  # Telegram caption limit
                "parse_mode": "HTML",
            },
            files={"photo": ("chart.png", photo_bytes, "image/png")},
            timeout=30,
        )
        return resp.json()

    def send_media_group(self, photos: list[tuple[bytes, str]]) -> dict:
        """Send multiple charts as a grouped album."""
        if not photos:
            return {"ok": False, "description": "No photos to send"}

        # Telegram sendMediaGroup accepts up to 10 media items
        media = []
        files = {}
        for i, (photo_bytes, caption) in enumerate(photos[:10]):
            attach_name = f"photo{i}"
            media.append({
                "type": "photo",
                "media": f"attach://{attach_name}",
                "caption": caption[:1024] if i == 0 else "",  # Only first item gets caption
                "parse_mode": "HTML",
            })
            files[attach_name] = (f"chart_{i}.png", photo_bytes, "image/png")

        resp = requests.post(
            f"{self.base_url}/sendMediaGroup",
            data={
                "chat_id": self.chat_id,
                "media": json.dumps(media),
            },
            files=files,
            timeout=60,
        )
        return resp.json()

    def send_weekly_report(
        self,
        summary_text: str,
        charts: list[tuple[bytes, str]],
    ) -> bool:
        """Send a complete weekly report: text summary + chart album.
        Also saves the report as context for follow-up Q&A.

        Args:
            summary_text: HTML-formatted report text
            charts: List of (png_bytes, caption) tuples

        Returns:
            True if all messages sent successfully
        """
        success = True

        # 1. Send text summary
        result = self.send_message(summary_text)
        if not result.get("ok"):
            success = False

        # 2. Send charts as media group
        if charts:
            result = self.send_media_group(charts)
            if not result.get("ok"):
                # Fallback: send charts individually
                for photo_bytes, caption in charts:
                    result = self.send_photo(photo_bytes, caption)
                    if not result.get("ok"):
                        success = False

        # 3. Save report as conversation context so follow-up Q&A has context
        try:
            import database as _db
            import os as _os
            _db_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "expenses.db")
            _conn = _db.get_connection(_db_path)
            session_id = f"tg_{self.chat_id}"
            # Strip HTML tags for clean context
            import re
            plain = re.sub(r'<[^>]+>', '', summary_text)
            _db.save_conversation(_conn, session_id, "assistant",
                f"[Weekly Report sent]\n{plain[:2000]}")
            _conn.close()
        except Exception:
            pass

        # 4. Send a prompt for follow-up
        self.send_message(
            "<i>Reply to this message with any follow-up questions about your finances. "
            "I'll answer using your actual spending data.</i>"
        )

        return success


def format_weekly_report_html(report_data: dict, **_kwargs) -> str:
    """Savings-first, grandma-friendly Telegram report.

    Dynamic by week-of-month:
      - start (day 1-7):   Budget plan, last month's lessons
      - middle (day 8-21): Progress tracking, course corrections
      - end (day 22+):     Final scorecard, wins & lessons
    """
    d = report_data
    from datetime import date
    from calendar import month_name

    today = date.fromisoformat(d["report_date"])
    month_label = month_name[today.month].upper()
    year = today.year
    phase = d.get("month_phase", "middle")
    week_num = d.get("week_number", 1)
    weeks_in_month = d.get("weeks_in_month", 4)

    # Core numbers
    income = d.get("monthly_income", 0)
    fixed = d.get("effective_fixed", 0)
    disc_spent = d.get("txn_discretionary", 0)
    saved = d.get("saved", 0)
    target = d.get("savings_target", 2000)
    disc_budget = d.get("disc_budget", income - fixed - target)
    days_left = d.get("days_left", 0)
    days_in_month = d.get("days_in_month", 30)
    daily = d.get("daily_budget", 0)

    lines = []

    # ── HEADER ────────────────────────────────────────────────────
    lines.append(f"<b>{month_label} {year} — Week {week_num} of {weeks_in_month}</b>")
    lines.append("")

    # ── SCOREBOARD (always shown — the core mental model) ─────────
    lines.append(f"<b>SAVINGS GOAL: ${target:,}/mo</b>")
    lines.append("")
    lines.append(f"  Income:         ${income:,.0f}")
    lines.append(f"  Fixed bills:    ${fixed:,.0f}")
    lines.append(f"  Savings goal:   ${target:,.0f}")
    lines.append(f"                  ────────")
    lines.append(f"  Spending money: <b>${disc_budget:,.0f}</b>")
    lines.append("")

    # Progress bar (10 chars wide)
    if disc_budget > 0:
        pct_used = min(disc_spent / disc_budget, 2.0)
        filled = min(int(pct_used * 10), 10)
        bar = "█" * filled + "░" * (10 - filled)
        pct_label = f"{pct_used * 100:.0f}%"
    else:
        bar = "█" * 10
        pct_label = "OVER"

    if disc_spent <= disc_budget:
        remaining = disc_budget - disc_spent
        lines.append(f"  Flex spent: ${disc_spent:,.0f}  [{bar}] {pct_label}")
        lines.append(f"  Left:  <b>${remaining:,.0f}</b>")
        if daily > 0 and days_left > 0:
            lines.append(f"  = <b>${daily:,.0f}/day</b> for {days_left} days")
    else:
        over_by = disc_spent - disc_budget
        lines.append(f"  Flex spent: ${disc_spent:,.0f}  [{bar}] {pct_label}")
        lines.append(f"  <b>${over_by:,.0f} OVER BUDGET</b>")
        # Show realistic savings at current pace
        realistic_saved = income - fixed - disc_spent
        if realistic_saved > 0:
            lines.append(f"  At current pace: saving ${realistic_saved:,.0f}/mo")
        else:
            lines.append(f"  At current pace: ${abs(realistic_saved):,.0f}/mo in the red")
        if days_left > 0:
            lines.append(f"  Freeze spending for {days_left} day{'s' if days_left != 1 else ''}")
    lines.append("")

    # ── WEEK-BY-WEEK (middle + end phases) ────────────────────────
    weekly_breakdown = d.get("weekly_breakdown", [])
    if phase in ("middle", "end") and weekly_breakdown:
        lines.append("<b>WEEK BY WEEK</b>")
        cumulative = 0
        for wk in weekly_breakdown:
            wk_total = wk.get("total", 0)
            cumulative += wk_total
            wk_start = wk.get("start", "")
            wk_end = wk.get("end", "")
            # Format dates as "Mar 1-7"
            try:
                s = date.fromisoformat(wk_start)
                e = date.fromisoformat(wk_end)
                date_label = f"{month_name[s.month][:3]} {s.day}-{e.day}"
            except (ValueError, IndexError):
                date_label = f"Wk {wk['week_num']}"

            marker = "  ◀" if wk["week_num"] == week_num else ""
            lines.append(f"  Wk {wk['week_num']} ({date_label}): ${wk_total:,.0f}{marker}")

        lines.append(f"  ─────────────────────")
        lines.append(f"  Total: <b>${cumulative:,.0f}</b> of ${disc_budget:,.0f} budget")
        lines.append("")

    # ── PHASE-SPECIFIC CONTENT ────────────────────────────────────
    if phase == "start":
        _format_start_phase(lines, d, daily, days_in_month)
    elif phase == "middle":
        _format_middle_phase(lines, d)
    else:
        _format_end_phase(lines, d, saved, target)

    # ── ACTION ITEM (always — max 2 sentences) ───────────────────
    lines.append("<b>NEXT STEP</b>")
    if saved >= target:
        lines.append(f"On track! Keep daily spending under ${daily:,.0f}.")
    elif saved > 0:
        gap = target - saved
        lines.append(f"${gap:,.0f} short of target. Cut ${gap / max(days_left, 1):,.0f}/day to hit it.")
    else:
        lines.append(f"Over budget by ${abs(saved):,.0f}. Freeze all non-essential spending.")

    # Flag fees/interest
    for cat_data in d.get("mtd_breakdown", []):
        cat = cat_data.get("category", "")
        if "interest" in cat.lower() or "fees" in cat.lower():
            amt = abs(cat_data.get("total", 0))
            if amt > 10:
                lines.append(f"  → {cat}: ${amt:,.0f}/mo — eliminate this first")

    return "\n".join(lines)


def _format_start_phase(lines: list, d: dict, daily_budget: float, days_in_month: int):
    """Week 1: set the plan, learn from last month."""
    lines.append("<b>THE PLAN</b>")
    lines.append(f"  Daily spending target: <b>${daily_budget:,.0f}/day</b> ({days_in_month} days)")
    lines.append("")

    overbudget = d.get("last_month_overbudget", [])
    if overbudget:
        lines.append("<b>LAST MONTH'S LESSONS</b>")
        for item in overbudget[:3]:
            lines.append(f"  • {item['category']} was {item['status']}")
        lines.append("")


def _format_middle_phase(lines: list, d: dict):
    """Weeks 2-3: this week's activity, categories to watch."""
    week_spent = abs(d.get("week_spending_total", 0))
    week_count = d.get("week_txn_count", 0)

    if week_spent > 0:
        lines.append(f"<b>THIS WEEK: ${week_spent:,.0f}</b> ({week_count} txns)")
        week_merchants = d.get("week_merchants", [])
        if week_merchants:
            for m in week_merchants[:3]:
                name = m.get("description", "?")
                total = abs(m.get("total_spent", 0))
                if total > 0:
                    lines.append(f"  • {name}: ${total:,.0f}")
        lines.append("")

    # Categories over pace (flex only)
    budget_statuses = d.get("budget_statuses", {})
    fixed_cats = d.get("fixed_categories", set())
    flagged = []
    for cat, bs in budget_statuses.items():
        if cat in fixed_cats:
            continue
        status = bs.status if hasattr(bs, "status") else bs.get("status", "")
        if status in ("over", "elevated"):
            flagged.append(cat)
    if flagged:
        lines.append("<b>OVER PACE</b>")
        for cat in flagged[:3]:
            lines.append(f"  • {cat}")
        lines.append("")


def _format_end_phase(lines: list, d: dict, saved: float, target: float):
    """Week 4+: final score, wins, and lessons."""
    lines.append("<b>MONTH SCORE</b>")
    if saved >= target:
        lines.append(f"  Saved ${saved:,.0f} — target ${target:,} HIT")
    elif saved > 0:
        lines.append(f"  Saved ${saved:,.0f} — ${target - saved:,.0f} short of ${target:,}")
    else:
        lines.append(f"  ${abs(saved):,.0f} over budget")
    lines.append("")

    # Big wins (flex categories only — exclude fixed bills you don't control)
    trends = d.get("trends", {})
    breakdown = d.get("mtd_breakdown", [])
    fixed_cats = d.get("fixed_categories", set())
    wins = []
    for cat_data in sorted(breakdown, key=lambda c: abs(c.get("total", 0)), reverse=True):
        cat = cat_data.get("category", "")
        if cat in fixed_cats:
            continue
        spent = abs(cat_data.get("total", 0))
        trend = trends.get(cat)
        if not trend or spent < 10:
            continue
        pct = trend.get("pct_vs_mean", 0) if isinstance(trend, dict) else trend.pct_vs_mean
        mean = trend.get("mean", 0) if isinstance(trend, dict) else trend.mean
        if pct < -15 and mean > 50:
            wins.append(f"  • {cat}: ${spent:,.0f} (saving ${mean - spent:,.0f}/mo)")
    if wins:
        lines.append("<b>WINS</b>")
        lines.extend(wins[:3])
        lines.append("")
