"""Cached-friendly workbook ingestion into separate detail and store-day facts."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from config.kpi_thresholds import KPIColorRule
from config.settings import STORE_NAMES
from src.color_rules import is_color_rule_sheet, load_color_rules
from src.data_cleaner import clean_frame
from src.schema_detector import SheetInspection, inspect_workbook

LOGGER = logging.getLogger(__name__)


@dataclass
class WorkbookData:
    detail: pd.DataFrame
    daily: pd.DataFrame
    inspections: list[dict[str, object]]
    sheet_quality: pd.DataFrame
    loaded_sheets: list[str]
    skipped_sheets: list[str]
    skipped_stores: list[str]
    warnings: list[str]
    workbook_path: Path
    workbook_mtime: float
    kpi_color_rules: dict[str, KPIColorRule]
    color_rule_source: str | None

    @property
    def available_stores(self) -> list[str]:
        values = set(self.detail.get("store_code", pd.Series(dtype=str)).dropna())
        values.update(self.daily.get("store_code", pd.Series(dtype=str)).dropna())
        return [code for code in STORE_NAMES if code in values]


def _has_usable_data(frame: pd.DataFrame, role: str) -> bool:
    if frame.empty or "date" not in frame or frame["date"].notna().sum() == 0:
        return False
    if role == "detail":
        return "net_sales" in frame and frame["net_sales"].notna().any()
    return any(
        column in frame and frame[column].notna().any()
        for column in ("net_sales", "footfall", "nob", "quantity")
    )


def _prepare_daily(
    daily_parts: list[pd.DataFrame], detail: pd.DataFrame, warnings: list[str]
) -> pd.DataFrame:
    daily = pd.concat(daily_parts, ignore_index=True, sort=False) if daily_parts else pd.DataFrame()
    if not detail.empty:
        detail_daily = (
            detail.groupby(["store_code", "store_name", "date"], as_index=False, dropna=False)
            .agg(
                detail_net_sales=("net_sales", "sum"),
                detail_gross_sales=("gross_sales", "sum"),
            )
            if "gross_sales" in detail.columns
            else detail.groupby(["store_code", "store_name", "date"], as_index=False)
            .agg(detail_net_sales=("net_sales", "sum"))
        )
    else:
        detail_daily = pd.DataFrame()

    if daily.empty:
        daily = detail_daily.rename(
            columns={
                "detail_net_sales": "net_sales",
                "detail_gross_sales": "gross_sales",
            }
        )
        daily["quantity"] = np.nan
        daily["sales_source"] = "detail fallback"
        return daily

    # A one-to-one store/date merge is safe and explicitly validated.
    if daily.duplicated(["store_code", "date"]).any():
        warnings.append("Daily sheets contain duplicate store/date rows; they were aggregated safely.")
        aggregations = {
            column: "sum"
            for column in ("net_sales", "target", "quantity", "footfall", "nob")
            if column in daily
        }
        for column in ("atv", "rpv", "conversion", "achievement", "basket_size"):
            if column in daily:
                aggregations[column] = "mean"
        daily = daily.groupby(["store_code", "store_name", "date"], as_index=False).agg(aggregations)

    if not detail_daily.empty:
        daily = daily.merge(
            detail_daily,
            on=["store_code", "store_name", "date"],
            how="outer",
            validate="one_to_one",
        )

    if "net_sales" not in daily:
        daily["net_sales"] = np.nan
    daily["sales_source"] = np.where(
        daily["net_sales"].notna() & daily["net_sales"].ne(0),
        "daily summary",
        "detail fallback",
    )
    daily["net_sales"] = daily["net_sales"].where(
        daily["net_sales"].notna() & daily["net_sales"].ne(0),
        daily.get("detail_net_sales"),
    )
    if {"detail_gross_sales", "detail_net_sales"}.issubset(daily.columns):
        daily["detail_discount_gap"] = (
            daily["detail_gross_sales"] - daily["detail_net_sales"]
        )
        daily["gross_sales"] = daily["net_sales"] + daily["detail_discount_gap"]
        daily["gross_sales_source"] = "derived: summary net + detail gross/net gap"
    elif "gross_sales" not in daily:
        daily["gross_sales"] = daily.get("detail_gross_sales")
    if "quantity" not in daily:
        # Quantity KPIs must come exclusively from SUM_OF_BILL_QUANTITY in the
        # store-day summary sheets; never substitute line-level BILL_QUANTITY.
        daily["quantity"] = np.nan

    # Treat near-empty pre-aggregated operational columns as unavailable. This
    # converts HB2's two zero placeholders (among 212 dates) to N/A while keeping
    # valid all-zero closed days inside otherwise well-covered stores.
    operational = ("footfall", "nob", "atv", "rpv", "conversion", "achievement", "basket_size")
    for store_code, indices in daily.groupby("store_code").groups.items():
        for column in operational:
            if column not in daily:
                continue
            values = daily.loc[indices, column]
            if values.notna().mean() < 0.5 or values.dropna().abs().sum() == 0:
                daily.loc[indices, column] = np.nan
                warnings.append(
                    f"{STORE_NAMES[store_code]}: {column} is unavailable because the "
                    "store-day source is empty or only contains placeholder zeros."
                )

    # CitiMart's SALE_TARGET is the controlling source. Derive a fallback only for
    # older worksheets where a manual target is absent but achievement is present.
    if "target" not in daily:
        daily["target"] = np.nan
    manual_target = daily["target"].notna() & daily["target"].gt(0)
    daily["target_source"] = np.where(
        manual_target, "CitiMart manual SALE_TARGET", None
    )
    if "achievement" in daily:
        fallback_target = (
            ~manual_target
            & daily["achievement"].notna()
            & daily["achievement"].gt(0)
            & daily["net_sales"].notna()
        )
        daily.loc[fallback_target, "target"] = (
            daily.loc[fallback_target, "net_sales"]
            / daily.loc[fallback_target, "achievement"]
        )
        daily.loc[fallback_target, "target_source"] = (
            "derived fallback: sales / achievement"
        )

    # Recalculate achievement from the selected target so cards, charts, and
    # tables reconcile to CitiMart's manually supplied plan.
    valid_target = daily["target"].notna() & daily["target"].gt(0)
    daily["achievement"] = np.where(
        valid_target, daily["net_sales"] / daily["target"], np.nan
    )

    if {"detail_net_sales", "net_sales"}.issubset(daily.columns):
        comparable = daily["detail_net_sales"].notna() & daily["net_sales"].notna()
        daily["sales_reconciliation_variance"] = np.where(
            comparable, daily["detail_net_sales"] - daily["net_sales"], np.nan
        )
        material = comparable & (
            daily["sales_reconciliation_variance"].abs()
            > daily["net_sales"].abs().mul(0.01).clip(lower=1)
        )
        if material.any():
            warnings.append(
                f"{int(material.sum())} store-days differ by more than 1% between detail "
                "net sales and daily summary sales; overall KPIs use daily summary values."
            )
    return daily


def load_workbook_data(path: str | Path) -> WorkbookData:
    """Load all recognized sheets without modifying the source workbook."""
    workbook_path = Path(path)
    inspections = inspect_workbook(workbook_path)
    color_rules, color_rule_source, color_rule_warnings = load_color_rules(
        workbook_path
    )
    recognized_parts: list[tuple[str, str, str, pd.DataFrame]] = []
    quality_rows: list[dict[str, object]] = []
    loaded: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = list(color_rule_warnings)

    for inspection in inspections:
        if is_color_rule_sheet(inspection.name):
            continue
        if inspection.store_code is None or inspection.role is None:
            skipped.append(inspection.name)
            warnings.append(f"{inspection.name}: unrecognized store prefix or sheet role.")
            continue
        try:
            raw = pd.read_excel(workbook_path, sheet_name=inspection.name, engine="openpyxl")
            frame, quality = clean_frame(
                raw,
                inspection.mapping,
                inspection.store_code,
                inspection.name,
                inspection.role,
            )
        except Exception as exc:  # pragma: no cover - defensive UI path
            LOGGER.exception("Failed to load worksheet %s", inspection.name)
            skipped.append(inspection.name)
            warnings.append(f"{inspection.name}: load failed ({exc}).")
            continue

        quality_rows.append(
            {
                "worksheet": inspection.name,
                "store": STORE_NAMES[inspection.store_code],
                "role": inspection.role,
                **quality,
                "date_min": frame["date"].min() if "date" in frame else pd.NaT,
                "date_max": frame["date"].max() if "date" in frame else pd.NaT,
                "detected_columns": ", ".join(
                    f"{key} ← {value}" for key, value in inspection.mapping.items()
                ),
            }
        )
        if inspection.role == "detail":
            if "division" not in frame:
                warnings.append(
                    f"{inspection.name}: DIVISION was not detected; division analysis is unavailable."
                )
            elif frame["division"].notna().sum() == 0:
                warnings.append(
                    f"{inspection.name}: DIVISION contains no usable values."
                )
        if not _has_usable_data(frame, inspection.role):
            skipped.append(inspection.name)
            warnings.append(f"{inspection.name}: no usable {inspection.role} records.")
            continue
        recognized_parts.append(
            (inspection.name, inspection.store_code, inspection.role, frame)
        )

    # A store is reportable only when its pair supplies both usable sales detail
    # and meaningful store-day sales. This keeps incomplete HB1/HB2 out of KPI
    # totals while automatically enabling HB after valid HB2 sales are supplied.
    reportable_stores: set[str] = set()
    skipped_stores: list[str] = []
    for store_code in STORE_NAMES:
        store_parts = [part for part in recognized_parts if part[1] == store_code]
        if not store_parts:
            continue
        detail_ok = any(
            role == "detail"
            and "net_sales" in frame
            and frame["net_sales"].dropna().abs().sum() > 0
            for _, _, role, frame in store_parts
        )
        daily_ok = any(
            role == "daily"
            and "net_sales" in frame
            and frame["net_sales"].dropna().abs().sum() > 0
            for _, _, role, frame in store_parts
        )
        if detail_ok and daily_ok:
            reportable_stores.add(store_code)
        else:
            skipped_stores.append(store_code)
            warnings.append(
                f"{STORE_NAMES[store_code]} (store {store_code}) was skipped: "
                "both usable detail sales and store-day sales are required."
            )

    detail_parts: list[pd.DataFrame] = []
    daily_parts: list[pd.DataFrame] = []
    for sheet_name, store_code, role, frame in recognized_parts:
        if store_code in reportable_stores:
            loaded.append(sheet_name)
            (detail_parts if role == "detail" else daily_parts).append(frame)
        else:
            skipped.append(sheet_name)

    detail = pd.concat(detail_parts, ignore_index=True, sort=False) if detail_parts else pd.DataFrame()
    daily = _prepare_daily(daily_parts, detail, warnings)
    return WorkbookData(
        detail=detail,
        daily=daily,
        inspections=[asdict(item) for item in inspections],
        sheet_quality=pd.DataFrame(quality_rows),
        loaded_sheets=loaded,
        skipped_sheets=list(dict.fromkeys(skipped)),
        skipped_stores=skipped_stores,
        warnings=warnings,
        workbook_path=workbook_path,
        workbook_mtime=workbook_path.stat().st_mtime,
        kpi_color_rules=color_rules,
        color_rule_source=color_rule_source,
    )
