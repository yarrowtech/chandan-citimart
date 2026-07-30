from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from uuid import uuid4

from src.data_cleaner import clean_frame, parse_dates
from src.data_loader import load_workbook_data
from src.schema_detector import detect_columns, store_code_for_sheet


def test_store_sheet_mapping() -> None:
    assert store_code_for_sheet("NM1") == "NW"
    assert store_code_for_sheet("NW2") == "NW"
    assert store_code_for_sheet("HB1") == "HB"
    assert store_code_for_sheet("CHW2") == "CHW"


def test_alias_mapping_is_case_and_punctuation_tolerant() -> None:
    mapping = detect_columns(
        [
            " Bill-Quantity ",
            "NET_AMOUNT",
            "BUCKET SIZE",
            "DIVISION",
            "SALE_TARGET",
        ]
    )
    assert mapping["quantity"] == " Bill-Quantity "
    assert mapping["net_sales"] == "NET_AMOUNT"
    assert mapping["basket_size"] == "BUCKET SIZE"
    assert mapping["division"] == "DIVISION"
    assert mapping["target"] == "SALE_TARGET"


def test_undated_subtotal_rows_are_not_valid_facts() -> None:
    raw = pd.DataFrame(
        {
            "DATE": [pd.Timestamp("2026-01-01"), pd.NaT],
            "DIVISION": ["FMCG", pd.NA],
            "NET_AMOUNT": [100.0, 100.0],
        }
    )
    cleaned, quality = clean_frame(
        raw,
        {"date": "DATE", "division": "DIVISION", "net_sales": "NET_AMOUNT"},
        "NW",
        "NW1",
        "detail",
    )
    assert len(cleaned) == 1
    assert cleaned["net_sales"].sum() == 100
    assert quality["subtotal_or_undated_rows_removed"] == 1


def test_date_parsing_excel_serial_and_day_first() -> None:
    parsed = parse_dates(pd.Series([45992, "02/01/2026", pd.Timestamp("2026-03-04")]))
    assert parsed.dt.strftime("%Y-%m-%d").tolist() == [
        "2025-12-01",
        "2026-01-02",
        "2026-03-04",
    ]


def test_missing_hb_worksheets_do_not_fail() -> None:
    # Keep the temporary workbook inside the project for locked-down Windows CI.
    path = Path("reports") / f"test_salesdata_{uuid4().hex}.xlsx"
    detail = pd.DataFrame(
        {
            "DATE": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "DIVISION": ["FMCG", "FMCG"],
            "SECTION": ["Food", "Food"],
            "DEPARTMENT": ["Grocery", "Grocery"],
            "BILL_QUANTITY": [2, 3],
            "NET_AMOUNT": [100, 150],
            "GROSS_AMOUNT": [110, 170],
        }
    )
    daily = pd.DataFrame(
        {
            "DATE": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "SALE_TARGET": [90, 120],
            "SALE": [100, 150],
            "SUM_OF_BILL_QUANTITY": [20, 30],
            "FOOTFALL": [5, 6],
            "NOB": [2, 2],
            "ACHIEVEMENT_PERCENTAGE": [0.5, 0.75],
        }
    )
    colour_rules = pd.DataFrame(
        {
            "KPI NAME": [
                "ATV",
                "RPV",
                "BUSKET SIZE",
                "CONVERSION PERCENTAGE",
                "ACHIEVEMNET PERCENTAGE",
            ],
            "RED": ["< 900", "< 500", "< 2", "< 45%", "< 80%"],
            "YELLOW": [
                "900 to 1100",
                "500 to 700",
                "2 to 5",
                "45% to 55%",
                "80% to 100%",
            ],
            "GREEN": ["> 1100", "> 700", "> 5", "> 55%", "> 100"],
        }
    )
    try:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            detail.to_excel(writer, sheet_name="NM1", index=False)
            daily.to_excel(writer, sheet_name="NM2", index=False)
            detail.to_excel(writer, sheet_name="HB1", index=False)
            daily.assign(
                SALE=np.nan,
                FOOTFALL=np.nan,
                NOB=np.nan,
                ACHIEVEMENT_PERCENTAGE=np.nan,
            ).to_excel(writer, sheet_name="HB2", index=False)
            colour_rules.to_excel(
                writer, sheet_name="COLOUR FORMATTING", index=False
            )
        loaded = load_workbook_data(path)
        assert loaded.available_stores == ["NW"]
        assert set(loaded.loaded_sheets) == {"NM1", "NM2"}
        assert set(loaded.skipped_sheets) == {"HB1", "HB2"}
        assert loaded.skipped_stores == ["HB"]
        assert loaded.color_rule_source == "COLOUR FORMATTING"
        assert set(loaded.kpi_color_rules) == {
            "atv",
            "rpv",
            "basket_size",
            "conversion",
            "achievement",
        }
        assert loaded.kpi_color_rules["conversion"].lower_bound == 0.45
        assert loaded.kpi_color_rules["conversion"].upper_bound == 0.55
        assert loaded.kpi_color_rules["achievement"].status(1.0) == "Yellow"
        assert loaded.kpi_color_rules["achievement"].status(1.001) == "Green"
        assert "COLOUR FORMATTING" not in loaded.skipped_sheets
        assert loaded.daily["target"].sum() == 210
        assert set(loaded.daily["target_source"]) == {
            "CitiMart manual SALE_TARGET"
        }
        assert loaded.daily["achievement"].tolist() == [
            100 / 90,
            150 / 120,
        ]
        assert loaded.daily["quantity"].sum() == 50
        assert loaded.detail["division"].tolist() == ["FMCG", "FMCG"]
    finally:
        path.unlink(missing_ok=True)
