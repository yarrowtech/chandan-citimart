"""Validation and preparation of user-uploaded XLSX forecasting data."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Sequence

import pandas as pd

from config.settings import STORE_NAMES
from src.data_cleaner import parse_dates, to_numeric
from src.schema_detector import (
    detect_columns,
    normalize_name,
    sheet_role,
    store_code_for_sheet,
)

MAX_FORECAST_UPLOAD_BYTES = 50 * 1024 * 1024
FORECAST_DIMENSIONS = ("division", "section", "department")


@dataclass
class UploadedForecastWorkbook:
    """Canonical rows discovered across usable worksheets."""

    rows: pd.DataFrame
    source_name: str
    usable_sheets: list[str]
    skipped_sheets: list[str]
    warnings: list[str]


@dataclass
class ForecastHistory:
    """Daily history selected from an uploaded workbook for model training."""

    daily: pd.DataFrame
    source_name: str
    sheets_used: list[str]
    source_rows: int
    warnings: list[str]
    filters_applied: bool

    @property
    def date_min(self) -> pd.Timestamp:
        return pd.Timestamp(self.daily["date"].min())

    @property
    def date_max(self) -> pd.Timestamp:
        return pd.Timestamp(self.daily["date"].max())


def _clean_text(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    return values.mask(values.str.casefold().isin({"", "nan", "none", "null"}))


def _store_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for code, name in STORE_NAMES.items():
        lookup[normalize_name(code)] = code
        lookup[normalize_name(name)] = code
    return lookup


def _canonical_sheet_rows(raw: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    mapping = detect_columns(raw.columns)
    if "date" not in mapping or "net_sales" not in mapping:
        return pd.DataFrame()

    selected_fields = [
        field
        for field in ("date", "net_sales", "store", *FORECAST_DIMENSIONS)
        if field in mapping
    ]
    rename_map = {mapping[field]: field for field in selected_fields}
    frame = raw[list(rename_map)].rename(columns=rename_map).copy()
    frame["date"] = parse_dates(frame["date"])
    frame["net_sales"] = to_numeric(frame["net_sales"])
    frame = frame.dropna(subset=["date", "net_sales"]).copy()
    if frame.empty:
        return frame

    for dimension in ("store", *FORECAST_DIMENSIONS):
        if dimension in frame:
            frame[dimension] = _clean_text(frame[dimension])

    sheet_store_code = store_code_for_sheet(sheet_name)
    if sheet_store_code:
        frame["store_code"] = sheet_store_code
        frame["store_name"] = STORE_NAMES[sheet_store_code]
    elif "store" in frame:
        lookup = _store_lookup()
        frame["store_code"] = frame["store"].map(
            lambda value: lookup.get(normalize_name(value)) if pd.notna(value) else None
        )
        frame["store_name"] = frame["store"]
    else:
        frame["store_code"] = pd.NA
        frame["store_name"] = pd.NA

    frame["source_worksheet"] = sheet_name
    frame["fact_role"] = sheet_role(sheet_name) or "generic"
    return frame


def load_uploaded_forecast_workbook(
    file_bytes: bytes,
    source_name: str,
) -> UploadedForecastWorkbook:
    """Read usable DATE + SALE/NET SALES rows from an uploaded XLSX workbook."""
    if not file_bytes:
        raise ValueError("The uploaded workbook is empty.")
    if len(file_bytes) > MAX_FORECAST_UPLOAD_BYTES:
        raise ValueError("The uploaded workbook exceeds the 50 MB forecasting limit.")
    if Path(source_name).suffix.casefold() != ".xlsx":
        raise ValueError("Upload an .xlsx workbook for forecasting.")

    try:
        workbook = pd.ExcelFile(BytesIO(file_bytes), engine="openpyxl")
    except Exception as exc:
        raise ValueError(f"The uploaded XLSX workbook could not be opened: {exc}") from exc

    usable_parts: list[pd.DataFrame] = []
    usable_sheets: list[str] = []
    skipped_sheets: list[str] = []
    warnings: list[str] = []
    try:
        for sheet_name in workbook.sheet_names:
            try:
                raw = pd.read_excel(workbook, sheet_name=sheet_name)
                frame = _canonical_sheet_rows(raw, sheet_name)
            except Exception as exc:
                skipped_sheets.append(sheet_name)
                warnings.append(f"{sheet_name}: could not be read ({exc}).")
                continue
            if frame.empty:
                skipped_sheets.append(sheet_name)
                warnings.append(
                    f"{sheet_name}: skipped because usable DATE and SALE/NET SALES "
                    "columns were not found."
                )
                continue
            usable_sheets.append(sheet_name)
            usable_parts.append(frame)
    finally:
        workbook.close()

    if not usable_parts:
        raise ValueError(
            "No forecast history was found. At least one worksheet must contain a "
            "DATE column and a SALE, NET SALES, NET AMOUNT, SALES AMOUNT, or REVENUE column."
        )

    rows = pd.concat(usable_parts, ignore_index=True, sort=False)
    if rows["date"].nunique() < 2:
        raise ValueError("The uploaded workbook contains fewer than two usable sales dates.")

    return UploadedForecastWorkbook(
        rows=rows,
        source_name=source_name,
        usable_sheets=usable_sheets,
        skipped_sheets=skipped_sheets,
        warnings=warnings,
    )


def _preferred_fact_rows(
    rows: pd.DataFrame,
    hierarchy_filter_active: bool,
) -> pd.DataFrame:
    """Avoid double counting paired detail/daily sheets."""
    parts: list[pd.DataFrame] = []
    recognized = rows["fact_role"].isin(["detail", "daily"])
    generic = rows.loc[~recognized]
    if not generic.empty:
        parts.append(generic)

    recognized_rows = rows.loc[recognized]
    if not recognized_rows.empty:
        group_field = recognized_rows["store_code"].fillna(
            recognized_rows["source_worksheet"]
        )
        for _, group in recognized_rows.groupby(group_field, sort=False):
            preferred_role = "detail" if hierarchy_filter_active else "daily"
            preferred = group.loc[group["fact_role"].eq(preferred_role)]
            if preferred.empty:
                fallback_role = "daily" if preferred_role == "detail" else "detail"
                preferred = group.loc[group["fact_role"].eq(fallback_role)]
            parts.append(preferred)

    return pd.concat(parts, ignore_index=True, sort=False) if parts else rows.iloc[0:0].copy()


def _filter_dimension(
    rows: pd.DataFrame,
    column: str,
    selected_values: Sequence[str] | None,
) -> pd.DataFrame:
    if not selected_values:
        return rows
    if column not in rows or rows[column].notna().sum() == 0:
        raise ValueError(
            f"The current {column.upper()} filter cannot be applied because the uploaded "
            f"forecast data has no usable {column.upper()} column."
        )
    selected = {normalize_name(value) for value in selected_values}
    normalized = rows[column].map(
        lambda value: normalize_name(value) if pd.notna(value) else ""
    )
    return rows.loc[normalized.isin(selected)]


def prepare_uploaded_forecast_history(
    workbook: UploadedForecastWorkbook,
    *,
    apply_view_filters: bool = False,
    start_date: object | None = None,
    end_date: object | None = None,
    selected_store_codes: Sequence[str] | None = None,
    divisions: Sequence[str] | None = None,
    sections: Sequence[str] | None = None,
    departments: Sequence[str] | None = None,
) -> ForecastHistory:
    """Select, optionally filter, and aggregate uploaded rows to daily sales."""
    hierarchy_filter_active = any((divisions, sections, departments))
    rows = _preferred_fact_rows(workbook.rows, hierarchy_filter_active and apply_view_filters)
    warnings = list(workbook.warnings)

    if apply_view_filters:
        if start_date is not None:
            rows = rows.loc[rows["date"].ge(pd.Timestamp(start_date))]
        if end_date is not None:
            rows = rows.loc[rows["date"].le(pd.Timestamp(end_date))]

        if selected_store_codes:
            if "store_code" not in rows or rows["store_code"].notna().sum() == 0:
                raise ValueError(
                    "The current STORE filter cannot be applied because the uploaded "
                    "forecast data has no recognizable store names or store-coded sheets."
                )
            rows = rows.loc[rows["store_code"].isin(selected_store_codes)]

        rows = _filter_dimension(rows, "division", divisions)
        rows = _filter_dimension(rows, "section", sections)
        rows = _filter_dimension(rows, "department", departments)

    if rows.empty:
        raise ValueError("No uploaded forecast rows remain after applying the selected scope.")

    source_rows = len(rows)
    daily = (
        rows.groupby("date", as_index=False, dropna=False)["net_sales"]
        .sum()
        .sort_values("date")
        .reset_index(drop=True)
    )
    if daily["date"].nunique() < 2:
        raise ValueError("The selected uploaded scope contains fewer than two sales dates.")

    sheets_used = sorted(rows["source_worksheet"].dropna().astype(str).unique())
    return ForecastHistory(
        daily=daily,
        source_name=workbook.source_name,
        sheets_used=sheets_used,
        source_rows=source_rows,
        warnings=warnings,
        filters_applied=apply_view_filters,
    )
