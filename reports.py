"""
Weekly report generation and optional email dispatch.
Can be triggered manually from the app or scheduled via cron/APScheduler.
"""

import os
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import database
import config


def gather_report_data(conn, report_date: Optional[date] = None, period: str = "weekly") -> dict:
    """Pull transactions for the configured period, MTD totals, objective progress, alerts.
    period: 'weekly' (7 days), 'biweekly' (14 days), 'monthly' (month to date)
    """
    today = report_date or date.today()
    period_days = {"weekly": 7, "biweekly": 14, "monthly": (today - today.replace(day=1)).days or 30}
    week_ago = today - timedelta(days=period_days.get(period, 7))
    month_start = today.replace(day=1)

    # This week's transactions
    week_txns = database.get_transactions(
        conn,
        start_date=week_ago.isoformat(),
        end_date=today.isoformat(),
    )
    week_txns_list = [dict(t) for t in week_txns]

    # Filter to active categories only (exclude Financial Transfers, etc.)
    try:
        import category_engine
        _active_cats = category_engine.get_active_categories(conn)
        week_txns_list = [t for t in week_txns_list if t.get("category") in _active_cats]
    except Exception:
        pass

    # Month-to-date summary
    mtd_summary = database.get_monthly_summary(conn, today.year, today.month)

    # Category breakdown this month — filtered to active categories only
    _raw_breakdown = database.get_category_breakdown(
        conn, month_start.isoformat(), today.isoformat()
    )
    try:
        import category_engine
        _active_cats = category_engine.get_active_categories(conn)
        mtd_breakdown = [c for c in _raw_breakdown if c.get("category") in _active_cats]
    except Exception:
        mtd_breakdown = _raw_breakdown

    # Active alerts
    alerts = [dict(a) for a in database.get_active_alerts(conn)]

    # Objective progress (last snapshots)
    objectives = {}
    for obj in config.OBJECTIVES:
        history = database.get_objective_history(conn, obj["id"])
        if history:
            latest = dict(history[-1])
            objectives[obj["id"]] = {
                "label": obj["label"],
                "target": obj.get("target"),
                "current": latest["current_amount"],
                "deadline": obj.get("deadline"),
            }
        else:
            objectives[obj["id"]] = {
                "label": obj["label"],
                "target": obj.get("target"),
                "current": 0,
                "deadline": obj.get("deadline"),
            }

    # Spending intelligence: budget status + tips
    budget_status = []
    savings_tips = []
    try:
        import spending_intelligence
        budget_status = spending_intelligence.get_category_budget_status(conn)
        savings_tips = spending_intelligence.get_savings_tips(conn)
    except Exception:
        pass

    # MTD total for scorecard
    mtd_total = sum(abs(c.get("total", 0)) for c in mtd_breakdown) if mtd_breakdown else 0

    return {
        "report_date": today.isoformat(),
        "week_start": week_ago.isoformat(),
        "period": period,
        "week_transactions": week_txns_list,
        "week_spending_total": sum(t["amount"] for t in week_txns_list if t["amount"] < 0),
        "week_txn_count": len(week_txns_list),
        "mtd_summary": mtd_summary,
        "mtd_total": mtd_total,
        "mtd_breakdown": mtd_breakdown,
        "objective_progress": objectives,
        "alerts": alerts,
        "budget_status": budget_status,
        "savings_tips": savings_tips,
    }


def generate_and_save_report(db_path: str, advisor, report_date: Optional[date] = None) -> dict:
    """Orchestrate: gather data -> statistical analysis -> Claude writes report -> save to DB."""
    conn = database.get_connection(db_path)
    try:
        data = gather_report_data(conn, report_date)

        # Build statistical context for data-driven report
        statistical_context = None
        try:
            import analytics
            statistical_context = analytics.build_statistical_context(conn)
        except Exception:
            pass

        report = advisor.generate_weekly_report(
            week_transactions=data["week_transactions"],
            monthly_context=data["mtd_summary"],
            objective_progress=data["objective_progress"],
            alerts=data["alerts"],
            statistical_context=statistical_context,
        )

        report_id = database.save_weekly_report(
            conn,
            report_date=(report_date or date.today()).isoformat(),
            subject=report.get("subject", "Weekly Budget Report"),
            html_body=report.get("html_body", ""),
            plain_text=report.get("plain_text", ""),
        )

        report["id"] = report_id
        report["data"] = data
        return report
    finally:
        conn.close()


def send_email_report(report: dict) -> bool:
    """Send report via SMTP. Returns True if sent successfully."""
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    recipients = os.environ.get("REPORT_RECIPIENTS", "").split(",")

    if not all([smtp_host, smtp_user, smtp_pass, recipients[0]]):
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = report.get("subject", "Weekly Budget Report")
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)

    plain = MIMEText(report.get("plain_text", ""), "plain")
    html = MIMEText(report.get("html_body", ""), "html")
    msg.attach(plain)
    msg.attach(html)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipients, msg.as_string())
        return True
    except Exception:
        return False
