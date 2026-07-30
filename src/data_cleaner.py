"""Cleaning and standardisation functions for detail and daily facts."""

from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import pandas as pd

from config.settings import STORE_NAMES

NUMERIC_FIELDS = {
    "quantity",
    "gross_sales",
    "net_sales",
    "discount",
    "cost",
    "target",
    "footfall",
    "nob",
    "atv",
    "rpv",
    "conversion",
    "achievement",
    "basket_size",
}


def parse_dates(series: pd.Series) -> pd.Series:
    """Parse Excel serial dates, timestamps, and day-first text dates."""
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_mask = numeric.notna() & numeric.between(1, 100000)
    if numeric_mask.any():
        result.loc[numeric_mask] = pd.to_datetime(
            numeric.loc[numeric_mask], unit="D", origin="1899-12-30", errors="coerce"
        )
    other_mask = ~numeric_mask & series.notna()
    if other_mask.any():
        result.loc[other_mask] = pd.to_datetime(
            series.loc[other_mask], errors="coerce", dayfirst=True
        )
    return result.dt.normalize()


def to_numeric(series: pd.Series) -> pd.Series:
    """Convert accounting/currency text while preserving valid negatives."""
    cleaned = (
        series.astype("string")
        .str.strip()
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        .str.replace(r"[₹$£€,\s]", "", regex=True)
        .str.replace("%", "", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _strip_text(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    return values.mask(
        values.str.casefold().isin({"", "n/a", "na", "nan", "none", "null"})
    )


def add_date_dimensions(frame: pd.DataFrame) -> pd.DataFrame:
    """Add reusable calendar dimensions."""
    if "date" not in frame:
        return frame
    dates = frame["date"]
    iso = dates.dt.isocalendar()
    frame["day"] = dates.dt.day
    frame["day_name"] = dates.dt.day_name()
    frame["week"] = iso.week.astype("Int64")
    frame["month_number"] = dates.dt.month
    frame["month_name"] = dates.dt.month_name()
    frame["quarter"] = "Q" + dates.dt.quarter.astype("Int64").astype("string")
    frame["year"] = dates.dt.year.astype("Int64")
    frame["year_month"] = dates.dt.to_period("M").astype("string")
    frame["day_type"] = np.where(dates.dt.dayofweek >= 5, "Weekend", "Weekday")
    return frame


def clean_frame(
    raw: pd.DataFrame,
    mapping: dict[str, str],
    store_code: str,
    worksheet: str,
    role: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Clean a worksheet into a canonical fact table plus quality counters."""
    selected = {source: canonical for canonical, source in mapping.items()}
    frame = raw.rename(columns=selected).copy()
    keep = [column for column in selected.values() if column in frame.columns]
    frame = frame[keep]
    initial_rows = len(frame)

    for column in frame.select_dtypes(include=["object", "string"]).columns:
        frame[column] = _strip_text(frame[column])

    if "date" in frame:
        original_date_nonnull = frame["date"].notna().sum()
        frame["date"] = parse_dates(frame["date"])
        invalid_dates = int(original_date_nonnull - frame["date"].notna().sum())
    else:
        invalid_dates = initial_rows

    invalid_numeric = 0
    for column in NUMERIC_FIELDS.intersection(frame.columns):
        original_nonnull = frame[column].notna().sum()
        frame[column] = to_numeric(frame[column])
        invalid_numeric += int(original_nonnull - frame[column].notna().sum())

    # Percentages supplied as 47 or 47% are converted to fractions; 0.47 is retained.
    for column in ("conversion", "achievement"):
        if column in frame and frame[column].dropna().abs().median() > 3:
            frame[column] = frame[column] / 100.0

    text_columns = [
        column
        for column in (
            "section",
            "department",
            "division",
            "category",
            "subcategory",
            "brand",
            "product",
            "sku",
            "transaction_id",
        )
        if column in frame
    ]
    subtotal_pattern = re.compile(r"^(sub\s*total|grand\s*total|total)$", re.I)
    subtotal_mask = pd.Series(False, index=frame.index)
    for column in text_columns:
        subtotal_mask |= frame[column].fillna("").str.match(subtotal_pattern)

    metric_columns = list(NUMERIC_FIELDS.intersection(frame.columns))
    empty_metric_mask = (
        frame[metric_columns].isna().all(axis=1)
        if metric_columns
        else pd.Series(True, index=frame.index)
    )
    missing_date_mask = frame["date"].isna() if "date" in frame else pd.Series(True, index=frame.index)
    # Every valid fact row in the CitiMart workbook has a date. The red-font
    # calculation rows contain numeric totals but no date, so retaining rows only
    # when the date is valid removes those subtotals without relying on formatting
    # metadata that pandas does not preserve.
    removed_subtotal_rows = int((subtotal_mask | missing_date_mask).sum())
    frame = frame.loc[~subtotal_mask & ~missing_date_mask & ~empty_metric_mask].copy()

    frame["store_code"] = store_code
    frame["store_name"] = STORE_NAMES[store_code]
    frame["source_worksheet"] = worksheet
    frame["fact_role"] = role
    frame = add_date_dimensions(frame)

    quality = {
        "source_rows": initial_rows,
        "retained_rows": len(frame),
        "invalid_dates": invalid_dates,
        "invalid_numeric_values": invalid_numeric,
        "subtotal_or_undated_rows_removed": removed_subtotal_rows,
        "missing_dates": int(frame["date"].isna().sum()) if "date" in frame else len(frame),
        "missing_divisions": (
            int(frame["division"].isna().sum())
            if role == "detail" and "division" in frame
            else (len(frame) if role == "detail" else 0)
        ),
        "distinct_divisions": (
            int(frame["division"].nunique())
            if role == "detail" and "division" in frame
            else 0
        ),
        "negative_sales_rows": int(
            (frame["net_sales"] < 0).sum() if "net_sales" in frame else 0
        ),
        # Exact duplicate rows are reported, not removed: no transaction/SKU key exists
        # in the current detail sheets, so identical lines can be legitimate purchases.
        "potential_duplicate_rows": int(frame.duplicated().sum()),
    }
    return frame, quality
