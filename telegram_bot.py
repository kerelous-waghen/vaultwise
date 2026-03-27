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
    """Data-driven Telegram report mirroring the dashboard's exact metrics."""
    d = report_data
    from datetime import date
    from calendar import month_name

    today = date.fromisoformat(d["report_date"])
    month_label = f"{month_name[today.month]} {today.year}"

    # Core metrics (computed in gather_report_data using same math as dashboard)
    income = d.get("monthly_income", 0)
    fixed = d.get("effective_fixed", 0)
    disc = d.get("txn_discretionary", 0)
    saved = d.get("saved", 0)
    target = d.get("savings_target", 2000)
    rate = d.get("savings_rate", 0)
    days_left = d.get("days_left", 0)
    daily = d.get("daily_budget", 0)
    gap = saved - target

    # Status (same logic as home.py)
    if saved >= target:
        status = f"✅ ON TRACK — ${gap:,.0f} above goal"
    elif saved > 0:
        status = f"⚠️ AT RISK — ${abs(gap):,.0f} short of target"
    else:
        status = f"🔴 OVER BUDGET — ${abs(saved):,.0f} in the red"

    target_rate = (target / income * 100) if income > 0 else 0

    lines = [
        f"<b>💰 VaultWise — {month_label}</b>",
        "",
        f"<b>🎯 SAVINGS: {status}</b>",
        f"  Saved: <b>${saved:,.0f}</b> (target: ${target:,})",
        f"  Savings rate: <b>{rate:.0f}%</b> (target: {target_rate:.0f}%)",
    ]
    if days_left > 0:
        if daily > 0:
            lines.append(f"  Daily budget: <b>${daily:,.0f}/day</b> for {days_left} days")
        else:
            lines.append(f"  🛑 FREEZE spending for {days_left} days")
    lines.append("")

    # ── THE MATH ──────────────────────────────────────────────────
    lines.append("<b>💵 THE MATH</b>")
    lines.append(f"  Income: ${income:,.0f}")
    lines.append(f"  Fixed bills: ${fixed:,.0f}")
    lines.append(f"  Discretionary: ${disc:,.0f}")
    gap_text = f"+${gap:,.0f} above target" if gap >= 0 else f"${gap:,.0f} vs target"
    lines.append(f"  <b>Saved: ${saved:,.0f}</b> ({gap_text})")
    lines.append("")

    # ── CATEGORIES BY SEVERITY ────────────────────────────────────
    trends = d.get("trends", {})
    budget_statuses = d.get("budget_statuses", {})
    breakdown = d.get("mtd_breakdown", [])

    dir_icons = {"rising": "↑", "falling": "↓", "stable": "→"}

    critical = []
    wins = []
    watch = []

    for cat_data in sorted(breakdown, key=lambda c: abs(c.get("total", 0)), reverse=True):
        cat = cat_data.get("category", "")
        spent = abs(cat_data.get("total", 0))
        if spent < 10:
            continue

        trend = trends.get(cat)
        bs = budget_statuses.get(cat)
        if not trend:
            continue

        # Handle both dict (cached) and TrendResult (dataclass) formats
        if isinstance(trend, dict):
            mean = trend.get("mean", 0)
            pct = trend.get("pct_vs_mean", 0)
            direction = dir_icons.get(trend.get("direction", "stable"), "→")
            severity = trend.get("severity", "normal")
        else:
            mean = trend.mean
            pct = trend.pct_vs_mean
            direction = dir_icons.get(trend.direction, "→")
            severity = trend.severity

        if pct > 0:
            pct_text = f"+{pct:.0f}% vs ${mean:,.0f} avg"
        else:
            pct_text = f"{pct:.0f}% vs ${mean:,.0f} avg"

        entry = f"  • {cat}: <b>${spent:,.0f}</b> ({pct_text}) {direction}"

        bs_status = (bs.status if hasattr(bs, "status") else bs.get("status", "")) if bs else ""
        if severity in ("critical", "warning") or bs_status in ("over", "elevated"):
            critical.append(entry)
        elif pct < -15 and mean > 50:
            saving = mean - spent
            wins.append(f"  • {cat}: <b>${spent:,.0f}</b> ({pct_text}) — saving ${saving:,.0f}/mo")
        elif pct > 5:
            watch.append(entry)

    if critical:
        lines.append("<b>🔴 NEEDS ATTENTION</b>")
        lines.extend(critical[:5])
        lines.append("")

    if wins:
        lines.append("<b>💪 BIG WINS</b>")
        lines.extend(wins[:5])
        lines.append("")

    if watch:
        lines.append("<b>⚠️ WATCH</b>")
        lines.extend(watch[:3])
        lines.append("")

    # ── THIS WEEK ─────────────────────────────────────────────────
    week_spent = abs(d.get("week_spending_total", 0))
    week_count = d.get("week_txn_count", 0)
    if week_spent > 0:
        lines.append(f"<b>📋 THIS WEEK:</b> ${week_spent:,.0f} spent ({week_count} transactions)")
        top_merchants = d.get("top_merchants", [])
        if top_merchants:
            merch_parts = []
            for m in top_merchants[:5]:
                name = m.get("description", "?")
                total = abs(m.get("total_spent", 0) or m.get("total", 0))
                if total > 0:
                    merch_parts.append(f"{name} ${total:,.0f}")
            if merch_parts:
                lines.append(f"  Top: {', '.join(merch_parts)}")
        lines.append("")

    # ── BOTTOM LINE ───────────────────────────────────────────────
    lines.append("<b>🔥 BOTTOM LINE</b>")
    if saved >= target:
        lines.append(f"${saved:,.0f} saved this month — {rate:.0f}% savings rate. Keep it up.")
    elif saved > 0:
        lines.append(f"Positive savings (${saved:,.0f}) but ${abs(gap):,.0f} short of your ${target:,} target.")
    else:
        lines.append(f"Spending exceeds income by ${abs(saved):,.0f}. Review categories flagged above.")

    # Flag recurring waste
    for cat_data in breakdown:
        cat = cat_data.get("category", "")
        if "interest" in cat.lower() or "fees" in cat.lower():
            amt = abs(cat_data.get("total", 0))
            if amt > 10:
                lines.append(f"  💸 {cat}: ${amt:,.0f}/mo — priority to eliminate")

    return "\n".join(lines)
