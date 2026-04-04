"""
Chart generation module — creates Plotly charts and exports as PNG bytes.
Used for Telegram reports and downloadable images.
Requires kaleido for static image export.
"""

from typing import Optional

import plotly.graph_objects as go
import plotly.io as pio
import pandas as pd

import config
import models


# Consistent color palette
COLORS = {
    "green": "#2ecc71",
    "red": "#e74c3c",
    "blue": "#3498db",
    "orange": "#f39c12",
    "purple": "#9b59b6",
    "gray": "#95a5a6",
    "dark": "#2c3e50",
}

CATEGORY_COLORS = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#34495e", "#e91e63", "#00bcd4",
    "#8bc34a", "#ff9800", "#795548", "#607d8b", "#673ab7",
]


def _to_png(fig: go.Figure, width: int = 800, height: int = 500) -> bytes:
    """Convert a Plotly figure to PNG bytes."""
    return pio.to_image(fig, format="png", width=width, height=height, scale=2)


def generate_weekly_spending_chart(weekly_data: dict) -> bytes:
    """Bar chart of this week's spending by category."""
    categories = weekly_data.get("categories", {})
    if not categories:
        return _empty_chart("No spending data this week")

    cats = sorted(categories.keys(), key=lambda k: categories[k]["total"])
    values = [abs(categories[k]["total"]) for k in cats]

    fig = go.Figure(go.Bar(
        x=values,
        y=cats,
        orientation="h",
        marker_color=CATEGORY_COLORS[:len(cats)],
        text=[f"${v:,.0f}" for v in values],
        textposition="auto",
    ))
    fig.update_layout(
        title=f"This Week's Spending: ${sum(values):,.0f}",
        xaxis_title="Amount ($)",
        height=max(400, len(cats) * 35 + 100),
        margin=dict(l=150),
        font=dict(size=14),
    )
    return _to_png(fig, width=800, height=max(400, len(cats) * 35 + 100))


def generate_monthly_trend_chart(trend_data: list[dict]) -> bytes:
    """Line chart of monthly spending over time."""
    if not trend_data:
        return _empty_chart("No trend data available")

    df = pd.DataFrame(trend_data)
    df["spending"] = df["spending"].abs()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["month"], y=df["spending"],
        mode="lines+markers",
        name="Monthly Spending",
        line=dict(color=COLORS["red"], width=3),
        marker=dict(size=8),
    ))

    # Average line
    avg = df["spending"].mean()
    fig.add_hline(y=avg, line_dash="dash", line_color=COLORS["gray"],
                  annotation_text=f"Avg: ${avg:,.0f}")

    fig.update_layout(
        title="Monthly Spending Trend",
        xaxis_title="Month",
        yaxis_title="Total Spent ($)",
        height=400,
        font=dict(size=14),
    )
    return _to_png(fig)


def generate_category_pie_chart(breakdown: list[dict]) -> bytes:
    """Pie chart of spending by category."""
    if not breakdown:
        return _empty_chart("No category data")

    # Filter to expenses only, top 10
    expenses = [b for b in breakdown if b.get("total", 0) < 0]
    expenses.sort(key=lambda x: x["total"])
    top = expenses[:10]

    labels = [b["category"] for b in top]
    values = [abs(b["total"]) for b in top]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.4,
        marker_colors=CATEGORY_COLORS[:len(labels)],
        textinfo="label+percent",
        textfont_size=12,
    ))
    fig.update_layout(
        title="Spending by Category",
        height=500,
        font=dict(size=14),
    )
    return _to_png(fig, width=800, height=500)


def generate_cashflow_chart(months_ahead: int = 66) -> bytes:
    """Cash flow projection chart."""
    df = models.project_cash_flow(months_ahead=months_ahead)

    fig = go.Figure()

    # Monthly net as bars
    colors = [COLORS["red"] if x < 0 else COLORS["green"] for x in df["monthly_net"]]
    fig.add_trace(go.Bar(
        x=df["month"], y=df["monthly_net"],
        name="Monthly Net",
        marker_color=colors,
        opacity=0.7,
    ))

    # Cumulative line
    fig.add_trace(go.Scatter(
        x=df["month"], y=df["cumulative"],
        mode="lines",
        name="Cumulative Savings",
        line=dict(color=COLORS["blue"], width=3),
        yaxis="y2",
    ))

    fig.update_layout(
        title="Cash Flow Projection",
        xaxis_title="Month",
        yaxis=dict(title="Monthly Net ($)"),
        yaxis2=dict(title="Cumulative ($)", overlaying="y", side="right"),
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        font=dict(size=12),
    )
    return _to_png(fig, width=1000, height=500)


def generate_objective_progress_chart(objectives: list[dict]) -> bytes:
    """Horizontal bar chart of objective progress."""
    if not objectives:
        return _empty_chart("No objectives configured")

    labels = []
    targets = []
    currents = []

    for obj in objectives:
        target = obj.get("target", 0) or 0
        current = obj.get("current", 0) or 0
        if target > 0:
            labels.append(obj.get("label", obj.get("objective_id", "?")))
            targets.append(target)
            currents.append(min(current, target))

    if not labels:
        return _empty_chart("No measurable objectives")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=labels, x=targets, orientation="h",
        name="Target", marker_color=COLORS["gray"], opacity=0.3,
    ))
    fig.add_trace(go.Bar(
        y=labels, x=currents, orientation="h",
        name="Current", marker_color=COLORS["green"],
        text=[f"${c:,.0f} / ${t:,.0f}" for c, t in zip(currents, targets)],
        textposition="auto",
    ))

    fig.update_layout(
        title="Objective Progress",
        barmode="overlay",
        height=max(300, len(labels) * 60 + 100),
        margin=dict(l=200),
        font=dict(size=14),
    )
    return _to_png(fig, width=800, height=max(300, len(labels) * 60 + 100))


def generate_month_progress_chart(disc_budget: float, disc_spent: float,
                                   saved: float, target: float,
                                   weekly_breakdown=None) -> bytes:
    """Simple month progress chart: budget consumption + savings status."""
    fig = go.Figure()

    # Spending bar
    remaining = max(disc_budget - disc_spent, 0)
    over = max(disc_spent - disc_budget, 0)

    fig.add_trace(go.Bar(
        y=["Spending"], x=[min(disc_spent, disc_budget)],
        orientation="h", name="Spent",
        marker_color=COLORS["red"] if over > 0 else COLORS["orange"],
        text=[f"${disc_spent:,.0f}"], textposition="inside",
        textfont=dict(size=16, color="white"),
    ))
    if remaining > 0:
        fig.add_trace(go.Bar(
            y=["Spending"], x=[remaining],
            orientation="h", name="Remaining",
            marker_color="#e8e8e8",
            text=[f"${remaining:,.0f} left"], textposition="inside",
            textfont=dict(size=14, color="#666"),
        ))
    if over > 0:
        fig.add_trace(go.Bar(
            y=["Spending"], x=[over],
            orientation="h", name="Over budget",
            marker_color="#c0392b",
            text=[f"+${over:,.0f} over"], textposition="inside",
            textfont=dict(size=14, color="white"),
        ))

    # Savings bar
    if saved >= target:
        fig.add_trace(go.Bar(
            y=["Savings"], x=[saved],
            orientation="h", name="Saved",
            marker_color=COLORS["green"],
            text=[f"${saved:,.0f} saved"], textposition="inside",
            textfont=dict(size=16, color="white"),
        ))
    elif saved > 0:
        fig.add_trace(go.Bar(
            y=["Savings"], x=[saved],
            orientation="h", name="Saved",
            marker_color=COLORS["orange"],
            text=[f"${saved:,.0f}"], textposition="inside",
            textfont=dict(size=14, color="white"),
        ))
        fig.add_trace(go.Bar(
            y=["Savings"], x=[target - saved],
            orientation="h", name="Gap",
            marker_color="#e8e8e8",
            text=[f"${target - saved:,.0f} to go"], textposition="inside",
            textfont=dict(size=14, color="#666"),
        ))
    else:
        fig.add_trace(go.Bar(
            y=["Savings"], x=[abs(saved)],
            orientation="h", name="In the red",
            marker_color=COLORS["red"],
            text=[f"-${abs(saved):,.0f}"], textposition="inside",
            textfont=dict(size=16, color="white"),
        ))

    # Savings target line
    fig.add_vline(x=target, line_dash="dash", line_color=COLORS["dark"],
                  annotation_text=f"Target: ${target:,}", annotation_position="top")

    fig.update_layout(
        title="Month at a Glance",
        barmode="stack",
        height=250,
        xaxis=dict(title="Amount ($)", showgrid=True),
        yaxis=dict(categoryorder="array", categoryarray=["Savings", "Spending"]),
        showlegend=False,
        margin=dict(l=80, r=40, t=60, b=40),
        font=dict(size=14),
    )
    return _to_png(fig, width=800, height=250)


def generate_report_dashboard(report_data: dict) -> bytes:
    """Single dashboard image for the weekly Telegram report.

    Three panels:
      - Top: Category deviations vs average (red=over, green=under)
      - Bottom-left: Week-by-week flex spending pace
      - Bottom-right: 6-month savings trend with target line
    """
    from plotly.subplots import make_subplots
    from calendar import month_name
    from datetime import date

    over_avg = report_data.get("over_avg", [])
    under_avg = report_data.get("under_avg", [])
    weekly_breakdown = report_data.get("weekly_breakdown", [])
    savings_trend = report_data.get("savings_trend_6m", [])
    disc_budget = report_data.get("disc_budget", 0)
    target = report_data.get("savings_target", 2000)
    week_num = report_data.get("week_number", 1)
    phase = report_data.get("month_phase", "middle")

    today = date.fromisoformat(report_data["report_date"])
    title = f"{month_name[today.month].upper()} {today.year}"

    has_deviations = bool(over_avg or under_avg)
    has_weeks = bool(weekly_breakdown)
    has_trend = bool(savings_trend)

    # Determine layout based on available data
    if has_deviations and (has_weeks or has_trend):
        fig = make_subplots(
            rows=2, cols=2,
            row_heights=[0.55, 0.45],
            subplot_titles=["Category vs Average", "", "Week-by-Week Pace", "6-Month Savings"],
            horizontal_spacing=0.12, vertical_spacing=0.15,
            specs=[[{"colspan": 2}, None], [{}, {}]],
        )
    elif has_deviations:
        fig = make_subplots(rows=1, cols=1, subplot_titles=["Category vs Average"])
    else:
        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=["Week-by-Week Pace", "6-Month Savings"],
            horizontal_spacing=0.12,
        )

    # ── Panel 1: Category Deviations ─────────────────────────────
    if has_deviations:
        all_devs = list(reversed(over_avg)) + list(reversed(under_avg))
        cats = [d["category"] for d in all_devs]
        devs = [d["dev"] for d in all_devs]
        bar_colors = ["#ef4444" if d > 0 else "#10b981" for d in devs]
        labels = [f"+${d:,.0f}" if d > 0 else f"\u2212${abs(d):,.0f}" for d in devs]

        fig.add_trace(go.Bar(
            y=cats, x=devs, orientation="h",
            marker_color=bar_colors,
            text=labels, textposition="outside",
            textfont=dict(size=13, color=bar_colors),
            showlegend=False,
        ), row=1, col=1)

        fig.add_vline(x=0, line_color="#94a3b8", line_width=1, row=1, col=1)

        # Add avg annotation on each bar
        for i, d in enumerate(all_devs):
            fig.add_annotation(
                y=d["category"], x=0,
                text=f"avg ${d['avg']:,.0f}", showarrow=False,
                font=dict(size=10, color="#94a3b8"),
                xshift=-35 if d["dev"] > 0 else 35,
                row=1, col=1,
            )

    # ── Panel 2: Week-by-Week Pace ───────────────────────────────
    bottom_row = 2 if has_deviations else 1
    if has_weeks:
        wk_labels = [f"W{wk['week_num']}" for wk in weekly_breakdown]
        wk_totals = [abs(wk.get("total", 0)) for wk in weekly_breakdown]
        wk_colors = []
        for wk in weekly_breakdown:
            if wk["week_num"] == week_num and phase != "end":
                wk_colors.append("#6366f1")  # Current week = indigo
            elif wk["week_num"] < week_num or phase == "end":
                wk_colors.append("#3b82f6")  # Past weeks = blue
            else:
                wk_colors.append("#e2e8f0")  # Future weeks = light gray

        fig.add_trace(go.Bar(
            x=wk_labels, y=wk_totals,
            marker_color=wk_colors,
            text=[f"${v:,.0f}" for v in wk_totals],
            textposition="outside",
            textfont=dict(size=11),
            showlegend=False,
        ), row=bottom_row, col=1)

        # Budget pace line (budget / num weeks)
        if disc_budget > 0 and len(weekly_breakdown) > 0:
            weekly_budget = disc_budget / len(weekly_breakdown)
            fig.add_hline(
                y=weekly_budget, line_dash="dash", line_color="#f59e0b",
                line_width=2, row=bottom_row, col=1,
                annotation_text=f"${weekly_budget:,.0f}/wk pace",
                annotation_font=dict(size=10, color="#f59e0b"),
            )

    # ── Panel 3: 6-Month Savings Trend ───────────────────────────
    if has_trend:
        trend_col = 2
        m_labels = []
        m_saved = []
        m_colors = []
        for s in savings_trend:
            _y, _m = s["month"].split("-")
            m_labels.append(month_name[int(_m)][:3])
            m_saved.append(s["saved"])
            if s["saved"] >= target:
                m_colors.append("#10b981")  # Hit target = green
            elif s["saved"] > 0:
                m_colors.append("#f59e0b")  # Positive but missed = amber
            else:
                m_colors.append("#ef4444")  # Negative = red

        fig.add_trace(go.Bar(
            x=m_labels, y=m_saved,
            marker_color=m_colors,
            text=[f"${v:,.0f}" for v in m_saved],
            textposition="outside",
            textfont=dict(size=11),
            showlegend=False,
        ), row=bottom_row, col=trend_col)

        # Target line
        fig.add_hline(
            y=target, line_dash="dash", line_color="#2c3e50",
            line_width=2, row=bottom_row, col=trend_col,
            annotation_text=f"Target ${target:,}",
            annotation_font=dict(size=10, color="#2c3e50"),
        )

        # Zero line if there are negative values
        if any(s < 0 for s in m_saved):
            fig.add_hline(y=0, line_color="#94a3b8", line_width=1,
                          row=bottom_row, col=trend_col)

    # ── Layout ───────────────────────────────────────────────────
    total_height = 700 if has_deviations and (has_weeks or has_trend) else 400
    fig.update_layout(
        title=dict(
            text=f"<b>{title} \u2014 Weekly Report</b>",
            font=dict(size=18),
            x=0.5,
        ),
        height=total_height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Arial, sans-serif", size=12, color="#334155"),
        margin=dict(l=20, r=20, t=60, b=20),
        showlegend=False,
    )

    # Clean up axes
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9", zeroline=False)
    fig.update_yaxes(showgrid=False, zeroline=False)

    # Category panel: hide x-axis ticks, show grid
    if has_deviations:
        fig.update_xaxes(showticklabels=False, row=1, col=1)
        fig.update_yaxes(tickfont=dict(size=12), row=1, col=1)

    return _to_png(fig, width=900, height=total_height)


def _empty_chart(message: str) -> bytes:
    """Generate a placeholder chart with a message."""
    fig = go.Figure()
    fig.add_annotation(
        text=message, xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False, font=dict(size=20, color=COLORS["gray"]),
    )
    fig.update_layout(
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        height=300,
    )
    return _to_png(fig, width=800, height=300)
