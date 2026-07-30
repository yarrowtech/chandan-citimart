"""Comparable-period and MTD-alignment helpers."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd


def previous_period_bounds(
    start_date: pd.Timestamp, end_date: pd.Timestamp
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the immediately preceding inclusive period of equal length."""
    duration = end_date.normalize() - start_date.normalize()
    previous_end = start_date.normalize() - timedelta(days=1)
    return previous_end - duration, previous_end


def is_partial_month(end_date: pd.Timestamp) -> bool:
    """Return True when the end date is before its calendar month end."""
    end_date = pd.Timestamp(end_date).normalize()
    return end_date < end_date + pd.offsets.MonthEnd(0)


def aligned_monthly_daily(frame: pd.DataFrame, value_column: str = "net_sales") -> pd.DataFrame:
    """Compare months only through the minimum observed day-of-month."""
    if frame.empty or value_column not in frame:
        return pd.DataFrame(columns=["year_month", "day", value_column])
    working = frame.dropna(subset=["date"]).copy()
    working["year_month"] = working["date"].dt.to_period("M").astype(str)
    working["day"] = working["date"].dt.day
    maximum_common_day = int(
        working.groupby("year_month")["day"].max().min()
    )
    return (
        working.loc[working["day"].le(maximum_common_day)]
        .groupby(["year_month", "day"], as_index=False)[value_column]
        .sum()
    )

