"""Indian-number, currency, percentage, and download formatting."""

from __future__ import annotations

import math
import re

import pandas as pd

from config.settings import CURRENCY_SYMBOL


def indian_number(value: float, decimals: int = 0) -> str:
    """Format a number using Indian digit grouping."""
    if value is None or pd.isna(value):
        return "N/A"
    sign = "-" if value < 0 else ""
    absolute = abs(float(value))
    rendered = f"{absolute:.{decimals}f}"
    integer, dot, fraction = rendered.partition(".")
    if len(integer) > 3:
        last = integer[-3:]
        leading = integer[:-3]
        groups = []
        while leading:
            groups.insert(0, leading[-2:])
            leading = leading[:-2]
        integer = ",".join(groups + [last])
    return f"{sign}{integer}{dot}{fraction}" if decimals else f"{sign}{integer}"


def currency(value: float | None, decimals: int = 0) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{CURRENCY_SYMBOL}{indian_number(value, decimals)}"


def percentage(value: float | None, decimals: int = 0) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{value * 100:.{decimals}f}%"


def count(value: float | None, decimals: int = 0) -> str:
    return "N/A" if value is None or pd.isna(value) else indian_number(value, decimals)


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "report"


PERCENTAGE_COLUMNS = {
    "achievement",
    "achievement_percentage",
    "conversion",
    "conversion_percentage",
    "discount_pct",
    "discount_percentage",
    "percentage_variance",
    "share",
    "stage_conversion",
    "mape",
    "wape",
    "r²",
}

CURRENCY_COLUMNS = {
    "net_sales",
    "gross_sales",
    "sales",
    "sale",
    "target",
    "discount",
    "detail_net_sales",
    "detail_gross_sales",
    "sales_reconciliation_variance",
    "atv",
    "rpv",
    "mae",
    "rmse",
    "actual",
    "prediction",
    "forecast",
    "lower",
    "upper",
    "change",
    "current_value",
    "previous_period_value",
    "absolute_variance",
}

STATUS_COLUMNS = {
    "status",
    "color_code",
    "conversion_status",
    "conversion_color_code",
}

STATUS_COLOR_CODES = {
    "Red": "🔴",
    "Green": "🟢",
    "Yellow": "🟡",
    "Neutral": "🔵",
    "N/A": "⚪",
}


def status_color_code(value: object) -> str:
    """Convert an internal status label to a user-facing color indicator."""
    return STATUS_COLOR_CODES.get(str(value), "⚪")


def drop_unavailable_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove fields whose values are entirely empty or N/A sentinels."""
    if frame.empty:
        return frame.copy()
    keep: list[object] = []
    sentinels = {"", "n/a", "na", "nan", "none", "null"}
    for column in frame.columns:
        series = frame[column]
        populated = series.notna()
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            normalized = series.astype("string").str.strip().str.casefold()
            populated &= ~normalized.isin(sentinels)
        if populated.any():
            keep.append(column)
    return frame.loc[:, keep].copy()


def dashboard_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Format dashboard/PDF tables with integer values, percentages, and DD-MM-YYYY dates."""
    result = drop_unavailable_columns(frame)
    for column in result.columns:
        key = normalize_display_column(column)
        series = result[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            result[column] = series.dt.strftime("%d-%m-%Y").fillna("N/A")
        elif (
            key in STATUS_COLUMNS
            or key.endswith("_color_code")
            or key.endswith("_status")
        ):
            result[column] = series.map(status_color_code)
        elif key == "year_month":
            parsed = pd.to_datetime(series.astype("string") + "-01", errors="coerce")
            result[column] = parsed.dt.strftime("%d-%m-%Y").fillna(
                series.astype("string")
            )
        elif key in PERCENTAGE_COLUMNS and pd.api.types.is_numeric_dtype(series):
            result[column] = series.map(
                lambda value: percentage(value) if pd.notna(value) else "N/A"
            )
        elif key in CURRENCY_COLUMNS and pd.api.types.is_numeric_dtype(series):
            result[column] = series.map(
                lambda value: currency(round(float(value))) if pd.notna(value) else "N/A"
            )
        elif pd.api.types.is_numeric_dtype(series):
            result[column] = pd.to_numeric(series, errors="coerce").round(0).astype("Int64")
    return result


def normalize_display_column(value: object) -> str:
    return re.sub(r"[^a-z0-9²]+", "_", str(value).strip().casefold()).strip("_")
