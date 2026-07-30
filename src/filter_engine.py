"""Filter intersection logic shared by the dashboard and tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class FilterState:
    stores: tuple[str, ...]
    start_date: date
    end_date: date
    divisions: tuple[str, ...] = field(default_factory=tuple)
    sections: tuple[str, ...] = field(default_factory=tuple)
    departments: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DatePeriodOption:
    """A selectable calendar period with inclusive date bounds."""

    label: str
    start_date: date
    end_date: date


def calendar_period_options(
    dates: pd.Series,
    period: str,
) -> list[DatePeriodOption]:
    """Return sorted calendar week or month options present in the data."""
    parsed = pd.to_datetime(dates, errors="coerce").dropna().drop_duplicates()
    if parsed.empty:
        return []
    if period == "week":
        starts = (
            parsed - pd.to_timedelta(parsed.dt.dayofweek, unit="D")
        ).dt.normalize()
        ends = starts.map(lambda value: value + pd.DateOffset(days=6))
        bounds = pd.DataFrame(
            {
                "start": starts,
                "end": ends,
            }
        ).drop_duplicates()
        bounds = bounds.sort_values("start")
        return [
            DatePeriodOption(
                label=f"{row.start:%d-%m-%Y} to {row.end:%d-%m-%Y}",
                start_date=row.start.date(),
                end_date=row.end.date(),
            )
            for row in bounds.itertuples(index=False)
        ]
    if period == "month":
        periods = sorted(parsed.dt.to_period("M").unique())
        return [
            DatePeriodOption(
                label=item.start_time.strftime("%B %Y"),
                start_date=item.start_time.date(),
                end_date=item.end_time.date(),
            )
            for item in periods
        ]
    if period == "quarter":
        periods = sorted(parsed.dt.to_period("Q-DEC").unique())
        return [
            DatePeriodOption(
                label=(
                    f"Q{item.quarter} {item.year} "
                    f"({item.start_time:%B} to {item.end_time:%B})"
                ),
                start_date=item.start_time.date(),
                end_date=item.end_time.date(),
            )
            for item in periods
        ]
    raise ValueError("period must be 'week', 'month', or 'quarter'")


def clean_options(series: pd.Series) -> list[str]:
    """Return stable, nonblank, case-insensitively sorted filter values."""
    values = (
        series.dropna().astype(str).str.strip().loc[lambda item: item.ne("")].unique().tolist()
    )
    return sorted(values, key=str.casefold)


def apply_base_filters(
    frame: pd.DataFrame,
    stores: list[str] | tuple[str, ...],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Apply store and inclusive date filters without mutating the source."""
    if frame.empty or not stores or "date" not in frame:
        return frame.iloc[0:0].copy()
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    mask = (
        frame["store_code"].isin(stores)
        & frame["date"].ge(start)
        & frame["date"].le(end)
    )
    return frame.loc[mask].copy()


def apply_detail_filters(
    frame: pd.DataFrame,
    stores: list[str] | tuple[str, ...],
    start_date: date,
    end_date: date,
    divisions: list[str] | tuple[str, ...] | None = None,
    sections: list[str] | tuple[str, ...] | None = None,
    departments: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Apply intersecting hierarchy filters to the detail fact."""
    result = apply_base_filters(frame, stores, start_date, end_date)
    if divisions is not None and "division" in result:
        if not divisions:
            return result.iloc[0:0].copy()
        result = result[result["division"].isin(divisions)]
    if sections is not None and "section" in result:
        if not sections:
            return result.iloc[0:0].copy()
        result = result[result["section"].isin(sections)]
    if departments is not None and "department" in result:
        if not departments:
            return result.iloc[0:0].copy()
        result = result[result["department"].isin(departments)]
    return result.copy()


def dependent_options(
    detail: pd.DataFrame,
    stores: list[str] | tuple[str, ...],
    start_date: date,
    end_date: date,
    divisions: list[str] | tuple[str, ...] | None = None,
    sections: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Return dependent division, section, and department filter options."""
    base = apply_base_filters(detail, stores, start_date, end_date)
    division_options = clean_options(base["division"]) if "division" in base else []
    if divisions is not None and "division" in base:
        base = base[base["division"].isin(divisions)]
    section_options = clean_options(base["section"]) if "section" in base else []
    if sections is not None and "section" in base:
        base = base[base["section"].isin(sections)]
    department_options = clean_options(base["department"]) if "department" in base else []
    return division_options, section_options, department_options
