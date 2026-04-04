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


# ═══════════════════════════════════════════════════════════════════
# REPORT FORMATTING — Home-tab-inspired, savings-first
# ═══════════════════════════════════════════════════════════════════

def format_weekly_report_html(report_data: dict, **_kwargs) -> str:
    """Home-tab-inspired Telegram report: savings-first, root-cause-driven.

    Dynamic by week-of-month:
      - start (day 1-7):   Budget plan + last month's lessons
      - middle (day 8-21): Progress tracking + course corrections
      - end (day 22+):     Final scorecard + wins + 6-month trend
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
    gap = saved - target

    lines = []

    # ── HEADER ────────────────────────────────────────────────────
    header_sub = f"Week {week_num} of {weeks_in_month}" if phase != "end" else "Final Score"
    lines.append("\u2501" * 26)
    lines.append(f"  <b>{month_label} {year} \u00b7 {header_sub}</b>")
    lines.append("\u2501" * 26)
    lines.append("")

    # ── SAVINGS HERO or START PLAN ────────────────────────────────
    if phase == "start":
        _format_start_phase(lines, d, daily, days_in_month, income, fixed, target)
    else:
        _format_savings_hero(lines, d, saved, target, gap, income, fixed,
                             disc_spent, disc_budget, daily, days_left)

    # ── WEEK BY WEEK (middle + end) ──────────────────────────────
    weekly_breakdown = d.get("weekly_breakdown", [])
    if phase in ("middle", "end") and weekly_breakdown:
        lines.append("\u2500" * 26)
        lines.append("")
        lines.append("\U0001f4c5 <b>WEEK BY WEEK</b>")
        cumulative = 0
        for wk in weekly_breakdown:
            wk_total = abs(wk.get("total", 0))
            cumulative += wk_total
            wk_start = wk.get("start", "")
            wk_end = wk.get("end", "")
            try:
                s = date.fromisoformat(wk_start)
                e = date.fromisoformat(wk_end)
                date_label = f"{month_name[s.month][:3]} {s.day}-{e.day}"
            except (ValueError, IndexError):
                date_label = f"Wk {wk['week_num']}"
            marker = "  \u25c0 you are here" if wk["week_num"] == week_num and phase != "end" else ""
            lines.append(f"  W{wk['week_num']} ({date_label}):  ${wk_total:,.0f}{marker}")
        lines.append(f"  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
        lines.append(f"  ${cumulative:,.0f} of ${disc_budget:,.0f} budget")
        lines.append("")

    # ── CATEGORY DEVIATIONS (the root cause) ─────────────────────
    over_avg = d.get("over_avg", [])
    under_avg = d.get("under_avg", [])
    if over_avg or under_avg:
        lines.append("\u2500" * 26)
        lines.append("")
        if over_avg:
            lines.append("\U0001f53a <b>OVER AVERAGE</b> (the damage)")
            for c in over_avg:
                lines.append(f"  \u2022 {c['category']}  +${c['dev']:,.0f}  (${c['spent']:,.0f} vs ${c['avg']:,.0f} avg)")
            lines.append("")
        if under_avg:
            lines.append("\U0001f53b <b>UNDER AVERAGE</b> (bright spots)")
            for c in under_avg:
                lines.append(f"  \u2022 {c['category']}  \u2212${abs(c['dev']):,.0f}  (${c['spent']:,.0f} vs ${c['avg']:,.0f} avg)")
            lines.append("")

    # ── THIS WEEK'S ACTIVITY (middle phase) ──────────────────────
    if phase == "middle":
        _format_middle_phase(lines, d)

    # ── HEAVIEST WEEK (middle + end) ─────────────────────────────
    hw = d.get("heaviest_week")
    if hw and phase in ("middle", "end") and disc_spent > 0:
        hw_pct = hw["total"] / disc_spent * 100
        driver_str = " \u00b7 ".join(
            f"{dr['category']} ${dr['total']:,.0f}" for dr in hw.get("drivers", [])
        )
        lines.append(f"\u26a0\ufe0f Heaviest week: W{hw['week_num']} \u2014 ${hw['total']:,.0f} ({hw_pct:.0f}% of total flex)")
        if driver_str:
            lines.append(f"  Driven by: {driver_str}")
        lines.append("")

    # ── END PHASE: WINS + 6-MONTH TREND ──────────────────────────
    if phase == "end":
        _format_end_phase(lines, d, saved, target)

    # ── NEXT STEP (always) ───────────────────────────────────────
    lines.append("\u2500" * 26)
    lines.append("")
    lines.append("<b>NEXT STEP</b>")
    if saved >= target:
        lines.append(f"On track! Keep daily spending under ${daily:,.0f}.")
    elif saved > 0:
        short = target - saved
        lines.append(f"${short:,.0f} short of target. Cut ${short / max(days_left, 1):,.0f}/day to hit it.")
        if over_avg:
            biggest = over_avg[0]
            lines.append(f"\u2192 {biggest['category']} +${biggest['dev']:,.0f} over avg \u2014 biggest lever.")
    else:
        lines.append(f"Over budget by ${abs(saved):,.0f}. Freeze all non-essential spending.")

    # Flag fees/interest
    for cat_data in d.get("mtd_breakdown", []):
        cat = cat_data.get("category", "")
        if "interest" in cat.lower() or "fees" in cat.lower():
            amt = abs(cat_data.get("total", 0))
            if amt > 10:
                lines.append(f"  \u2192 {cat}: ${amt:,.0f}/mo \u2014 eliminate this first")

    # ── BOTTOM LINE (middle + end) ───────────────────────────────
    if phase in ("middle", "end"):
        lines.append("")
        over_budget = max(disc_spent - disc_budget, 0)
        if over_budget > 0:
            lines.append(
                f"<b>Bottom line:</b> Flex budget was ${disc_budget:,.0f}. "
                f"You spent ${disc_spent:,.0f} \u2014 the extra ${over_budget:,.0f} "
                f"came directly out of your ${target:,} savings target."
            )
        elif saved >= target:
            disc_left = disc_budget - disc_spent
            lines.append(
                f"<b>Bottom line:</b> Flex budget was ${disc_budget:,.0f}, "
                f"you spent ${disc_spent:,.0f} \u2014 ${disc_left:,.0f} left over "
                f"went straight to savings. On track!"
            )
        else:
            lines.append(
                f"<b>Bottom line:</b> Flex budget was ${disc_budget:,.0f}, "
                f"you spent ${disc_spent:,.0f}. Savings at ${saved:,.0f} of ${target:,} target."
            )

    return "\n".join(lines)


def _format_savings_hero(lines: list, d: dict, saved: float, target: float,
                          gap: float, income: float, fixed: float,
                          disc_spent: float, disc_budget: float,
                          daily: float, days_left: int):
    """Savings-first hero block — the emotional anchor of the report."""
    if gap >= 0:
        lines.append(f"\U0001f4b0 <b>SAVED: ${saved:,.0f} \u2705</b>")
        lines.append(f"  Target ${target:,} \u00b7 ${gap:,.0f} above goal!")
    elif saved > 0:
        lines.append(f"\U0001f4b0 <b>SAVINGS SHORTFALL: \u2212${abs(gap):,.0f}</b>")
        lines.append(f"  Target ${target:,} \u00b7 Kept only ${saved:,.0f}")
        lines.append(f"  Overspending ate ${abs(gap):,.0f} from your goal")
    else:
        lines.append(f"\U0001f4b0 <b>IN THE RED: \u2212${abs(saved):,.0f}</b>")
        lines.append(f"  Spent ${abs(saved):,.0f} more than earned")
        lines.append(f"  No savings this month")
    lines.append("")

    # Math breakdown
    lines.append(f"  Income         ${income:,.0f}")
    lines.append(f"  Fixed bills    \u2212 ${fixed:,.0f}")
    lines.append(f"  Flex spent     \u2212 ${disc_spent:,.0f}")
    lines.append(f"                 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    lines.append(f"  = Savings       <b>${saved:,.0f}</b>")
    lines.append("")

    # Progress bar
    if disc_budget > 0:
        pct_used = min(disc_spent / disc_budget, 2.0)
        filled = min(int(pct_used * 10), 10)
        bar = "\u2588" * filled + "\u2591" * (10 - filled)
        pct_label = f"{pct_used * 100:.0f}%"
    else:
        bar = "\u2588" * 10
        pct_label = "OVER"

    lines.append(f"  {bar}  {pct_label} of flex budget used")
    if disc_spent <= disc_budget:
        remaining = disc_budget - disc_spent
        if daily > 0 and days_left > 0:
            lines.append(f"  ${remaining:,.0f} left \u00b7 ${daily:,.0f}/day for {days_left} days")
        else:
            lines.append(f"  ${remaining:,.0f} left")
    else:
        over_by = disc_spent - disc_budget
        lines.append(f"  <b>${over_by:,.0f} OVER BUDGET</b>")
    lines.append("")


def _format_start_phase(lines: list, d: dict, daily_budget: float,
                         days_in_month: int, income: float, fixed: float,
                         target: float):
    """Week 1: set the plan, learn from last month."""
    disc_budget = income - fixed - target

    lines.append("\U0001f4ca <b>THE PLAN</b>")
    lines.append(f"  Income         ${income:,.0f}")
    lines.append(f"  Fixed bills    \u2212 ${fixed:,.0f}")
    lines.append(f"  Savings goal   \u2212 ${target:,.0f}")
    lines.append(f"                 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    lines.append(f"  Spending money  <b>${disc_budget:,.0f}</b>")
    lines.append("")
    lines.append(f"  That's <b>${daily_budget:,.0f}/day</b> for {days_in_month} days.")
    lines.append("")

    # Last month's lessons
    overbudget = d.get("last_month_overbudget", [])
    if overbudget:
        from calendar import month_name
        from datetime import date
        today = date.fromisoformat(d["report_date"])
        prev_month = today.month - 1 if today.month > 1 else 12
        prev_label = month_name[prev_month].upper()

        lines.append("\u2500" * 26)
        lines.append("")
        lines.append(f"\U0001f4dd <b>{prev_label} LESSONS</b>")
        for item in overbudget[:3]:
            status_label = "way over" if item["status"] == "over" else "elevated"
            lines.append(f"  \u2022 {item['category']} was {status_label}")
        lines.append("")
        lines.append(f"\U0001f4a1 This month's focus: keep these categories")
        lines.append(f"near their averages and you'll hit your ${target:,} target.")
        lines.append("")


def _format_middle_phase(lines: list, d: dict):
    """Weeks 2-3: this week's activity with top merchants."""
    week_spent = abs(d.get("week_spending_total", 0))
    week_count = d.get("week_txn_count", 0)

    if week_spent > 0:
        lines.append("\u2500" * 26)
        lines.append("")
        lines.append(f"\U0001f4cb <b>THIS WEEK: ${week_spent:,.0f}</b> ({week_count} txns)")
        week_merchants = d.get("week_merchants", [])
        if week_merchants:
            for m in week_merchants[:3]:
                name = m.get("description", "?")
                total = abs(m.get("total_spent", 0))
                if total > 0:
                    lines.append(f"  \u2022 {name}: ${total:,.0f}")
        lines.append("")


def _format_end_phase(lines: list, d: dict, saved: float, target: float):
    """Week 4+: wins, watch list, and 6-month trend."""
    over_avg = d.get("over_avg", [])
    under_avg = d.get("under_avg", [])

    # Wins (categories under average)
    if under_avg:
        lines.append("\u2500" * 26)
        lines.append("")
        lines.append("\U0001f3c6 <b>WINS</b>")
        for c in under_avg:
            lines.append(f"  \u2022 {c['category']}: ${c['spent']:,.0f} (saved ${abs(c['dev']):,.0f} vs avg)")
        lines.append("")

    # Watch list (categories over average)
    if over_avg:
        lines.append("\U0001f53a <b>WATCH LIST</b>")
        for c in over_avg:
            lines.append(f"  \u2022 {c['category']}: ${c['spent']:,.0f} (+${c['dev']:,.0f} vs avg)")
        lines.append("")

    # 6-month savings trend
    savings_trend = d.get("savings_trend_6m", [])
    if savings_trend:
        lines.append("\u2500" * 26)
        lines.append("")
        lines.append("\U0001f4c8 <b>6-MONTH TREND</b>")
        from calendar import month_name
        max_saved = max(abs(s["saved"]) for s in savings_trend) if savings_trend else 1
        hits = 0
        for s in savings_trend:
            bar_len = max(int(abs(s["saved"]) / max_saved * 6), 1) if max_saved > 0 else 1
            bar = "\u2588" * bar_len + "\u2591" * (6 - bar_len)
            _y, _m = s["month"].split("-")
            m_label = month_name[int(_m)][:3]
            hit_mark = " \u2713" if s["hit"] else ""
            is_current = s == savings_trend[-1]
            arrow = " \u2190 this month" if is_current else ""
            lines.append(f"  {m_label} {bar}  ${s['saved']:,.0f}{hit_mark}{arrow}")
            if s["hit"]:
                hits += 1
        lines.append("")
        lines.append(f"  Hit target: {hits} of {len(savings_trend)} months")
        lines.append("")
