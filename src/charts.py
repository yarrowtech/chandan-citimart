"""Plotly business charts and their underlying tables."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config.kpi_thresholds import (
    DEFAULT_KPI_COLOR_RULES,
    KPIColorRule,
    status_for,
)
from src.forecasting import ForecastResult
from src.formatting import currency
from src.kpi_engine import safe_divide

COLORS = {
    "navy": "#12304A",
    "blue": "#1665A8",
    "cyan": "#20A4B8",
    "gold": "#F4B740",
    "red": "#D64545",
    "green": "#2E8B57",
    "gray": "#7A8793",
}

GAUGE_CHART_HEIGHT = 300


def _period_labels(starts: pd.Series, granularity: str) -> pd.Series:
    """Render complete business periods instead of resample anchor dates."""
    dates = pd.to_datetime(starts)
    if granularity == "Year":
        return dates.dt.strftime("%Y")
    if granularity == "Quarter":
        return "Q" + dates.dt.quarter.astype(str) + " " + dates.dt.year.astype(str)
    if granularity == "Month":
        return dates.dt.strftime("%B %Y")
    if granularity == "Week":
        ends = pd.Series(
            dates.to_numpy(dtype="datetime64[ns]") + np.timedelta64(6, "D"),
            index=dates.index,
        )
        return dates.dt.strftime("%d-%m-%Y") + " to " + ends.dt.strftime("%d-%m-%Y")
    return dates.dt.strftime("%d-%m-%Y")


def _layout(figure: go.Figure, title: str) -> go.Figure:
    figure.update_layout(
        title=title,
        template="plotly_white",
        margin=dict(l=30, r=25, t=65, b=35),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.05, x=0),
    )
    figure.update_xaxes(tickformat="%d-%m-%Y", hoverformat="%d-%m-%Y")
    return figure


def empty_figure(title: str, message: str) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(text=message, x=0.5, y=0.5, showarrow=False, font_size=15)
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return _layout(figure, title)


def sales_by_period(
    daily: pd.DataFrame, granularity: str
) -> tuple[go.Figure, pd.DataFrame]:
    if daily.empty:
        return empty_figure("Net vs Gross Sales", "No data for active filters."), pd.DataFrame()
    rule = {"Year": "YS", "Quarter": "QS-JAN", "Month": "MS", "Week": "W-MON", "Day": "D"}[
        granularity
    ]
    columns = [column for column in ("net_sales", "gross_sales", "target") if column in daily]
    resampler = daily.set_index("date")[columns].resample(
        rule,
        label="left" if granularity == "Week" else None,
        closed="left" if granularity == "Week" else None,
    )
    table = resampler.sum(min_count=1).reset_index().rename(
        columns={"date": "Period start"}
    )
    table["discount_gap"] = table.get("gross_sales", np.nan) - table.get("net_sales", np.nan)
    numeric_columns = table.select_dtypes(include="number").columns
    table[numeric_columns] = table[numeric_columns].round(0)
    table.insert(
        0,
        "Period",
        _period_labels(table["Period start"], granularity),
    )
    table = table.drop(columns=["Period start"])
    figure = go.Figure()
    figure.add_bar(
        x=table["Period"],
        y=table["net_sales"],
        name="Net Sales",
        marker_color=COLORS["blue"],
        hovertemplate="₹%{y:,.0f}<extra>Net Sales</extra>",
    )
    if "gross_sales" in table and table["gross_sales"].notna().any():
        figure.add_bar(
            x=table["Period"],
            y=table["gross_sales"],
            name="Gross Sales",
            marker_color=COLORS["cyan"],
            hovertemplate="₹%{y:,.0f}<extra>Gross Sales</extra>",
        )
    if "target" in table and table["target"].notna().any():
        figure.add_scatter(
            x=table["Period"],
            y=table["target"],
            name="Target",
            mode="lines+markers",
            line_color=COLORS["gold"],
            hovertemplate="₹%{y:,.0f}<extra>Target</extra>",
        )
    figure.update_layout(barmode="group")
    figure.update_yaxes(title="Sales (₹)", tickprefix="₹", separatethousands=True)
    return _layout(figure, f"Net vs Gross Sales — {granularity}"), table


def _customer_period_table(daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregate traffic measures at a readable temporal grain."""
    unique_days = daily["date"].nunique()
    if unique_days <= 45:
        rule, grain = "D", "Day"
    elif unique_days <= 365:
        rule, grain = "W-MON", "Week"
    else:
        rule, grain = "MS", "Month"
    table = (
        daily.set_index("date")[["footfall", "nob"]]
        .resample(rule, label="left", closed="left")
        .sum(min_count=1)
        .dropna(how="all")
        .reset_index()
    )
    table["conversion_percentage"] = (
        table["nob"] / table["footfall"].replace(0, np.nan)
    )
    table["Period"] = _period_labels(table["date"], grain)
    table["Grain"] = grain
    return table[
        ["date", "Period", "Grain", "footfall", "nob", "conversion_percentage"]
    ]


def footfall_bills_chart(daily: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    required = {"date", "footfall", "nob"}
    if daily.empty or not required.issubset(daily):
        return empty_figure(
            "Footfall vs NoB", "Required source fields not available."
        ), pd.DataFrame()
    table = _customer_period_table(daily)
    figure = go.Figure()
    figure.add_bar(
        x=table["Period"],
        y=table["footfall"],
        name="Footfall",
        marker_color=COLORS["cyan"],
        hovertemplate="%{y:,.0f}<extra>Footfall</extra>",
    )
    figure.add_bar(
        x=table["Period"],
        y=table["nob"],
        name="NoB",
        marker_color=COLORS["blue"],
        hovertemplate="%{y:,.0f}<extra>NoB</extra>",
    )
    figure.update_yaxes(title="People / bills", rangemode="tozero")
    figure.update_layout(barmode="group")
    return _layout(figure, "Footfall vs NoB"), table


def conversion_percentage_chart(
    daily: pd.DataFrame,
    color_rule: KPIColorRule | None = None,
) -> tuple[go.Figure, pd.DataFrame]:
    """Show weighted NoB-to-footfall conversion as a separate trend."""
    required = {"date", "footfall", "nob"}
    if daily.empty or not required.issubset(daily):
        return empty_figure(
            "Conversion Percentage", "Required source fields not available."
        ), pd.DataFrame()
    table = _customer_period_table(daily)
    figure = go.Figure()
    figure.add_scatter(
        x=table["Period"],
        y=table["conversion_percentage"],
        name="Conversion %",
        mode="lines+markers",
        line={"color": COLORS["gold"], "width": 3},
        marker={"size": 7, "color": COLORS["navy"]},
        hovertemplate="%{y:.1%}<extra>Conversion</extra>",
    )
    rule = color_rule or DEFAULT_KPI_COLOR_RULES["conversion"]
    figure.add_hline(
        y=rule.lower_bound,
        line_dash="dash",
        line_color=COLORS["gray"],
        annotation_text=f"Yellow from {rule.lower_bound:.0%}",
    )
    figure.add_hline(
        y=rule.upper_bound,
        line_dash="dash",
        line_color=COLORS["green"],
        annotation_text=f"Green above {rule.upper_bound:.0%}",
    )
    figure.update_yaxes(
        title="Conversion percentage", tickformat=".0%", rangemode="tozero"
    )
    return _layout(figure, "Conversion Percentage"), table


def gauge(
    value: float | None,
    title: str,
    color_rule: KPIColorRule,
    kind: str,
    previous: float | None = None,
) -> go.Figure:
    if value is None:
        figure = empty_figure(title, "N/A — Required source field not available")
        figure.update_layout(
            height=GAUGE_CHART_HEIGHT,
            margin={"l": 12, "r": 12, "t": 58, "b": 12},
            showlegend=False,
        )
        return figure

    if kind == "currency":
        maximum = max(color_rule.upper_bound * 1.5, value * 1.2, 1)
        rendered_value = f"₹{value:,.0f}"
    elif kind == "percent":
        maximum = max(1.1, color_rule.upper_bound * 1.25, value * 1.15)
        rendered_value = f"{value:.1%}"
    else:
        maximum = max(color_rule.upper_bound * 1.4, value * 1.2, 1)
        rendered_value = f"{value:,.1f}"

    center_x, center_y = 0.5, 0.23
    outer_radius, inner_radius = 0.43, 0.335

    def arc_path(start: float, end: float) -> str:
        """Return a smooth annular-sector path for one gauge band."""
        start_fraction = max(0.0, min(start / maximum, 1.0))
        end_fraction = max(0.0, min(end / maximum, 1.0))
        start_angle = np.pi * (1.0 - start_fraction)
        end_angle = np.pi * (1.0 - end_fraction)
        outer_angles = np.linspace(start_angle, end_angle, 48)
        inner_angles = np.linspace(end_angle, start_angle, 48)
        points = [
            (
                center_x + outer_radius * np.cos(angle),
                center_y + outer_radius * np.sin(angle),
            )
            for angle in outer_angles
        ]
        points.extend(
            (
                center_x + inner_radius * np.cos(angle),
                center_y + inner_radius * np.sin(angle),
            )
            for angle in inner_angles
        )
        commands = [f"M {points[0][0]:.5f},{points[0][1]:.5f}"]
        commands.extend(f"L {x:.5f},{y:.5f}" for x, y in points[1:])
        commands.append("Z")
        return " ".join(commands)

    bands = [
        (0.0, color_rule.lower_bound, "#D83B3B"),
        (color_rule.lower_bound, color_rule.upper_bound, "#F4B740"),
        (color_rule.upper_bound, maximum, "#08A611"),
    ]
    shapes = [
        {
            "type": "path",
            "path": arc_path(start, end),
            "fillcolor": fill,
            "line": {"color": fill, "width": 0},
            "layer": "below",
        }
        for start, end, fill in bands
        if end > start
    ]

    needle_fraction = max(0.0, min(value / maximum, 1.0))
    needle_angle = np.pi * (1.0 - needle_fraction)
    needle_length = inner_radius * 0.91
    needle_x = center_x + needle_length * np.cos(needle_angle)
    needle_y = center_y + needle_length * np.sin(needle_angle)
    shapes.append(
        {
            "type": "line",
            "x0": center_x,
            "y0": center_y,
            "x1": needle_x,
            "y1": needle_y,
            "line": {"color": "#111111", "width": 5},
            "layer": "above",
        }
    )

    figure = go.Figure()
    figure.add_scatter(
        x=[center_x],
        y=[center_y],
        mode="markers",
        marker={"size": 21, "color": "#111111"},
        hoverinfo="skip",
        showlegend=False,
    )

    delta_text = ""
    delta_color = COLORS["gray"]
    if previous is not None and previous != 0:
        change = (value - previous) / abs(previous)
        delta_text = (
            f"{'▲' if change >= 0 else '▼'} "
            f"{abs(change):.1%} vs previous period"
        )
        delta_color = COLORS["green"] if change >= 0 else COLORS["red"]

    annotations = [
        {
            "x": center_x,
            "y": 0.115,
            "text": f"<b>{rendered_value}</b>",
            "showarrow": False,
            "font": {"size": 30, "color": "#050505"},
        },
    ]
    if delta_text:
        annotations.append(
            {
                "x": center_x,
                "y": 0.035,
                "text": delta_text,
                "showarrow": False,
                "font": {"size": 11, "color": delta_color},
            }
        )

    figure.update_layout(
        template="plotly_white",
        height=GAUGE_CHART_HEIGHT,
        autosize=True,
        margin={"l": 8, "r": 8, "t": 68, "b": 0},
        title={
            "text": (
                f"<b>{title} Gauge</b><br>"
                f"<span style='font-size:11px;color:{COLORS['gray']}'>"
                f"Selected-period value · colour bands from "
                f"{color_rule.source}</span>"
            ),
            "x": 0.01,
            "y": 0.95,
            "xanchor": "left",
            "yanchor": "top",
            "font": {"size": 16, "color": "#111111"},
        },
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        showlegend=False,
        shapes=shapes,
        annotations=annotations,
        xaxis={
            "range": [0, 1],
            "visible": False,
            "fixedrange": True,
            "constrain": "domain",
        },
        yaxis={
            "range": [0, 0.82],
            "visible": False,
            "fixedrange": True,
            "scaleanchor": "x",
            "scaleratio": 1,
        },
        hovermode=False,
    )
    return figure


def conversion_funnel(daily: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    if daily.empty or not {"footfall", "nob"}.issubset(daily):
        return empty_figure("Conversion Funnel", "Footfall or NOB is unavailable."), pd.DataFrame()
    footfall = daily["footfall"].sum(min_count=1)
    transactions = daily["nob"].sum(min_count=1)
    if pd.isna(footfall) or pd.isna(transactions):
        return empty_figure("Conversion Funnel", "Footfall or NOB is unavailable."), pd.DataFrame()
    table = pd.DataFrame({"Stage": ["Footfall", "Transactions"], "Value": [footfall, transactions]})
    table["Stage conversion"] = [1.0, safe_divide(transactions, footfall)]
    figure = go.Figure(
        go.Funnel(y=table["Stage"], x=table["Value"], textinfo="value+percent initial")
    )
    return _layout(figure, "Conversion Funnel: Footfall → Transactions"), table


def monthly_sales(daily: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    if daily.empty:
        return empty_figure("Monthly Sales", "No data for active filters."), pd.DataFrame()
    columns = [column for column in ("net_sales", "gross_sales", "target") if column in daily]
    table = daily.set_index("date")[columns].resample("MS").sum(min_count=1).reset_index()
    table[columns] = table[columns].round(0)
    table["Period"] = table["date"].dt.strftime("%B %Y")
    table["achievement"] = table["net_sales"] / table.get("target", np.nan)
    table["previous_year_sales"] = table["net_sales"].shift(12)
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_bar(x=table["Period"], y=table["net_sales"], name="Net Sales", marker_color=COLORS["blue"])
    if "gross_sales" in table:
        figure.add_scatter(x=table["Period"], y=table["gross_sales"], name="Gross Sales", mode="lines+markers")
    if "target" in table:
        figure.add_scatter(x=table["Period"], y=table["target"], name="Target", mode="lines")
    if table["achievement"].notna().any():
        figure.add_scatter(
            x=table["Period"], y=table["achievement"], name="Achievement", secondary_y=True
        )
        figure.update_traces(
            selector={"name": "Achievement"},
            hovertemplate="%{y:.0%}<extra>Achievement</extra>",
        )
        figure.update_yaxes(tickformat=".0%", title="Achievement", secondary_y=True)
    figure.update_yaxes(tickprefix="₹", title="Sales", secondary_y=False)
    table = table.drop(columns=["date"])
    return _layout(figure, "Monthly Sales, Target and Achievement"), table


def daily_trend(daily: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    if daily.empty:
        return empty_figure("Daily Sales Trend", "No data for active filters."), pd.DataFrame()
    table = daily.groupby(["date", "store_name"], as_index=False)["net_sales"].sum()
    table["net_sales"] = table["net_sales"].round(0)
    totals = table.groupby("date", as_index=False)["net_sales"].sum()
    totals["rolling_7"] = totals["net_sales"].rolling(7, min_periods=1).mean()
    totals["rolling_7"] = totals["rolling_7"].round(0)
    figure = px.line(
        table,
        x="date",
        y="net_sales",
        color="store_name",
        labels={"net_sales": "Net Sales (₹)", "store_name": "Store"},
    )
    figure.add_scatter(
        x=totals["date"],
        y=totals["rolling_7"],
        name="7-day rolling average",
        line={"color": COLORS["gold"], "width": 3},
    )
    return _layout(figure, "Daily Net Sales and 7-Day Rolling Average"), totals


def weekday_average(daily: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    if daily.empty:
        return empty_figure("Average by Day of Week", "No data for active filters."), pd.DataFrame()
    working = daily.groupby("date", as_index=False).agg(
        net_sales=("net_sales", "sum"),
        transactions=("nob", lambda x: x.sum(min_count=1)) if "nob" in daily else ("net_sales", lambda x: np.nan),
        footfall=("footfall", lambda x: x.sum(min_count=1)) if "footfall" in daily else ("net_sales", lambda x: np.nan),
    )
    working["day_of_week"] = working["date"].dt.day_name()
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    table = working.groupby("day_of_week", as_index=False).mean(numeric_only=True)
    for column in ("net_sales", "transactions", "footfall"):
        if column in table:
            table[column] = table[column].round(0)
    table["day_of_week"] = pd.Categorical(table["day_of_week"], order, ordered=True)
    table = table.sort_values("day_of_week")
    table["conversion"] = table["transactions"] / table["footfall"].replace(0, np.nan)
    figure = px.bar(
        table,
        x="day_of_week",
        y="net_sales",
        category_orders={"day_of_week": order},
        labels={"net_sales": "Average Daily Net Sales (₹)", "day_of_week": ""},
    )
    figure.update_traces(marker_color=COLORS["blue"])
    return _layout(figure, "Average Sales by Day of Week"), table


def target_achievement(
    daily: pd.DataFrame,
    color_rule: KPIColorRule | None = None,
) -> tuple[go.Figure, pd.DataFrame]:
    if daily.empty or "target" not in daily or daily["target"].notna().sum() == 0:
        return empty_figure("Target Achievement by Month", "Target cannot be derived for active data."), pd.DataFrame()
    table = daily.set_index("date")[["net_sales", "target"]].resample("MS").sum().reset_index()
    table[["net_sales", "target"]] = table[["net_sales", "target"]].round(0)
    table["Period"] = table["date"].dt.strftime("%B %Y")
    table["achievement"] = table["net_sales"] / table["target"].replace(0, np.nan)
    rule = color_rule or DEFAULT_KPI_COLOR_RULES["achievement"]
    table["status"] = table["achievement"].map(
        lambda value: rule.status(None if pd.isna(value) else float(value))
    )
    colors = table["status"].map({"Red": COLORS["red"], "Yellow": COLORS["gold"], "Green": COLORS["green"]})
    figure = go.Figure(
        go.Bar(
            x=table["Period"],
            y=table["achievement"],
            marker_color=colors,
            text=table["achievement"].map(lambda value: f"{value:.0%}"),
            hovertemplate="%{y:.0%}<extra>Achievement</extra>",
        )
    )
    figure.add_hline(y=1.0, line_dash="dash", annotation_text="100% target")
    figure.update_yaxes(tickformat=".0%")
    table = table.drop(columns=["date"])
    table = table.rename(columns={"status": "color_code"})
    return _layout(figure, "Target Achievement by Month"), table


def monthly_bridge(daily: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    if daily.empty or daily["date"].dt.to_period("M").nunique() < 2:
        return empty_figure("Monthly Sales Bridge", "At least two months are required."), pd.DataFrame()
    working = daily.assign(month=daily["date"].dt.to_period("M"))
    months = sorted(working["month"].unique())[-2:]
    pivot = (
        working[working["month"].isin(months)]
        .pivot_table(index="store_name", columns="month", values="net_sales", aggfunc="sum", fill_value=0)
        .reindex(columns=months, fill_value=0)
    )
    start_total = pivot[months[0]].sum()
    contributions = pivot[months[1]] - pivot[months[0]]
    table = contributions.round(0).rename("Change").reset_index()
    start_label = months[0].start_time.strftime("%B %Y")
    end_label = months[1].start_time.strftime("%B %Y")
    x = [start_label, *table["store_name"].tolist(), end_label]
    y = [
        round(float(start_total)),
        *table["Change"].tolist(),
        round(float(pivot[months[1]].sum())),
    ]
    measure = ["absolute", *(["relative"] * len(table)), "total"]
    figure = go.Figure(
        go.Waterfall(x=x, y=y, measure=measure, connector={"line": {"color": COLORS["gray"]}})
    )
    return _layout(
        figure,
        f"Monthly Sales Bridge: {start_label} to {end_label} by Store",
    ), table


def same_day_comparison(
    daily: pd.DataFrame, selected_day: int = 1
) -> tuple[go.Figure, pd.DataFrame]:
    """Compare sales for one selected day-of-month across the full month history."""
    if daily.empty:
        return empty_figure("Monthly Same-Day Comparison", "No data."), pd.DataFrame()
    if selected_day < 1 or selected_day > 31:
        raise ValueError("selected_day must be from 1 through 31")
    working = daily.copy()
    working["month_period"] = working["date"].dt.to_period("M")
    working["day"] = working["date"].dt.day
    month_periods = pd.period_range(
        working["month_period"].min(),
        working["month_period"].max(),
        freq="M",
    )
    selected = (
        working[working["day"].eq(selected_day)]
        .groupby("month_period", as_index=False)["net_sales"]
        .sum()
    )
    table = pd.DataFrame({"month_period": month_periods}).merge(
        selected, on="month_period", how="left"
    )
    table["Month"] = table["month_period"].dt.strftime("%b-%Y")
    table["Day of month"] = f"Day {selected_day}"
    table["Net Sales"] = table["net_sales"].round(0)
    figure = go.Figure(
        go.Bar(
            x=table["Month"],
            y=table["Net Sales"],
            marker_color="#20AD7B",
            text=table["Net Sales"].map(
                lambda value: currency(value) if pd.notna(value) else "N/A"
            ),
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                f"Day {selected_day}<br>%{{x}}<br>₹%{{y:,.0f}}"
                "<extra>Net Sales</extra>"
            ),
        )
    )
    figure.update_yaxes(title="Net Sales (₹)", tickprefix="₹", separatethousands=True)
    output = table[["Month", "Day of month", "Net Sales"]]
    return _layout(
        figure, f"Monthly Same-Day Comparison — Day {selected_day}"
    ), output


def yearly_same_month(daily: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    if daily.empty:
        return empty_figure("Yearly Same-Month Comparison", "No data."), pd.DataFrame()
    aggregations = {"net_sales": "sum"}
    for column in ("gross_sales", "nob", "footfall", "target"):
        if column in daily:
            aggregations[column] = "sum"
    table = (
        daily.assign(year=daily["date"].dt.year, month=daily["date"].dt.month_name())
        .groupby(["year", "month"], as_index=False)
        .agg(aggregations)
    )
    numeric_columns = table.select_dtypes(include="number").columns
    table[numeric_columns] = table[numeric_columns].round(0)
    table["atv"] = table["net_sales"] / table.get("nob", np.nan)
    table["conversion"] = table.get("nob", np.nan) / table.get("footfall", np.nan)
    table["achievement"] = table["net_sales"] / table.get("target", np.nan)
    order = list(pd.date_range("2024-01-01", periods=12, freq="MS").month_name())
    figure = px.bar(
        table,
        x="month",
        y="net_sales",
        color=table["year"].astype(str),
        barmode="group",
        category_orders={"month": order},
        labels={"color": "Year"},
    )
    return _layout(figure, "Yearly Same-Month Net Sales Comparison"), table


def hierarchy_chart(
    detail: pd.DataFrame, level: str
) -> tuple[go.Figure, pd.DataFrame]:
    if detail.empty or level not in detail or "net_sales" not in detail:
        return empty_figure("Retail Hierarchy Drill-Down", f"{level.title()} is unavailable."), pd.DataFrame()
    aggregations: dict[str, tuple[str, str]] = {
        "net_sales": ("net_sales", "sum"),
        "detail_rows": ("net_sales", "size"),
    }
    if "gross_sales" in detail:
        aggregations["gross_sales"] = ("gross_sales", "sum")
    if "quantity" in detail:
        aggregations["detail_quantity"] = ("quantity", "sum")
    if "date" in detail:
        aggregations["sales_days"] = ("date", "nunique")
    table = (
        detail.dropna(subset=[level])
        .groupby(level, as_index=False)
        .agg(**aggregations)
        .sort_values("net_sales", ascending=False)
    )
    if "gross_sales" in table:
        table["discount"] = table["gross_sales"] - table["net_sales"]
        table["discount_pct"] = (
            table["discount"] / table["gross_sales"].replace(0, np.nan)
        )
    if "sales_days" in table:
        table["average_daily_sales"] = (
            table["net_sales"] / table["sales_days"].replace(0, np.nan)
        )
    total_sales = table["net_sales"].sum()
    table["share"] = (
        table["net_sales"] / total_sales if total_sales else np.nan
    )
    table["rank"] = range(1, len(table) + 1)
    numeric_columns = [
        column
        for column in (
            "net_sales",
            "gross_sales",
            "discount",
            "detail_quantity",
            "average_daily_sales",
        )
        if column in table
    ]
    table[numeric_columns] = table[numeric_columns].round(0)
    hover_columns = [
        column
        for column in ("gross_sales", "share", "rank", "sales_days")
        if column in table
    ]
    figure = px.bar(
        table.head(30),
        x="net_sales",
        y=level,
        orientation="h",
        color="net_sales",
        hover_data=hover_columns,
        labels={"net_sales": "Net Sales", level: level.title()},
    )
    figure.update_layout(yaxis={"categoryorder": "total ascending"})
    return _layout(figure, f"Net Sales by {level.title()}"), table


def store_scorecard(
    daily: pd.DataFrame,
    sales_only: bool = False,
    color_rules: dict[str, KPIColorRule] | None = None,
) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    aggregations = {"net_sales": "sum"}
    optional_columns = (
        ("gross_sales",)
        if sales_only
        else ("gross_sales", "target", "footfall", "nob", "quantity")
    )
    for column in optional_columns:
        if column in daily:
            aggregations[column] = "sum"
    table = daily.groupby(["store_code", "store_name"], as_index=False).agg(aggregations)
    table["achievement"] = table["net_sales"] / table.get("target", np.nan)
    table["conversion"] = table.get("nob", np.nan) / table.get("footfall", np.nan)
    table["atv"] = table["net_sales"] / table.get("nob", np.nan)
    table["rpv"] = table["net_sales"] / table.get("footfall", np.nan)
    table["basket_size"] = table.get("quantity", np.nan) / table.get("nob", np.nan)
    table["discount_pct"] = (
        (table.get("gross_sales", np.nan) - table["net_sales"])
        / table.get("gross_sales", np.nan)
    )
    table["rank"] = table["net_sales"].rank(method="dense", ascending=False).astype("Int64")
    active_rules = (
        DEFAULT_KPI_COLOR_RULES if color_rules is None else color_rules
    )
    for metric in (
        "atv",
        "rpv",
        "basket_size",
        "conversion",
        "achievement",
    ):
        if metric not in table or metric not in active_rules:
            continue
        table[f"{metric}_color_code"] = table[metric].map(
            lambda value, metric=metric: status_for(
                metric,
                None if pd.isna(value) else float(value),
                active_rules,
            )
        )
    return table.sort_values("rank")


def forecast_chart(result: ForecastResult) -> tuple[go.Figure, pd.DataFrame]:
    history_dates = pd.to_datetime(result.history["date"]).dt.strftime(
        "%Y-%m-%d"
    )
    validation_dates = pd.to_datetime(result.validation["date"]).dt.strftime(
        "%Y-%m-%d"
    )
    future_dates = pd.to_datetime(result.future["date"]).dt.strftime(
        "%Y-%m-%d"
    )
    figure = go.Figure()
    figure.add_scatter(
        x=history_dates,
        y=result.history["actual"],
        name="Historical actual",
        line_color=COLORS["blue"],
        hovertemplate="%{x|%d-%m-%Y}<br>₹%{y:,.0f}<extra>Actual</extra>",
    )
    figure.add_scatter(
        x=validation_dates,
        y=result.validation["prediction"],
        name="Validation prediction",
        line={"color": COLORS["gold"], "dash": "dot"},
        hovertemplate="%{x|%d-%m-%Y}<br>₹%{y:,.0f}<extra>Validation</extra>",
    )
    figure.add_scatter(
        x=future_dates,
        y=result.future["forecast"],
        name="Future forecast",
        line_color=COLORS["green"],
        hovertemplate="%{x|%d-%m-%Y}<br>₹%{y:,.0f}<extra>Forecast</extra>",
    )
    figure.add_scatter(
        x=pd.concat([future_dates, future_dates.iloc[::-1]]),
        y=pd.concat([result.future["upper"], result.future["lower"].iloc[::-1]]),
        fill="toself",
        fillcolor="rgba(46,139,87,0.15)",
        line={"color": "rgba(0,0,0,0)"},
        name="Approx. 95% error band",
    )
    figure.add_vline(
        x=pd.Timestamp(result.training_end).strftime("%Y-%m-%d"),
        line_dash="dash",
        annotation_text="Forecast start",
    )
    table = result.future.copy()
    table[["forecast", "lower", "upper"]] = table[
        ["forecast", "lower", "upper"]
    ].round(0)
    return _layout(figure, f"Actual vs Predicted Sales — {result.model_name}"), table
