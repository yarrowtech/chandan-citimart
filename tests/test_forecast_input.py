from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from src.forecast_input import (
    load_uploaded_forecast_workbook,
    prepare_uploaded_forecast_history,
)


def _workbook_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return buffer.getvalue()


def test_generic_uploaded_workbook_uses_date_and_sale_aliases() -> None:
    dates = pd.date_range("2026-01-01", periods=70, freq="D")
    payload = _workbook_bytes(
        {
            "Forecast History": pd.DataFrame(
                {"DATE": dates, "SALE": range(1000, 1070)}
            )
        }
    )

    workbook = load_uploaded_forecast_workbook(payload, "new_sales.xlsx")
    history = prepare_uploaded_forecast_history(workbook)

    assert history.sheets_used == ["Forecast History"]
    assert len(history.daily) == 70
    assert history.daily["net_sales"].iloc[0] == 1000
    assert history.date_min == pd.Timestamp("2026-01-01")
    assert history.date_max == pd.Timestamp("2026-03-11")


def test_paired_workbook_prefers_daily_sheet_without_hierarchy_filters() -> None:
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    detail = pd.DataFrame(
        {
            "DATE": dates.repeat(2),
            "DIVISION": ["FMCG", "APPAREL"] * len(dates),
            "NET_AMOUNT": [60, 40] * len(dates),
        }
    )
    daily = pd.DataFrame({"DATE": dates, "SALE": [100] * len(dates)})
    payload = _workbook_bytes({"NM1": detail, "NM2": daily})

    workbook = load_uploaded_forecast_workbook(payload, "paired.xlsx")
    history = prepare_uploaded_forecast_history(workbook)

    assert history.sheets_used == ["NM2"]
    assert history.daily["net_sales"].sum() == 6500


def test_hierarchy_filter_uses_detail_sheet_from_uploaded_pair() -> None:
    dates = pd.date_range("2026-01-01", periods=65, freq="D")
    detail = pd.DataFrame(
        {
            "DATE": dates.repeat(2),
            "DIVISION": ["FMCG", "APPAREL"] * len(dates),
            "SECTION": ["FOOD", "CLOTHING"] * len(dates),
            "DEPARTMENT": ["GROCERY", "FASHION"] * len(dates),
            "NET_AMOUNT": [60, 40] * len(dates),
        }
    )
    daily = pd.DataFrame({"DATE": dates, "SALE": [100] * len(dates)})
    payload = _workbook_bytes({"NM1": detail, "NM2": daily})

    workbook = load_uploaded_forecast_workbook(payload, "paired.xlsx")
    history = prepare_uploaded_forecast_history(
        workbook,
        apply_view_filters=True,
        divisions=["FMCG"],
    )

    assert history.sheets_used == ["NM1"]
    assert history.daily["net_sales"].sum() == 3900


def test_uploaded_workbook_requires_date_and_sales_columns() -> None:
    payload = _workbook_bytes(
        {"Notes": pd.DataFrame({"DATE": ["2026-01-01"], "COMMENT": ["No sales"]})}
    )

    with pytest.raises(ValueError, match="No forecast history was found"):
        load_uploaded_forecast_workbook(payload, "invalid.xlsx")
