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


def format_weekly_report_html(report_data: dict, cached_analytics: dict = None,
                              red_cards: list = None, claude_actions: dict = None) -> str:
    """Format action-focused Telegram report. Prioritizes specific actions over information."""
    d = report_data
    week_start = d.get("week_start", "?")
    week_end = d.get("report_date", "?")
    total_spent = abs(d.get("week_spending_total", 0))
    txn_count = d.get("week_txn_count", 0)
    red_cards = red_cards or []
    claude_actions = claude_actions or {}

    # Savings target
    import database as _db
    import os as _os
    _db_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "expenses.db")
    try:
        _conn = _db.get_connection(_db_path)
        savings_target = int(_db.get_setting(_conn, "monthly_savings_target", "1000"))
        _conn.close()
    except Exception:
        savings_target = 1000

    # MTD spending for scorecard
    mtd_total = abs(d.get("mtd_total", total_spent))

    lines = [
        f"<b>💰 Budget Report</b>  {week_start} → {week_end}",
        "",
    ]

    # ── SAVINGS SCORECARD ─────────────────────────────────────────
    lines.append("<b>🎯 SAVINGS SCORECARD</b>")
    lines.append(f"  Target: <b>${savings_target:,}/mo</b>")
    lines.append(f"  This month: <b>${mtd_total:,.0f}</b> spent ({txn_count} transactions)")
    if mtd_total > 0:
        status = "✅ ON TRACK" if mtd_total < savings_target * 4 else ("⚠️ AT RISK" if mtd_total < savings_target * 5 else "🔴 OVER BUDGET")
        lines.append(f"  Status: <b>{status}</b>")
    lines.append("")

    # ── TOP ACTIONS (from Claude preventive actions, ranked by impact) ──
    actions_list = []
    for cat, action in claude_actions.items():
        if isinstance(action, dict) and action.get("severity") in ("critical", "warning"):
            impact = action.get("impact", 0)
            actions_list.append((cat, action, impact))
    actions_list.sort(key=lambda x: x[2], reverse=True)

    if actions_list:
        lines.append(f"<b>🔴 TOP {min(len(actions_list), 3)} ACTIONS (by savings impact)</b>")
        lines.append("")
        for i, (cat, action, impact) in enumerate(actions_list[:3], 1):
            headline = action.get("headline", cat)
            action_text = action.get("action", "Review spending in this category")
            lines.append(f"  <b>{i}. {headline}</b>")
            lines.append(f"  → {action_text}")
            if impact:
                lines.append(f"  💵 Saves: <b>${impact:,.0f}/mo</b> toward your ${savings_target:,} target")
            lines.append("")
    elif red_cards:
        lines.append("<b>🔴 NEEDS ATTENTION</b>")
        lines.append("")
        for rc in red_cards[:3]:
            lines.append(f"  <b>{rc.get('category', '')}</b>: ${rc.get('spent', 0):,.0f} (+{rc.get('pct_above', 0):.0f}% above avg)")
        lines.append("")

    # ── WINS (brief celebration) ──────────────────────────────────
    wins = []
    for cat, action in claude_actions.items():
        if isinstance(action, dict) and action.get("severity") == "good":
            wins.append((cat, action))
    if not wins and cached_analytics:
        for w in cached_analytics.get("spending_wins", [])[:3]:
            wins.append((w["category"], {"headline": f"saving ${w['saved']:,.0f}/mo vs avg"}))

    if wins:
        lines.append("<b>💪 WINS</b>")
        for cat, action in wins[:3]:
            headline = action.get("headline", cat) if isinstance(action, dict) else str(action)
            lines.append(f"  ✅ {headline}")
        lines.append("")

    # ── ACTION CHECKLIST ──────────────────────────────────────────
    action_items = d.get("action_items", [])
    if action_items:
        lines.append("<b>📋 DO THESE THIS WEEK</b>")
        for item in action_items[:3]:
            lines.append(f"  □ {item}")
        lines.append("")
    elif actions_list:
        lines.append("<b>📋 DO THESE THIS WEEK</b>")
        for i, (cat, action, impact) in enumerate(actions_list[:3], 1):
            forecast_note = action.get("forecast_note", "")
            if forecast_note:
                lines.append(f"  □ {forecast_note}")
            else:
                lines.append(f"  □ Review {cat} spending — saves ${impact:,.0f}/mo")
        lines.append("")

    return "\n".join(lines)
