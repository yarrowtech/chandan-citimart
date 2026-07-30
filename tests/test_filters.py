from __future__ import annotations

from datetime import date

import pandas as pd

from src.filter_engine import (
    apply_detail_filters,
    calendar_period_options,
    dependent_options,
)
from src.charts import (
    conversion_percentage_chart,
    footfall_bills_chart,
    hierarchy_chart,
    sales_by_period,
    store_scorecard,
)
from src.formatting import dashboard_table


def test_filter_intersections(detail_fact) -> None:
    filtered = apply_detail_filters(
        detail_fact,
        ["NW"],
        date(2026, 1, 1),
        date(2026, 1, 2),
        divisions=["FMCG"],
        sections=["Food"],
        departments=["Grocery"],
    )
    assert len(filtered) == 2
    assert filtered["net_sales"].sum() == 1900


def test_no_data_filter_state(detail_fact) -> None:
    filtered = apply_detail_filters(
        detail_fact,
        ["NW"],
        date(2027, 1, 1),
        date(2027, 1, 2),
        divisions=["FMCG"],
        sections=["Food"],
        departments=["Grocery"],
    )
    assert filtered.empty


def test_calendar_week_and_month_filter_options() -> None:
    dates = pd.Series(
        pd.to_datetime(["2025-12-31", "2026-01-01", "2026-01-31", "2026-02-01"])
    )
    weeks = calendar_period_options(dates, "week")
    months = calendar_period_options(dates, "month")
    quarters = calendar_period_options(dates, "quarter")
    assert weeks[0].label == "29-12-2025 to 04-01-2026"
    assert weeks[0].start_date == date(2025, 12, 29)
    assert weeks[0].end_date == date(2026, 1, 4)
    assert [item.label for item in months] == [
        "December 2025",
        "January 2026",
        "February 2026",
    ]
    assert [item.label for item in quarters] == [
        "Q4 2025 (October to December)",
        "Q1 2026 (January to March)",
    ]
    assert quarters[1].start_date == date(2026, 1, 1)
    assert quarters[1].end_date == date(2026, 3, 31)


def test_dependent_hierarchy_options(detail_fact) -> None:
    divisions, sections, departments = dependent_options(
        detail_fact,
        ["NW"],
        date(2026, 1, 1),
        date(2026, 1, 3),
        divisions=["Apparel"],
        sections=["Fashion"],
    )
    assert divisions == ["Apparel", "FMCG"]
    assert sections == ["Fashion"]
    assert departments == ["Mens"]


def test_division_sales_analysis(detail_fact) -> None:
    _, table = hierarchy_chart(detail_fact, "division")
    sales = table.set_index("division")["net_sales"].to_dict()
    assert sales == {"FMCG": 2700.0, "Apparel": 600.0}
    assert table["share"].sum() == 1
    assert table.set_index("division").loc["FMCG", "rank"] == 1
    assert table.set_index("division").loc["FMCG", "gross_sales"] == 3000
    assert table.set_index("division").loc["FMCG", "discount"] == 300
    assert table.set_index("division").loc["FMCG", "sales_days"] == 3


def test_division_filter_drives_sales_period_and_scorecard(detail_fact) -> None:
    fmcg = apply_detail_filters(
        detail_fact,
        ["NW", "CHW"],
        date(2026, 1, 1),
        date(2026, 1, 3),
        divisions=["FMCG"],
    )
    _, monthly = sales_by_period(fmcg, "Month")
    assert monthly["net_sales"].sum() == 2700
    scorecard = store_scorecard(fmcg, sales_only=True)
    assert scorecard["net_sales"].sum() == 2700
    assert "quantity" not in scorecard
    assert "footfall" not in scorecard


def test_customer_section_has_two_charts_and_one_shared_table(daily_fact) -> None:
    footfall_chart, footfall_table = footfall_bills_chart(daily_fact)
    conversion_chart, conversion_table = conversion_percentage_chart(daily_fact)
    assert footfall_chart.layout.title.text == "Footfall vs NoB"
    assert conversion_chart.layout.title.text == "Conversion Percentage"
    assert len(footfall_chart.data) == 2
    assert len(conversion_chart.data) == 1
    assert footfall_table.equals(conversion_table)
    assert {
        "footfall",
        "nob",
        "conversion_percentage",
    }.issubset(footfall_table.columns)


def test_store_scorecard_colors_all_governed_kpis(daily_fact) -> None:
    scorecard = store_scorecard(daily_fact)
    assert {
        "atv_color_code",
        "rpv_color_code",
        "basket_size_color_code",
        "conversion_color_code",
        "achievement_color_code",
    }.issubset(scorecard.columns)
    displayed = dashboard_table(scorecard)
    assert displayed["atv_color_code"].str.len().gt(0).all()


def test_dashboard_table_drops_columns_that_are_entirely_na() -> None:
    displayed = dashboard_table(
        pd.DataFrame(
            {
                "supported": [1, 2],
                "empty": [pd.NA, pd.NA],
                "sentinel": ["N/A", "n/a"],
            }
        )
    )
    assert displayed.columns.tolist() == ["supported"]


def test_calendar_quarters_and_dashboard_date_format(daily_fact) -> None:
    _, quarterly = sales_by_period(daily_fact, "Quarter")
    assert quarterly["Period"].tolist() == ["Q1 2026"]
    _, monthly = sales_by_period(daily_fact, "Month")
    assert monthly["Period"].tolist() == ["January 2026"]
    _, yearly = sales_by_period(daily_fact, "Year")
    assert yearly["Period"].tolist() == ["2026"]
    _, weekly = sales_by_period(daily_fact, "Week")
    assert weekly["Period"].iloc[0] == "29-12-2025 to 04-01-2026"
    displayed = dashboard_table(daily_fact[["date", "net_sales"]].head(1))
    assert displayed.loc[0, "date"] == "01-01-2026"
    assert "." not in str(displayed.loc[0, "net_sales"])
    color_codes = dashboard_table(
        pd.DataFrame({"Color code": ["Red", "Green", "Yellow", "N/A"]})
    )
    assert color_codes["Color code"].tolist() == ["🔴", "🟢", "🟡", "⚪"]
