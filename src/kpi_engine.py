"""Central KPI calculations with explicit availability metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from config.kpi_thresholds import (
    DEFAULT_KPI_COLOR_RULES,
    KPIColorRule,
    status_for,
)
from src.formatting import count, currency, percentage

KPI_FORMULAS = {
    "net_sales": "Σ SALE; Σ NET_AMOUNT under hierarchy filters",
    "gross_sales": "Σ GROSS_AMOUNT",
    "footfall": "Σ FOOTFALL",
    "transactions": "Σ NOB",
    "atv": "Net Sales ÷ NOB",
    "rpv": "Net Sales ÷ Footfall",
    "basket_size": "Σ SUM_OF_BILL_QUANTITY ÷ NOB",
    "conversion": "NOB ÷ Footfall",
    "achievement": "Net Sales ÷ Target",
    "discount": "Gross Sales − Net Sales",
    "discount_pct": "Discount ÷ Gross Sales",
    "quantity": "Σ SUM_OF_BILL_QUANTITY",
    "target": "Σ SALE_TARGET",
}


def safe_divide(numerator: float | int | None, denominator: float | int | None) -> float | None:
    """Return a finite quotient or None for missing/zero denominators."""
    if numerator is None or denominator is None:
        return None
    try:
        if pd.isna(numerator) or pd.isna(denominator) or float(denominator) == 0:
            return None
        value = float(numerator) / float(denominator)
        return value if np.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _sum_if_available(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame or frame[column].notna().sum() == 0:
        return None
    return float(frame[column].sum(min_count=1))


def _distinct_or_sum_transactions(frame: pd.DataFrame) -> tuple[float | None, str]:
    if "transaction_id" in frame and frame["transaction_id"].notna().any():
        return float(frame["transaction_id"].nunique()), "distinct transaction IDs"
    value = _sum_if_available(frame, "nob")
    return value, "pre-aggregated NOB" if value is not None else "unavailable"


def calculate_kpis(
    daily: pd.DataFrame,
    detail: pd.DataFrame | None = None,
    hierarchy_filtered: bool = False,
    color_rules: Mapping[str, KPIColorRule] | None = None,
) -> dict[str, dict[str, Any]]:
    """Calculate all supported KPIs once for cards, tables, charts, and PDF."""
    detail = detail if detail is not None else pd.DataFrame()
    sales_fact = detail if hierarchy_filtered else daily
    net_sales = _sum_if_available(sales_fact, "net_sales")
    gross_sales = _sum_if_available(sales_fact, "gross_sales")
    # KPI quantity is store-day SUM_OF_BILL_QUANTITY only. Detail
    # BILL_QUANTITY contains returns and is not a KPI fallback.
    quantity = None if hierarchy_filtered else _sum_if_available(daily, "quantity")
    discount = None
    gross_source = "workbook gross amount"
    if (
        "gross_sales_source" in sales_fact
        and sales_fact["gross_sales_source"].notna().any()
    ):
        gross_source = str(sales_fact["gross_sales_source"].dropna().iloc[0])
    if gross_sales is None and net_sales is not None:
        explicit_discount = _sum_if_available(sales_fact, "discount")
        if explicit_discount is not None:
            gross_sales = net_sales + explicit_discount
            gross_source = "derived: net sales + discount"
    if gross_sales is not None and net_sales is not None:
        discount = gross_sales - net_sales

    if hierarchy_filtered:
        footfall = transactions = target = None
        transaction_source = "not attributable to hierarchy"
        atv = rpv = basket = conversion = achievement = None
    else:
        has_transaction_ids = (
            "transaction_id" in daily and daily["transaction_id"].notna().any()
        )
        transaction_source = (
            "distinct transaction IDs" if has_transaction_ids else "pre-aggregated NOB"
        )
        nob_mask = (
            pd.Series(True, index=daily.index)
            if has_transaction_ids
            else (
                daily["nob"].notna() & daily["nob"].gt(0)
                if "nob" in daily
                else pd.Series(False, index=daily.index)
            )
        )
        footfall_mask = (
            daily["footfall"].notna() & daily["footfall"].gt(0)
            if "footfall" in daily
            else pd.Series(False, index=daily.index)
        )
        conversion_mask = nob_mask & footfall_mask
        target_mask = (
            daily["target"].notna() & daily["target"].gt(0)
            if "target" in daily
            else pd.Series(False, index=daily.index)
        )
        transactions = (
            float(daily["transaction_id"].nunique())
            if has_transaction_ids
            else _sum_if_available(daily.loc[nob_mask], "nob")
        )
        footfall = _sum_if_available(daily.loc[footfall_mask], "footfall")
        target = _sum_if_available(daily.loc[target_mask], "target")
        atv = safe_divide(
            _sum_if_available(daily.loc[nob_mask], "net_sales"), transactions
        )
        rpv = safe_divide(
            _sum_if_available(daily.loc[footfall_mask], "net_sales"), footfall
        )
        basket = safe_divide(
            _sum_if_available(daily.loc[nob_mask], "quantity"), transactions
        )
        conversion_transactions = (
            float(daily.loc[conversion_mask, "transaction_id"].nunique())
            if has_transaction_ids and conversion_mask.any()
            else _sum_if_available(daily.loc[conversion_mask], "nob")
        )
        conversion = safe_divide(
            conversion_transactions,
            _sum_if_available(daily.loc[conversion_mask], "footfall"),
        )
        achievement = safe_divide(
            _sum_if_available(daily.loc[target_mask], "net_sales"), target
        )
    discount_pct = safe_divide(discount, gross_sales)

    reason = (
        "N/A — store-day footfall and bills cannot be attributed to division/section/department"
        if hierarchy_filtered
        else "N/A — Required source field not available"
    )

    active_rules = color_rules if color_rules is not None else DEFAULT_KPI_COLOR_RULES

    def item(
        key: str,
        value: float | None,
        source: str,
    ) -> dict[str, Any]:
        rule = active_rules.get(key)
        return {
            "value": value,
            "available": value is not None,
            "source": source,
            "status": status_for(key, value, active_rules),
            "color_rule": (
                rule.description
                if rule is not None
                else "No rule in COLOUR FORMATTING"
            ),
            "message": None if value is not None else reason,
        }

    results = {
        "net_sales": item(
            "net_sales",
            net_sales,
            "daily summary" if not hierarchy_filtered else "detail fact",
        ),
        "gross_sales": item("gross_sales", gross_sales, gross_source),
        "footfall": item("footfall", footfall, "store-day footfall"),
        "transactions": item("transactions", transactions, transaction_source),
        "atv": item("atv", atv, "net sales / NOB"),
        "rpv": item("rpv", rpv, "net sales / footfall"),
        "basket_size": item(
            "basket_size", basket, "SUM_OF_BILL_QUANTITY / NOB"
        ),
        "conversion": item("conversion", conversion, "NOB / footfall"),
        "achievement": item(
            "achievement", achievement, "net sales / CitiMart target"
        ),
        "discount": item("discount", discount, "gross sales - net sales"),
        "discount_pct": item(
            "discount_pct", discount_pct, "discount / gross sales"
        ),
        "quantity": item(
            "quantity", quantity, "store-day SUM_OF_BILL_QUANTITY"
        ),
        "target": item("target", target, "CitiMart manual SALE_TARGET"),
    }
    for key, payload in results.items():
        payload["formula"] = KPI_FORMULAS[key]
    return results


def kpi_table(
    current: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Build a comparison table without inventing missing values."""
    labels = {
        "net_sales": "Total Net Sales",
        "gross_sales": "Total Gross Sales",
        "footfall": "Total Footfall",
        "transactions": "Number of Bills",
        "atv": "Average Transaction Value",
        "rpv": "Revenue per Visitor",
        "basket_size": "Basket Size",
        "conversion": "Conversion",
        "achievement": "Target Achievement",
        "target": "Sales Target",
        "quantity": "Total Units Sold",
    }
    rows = []
    previous = previous or {}
    for key, label in labels.items():
        if not current.get(key, {}).get("available", False):
            continue
        current_value = current[key]["value"]
        previous_value = previous.get(key, {}).get("value")
        variance = (
            current_value - previous_value
            if current_value is not None and previous_value is not None
            else None
        )
        if key in {"conversion", "achievement"}:
            render = percentage
        elif key in {"net_sales", "gross_sales", "atv", "rpv", "target"}:
            render = currency
        else:
            render = count
        rows.append(
            {
                "KPI": label,
                "Formula": current[key]["formula"],
                "Current value": render(current_value),
                "Previous-period value": render(previous_value),
                "Absolute variance": render(variance),
                "Percentage variance": percentage(
                    safe_divide(variance, abs(previous_value))
                    if variance is not None
                    else None
                ),
                "Color code": current[key]["status"],
                "Color rule": current[key]["color_rule"],
                "Source": current[key]["source"],
            }
        )
    return pd.DataFrame(rows)
