"""Application-wide settings."""

from pathlib import Path

APP_TITLE = "CITIMART™ SALES KPI DASHBOARD REPORT"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK = PROJECT_ROOT / "salesdata.xlsx"
CURRENCY_SYMBOL = "₹"

# Prefix aliases make the current NM sheets and future NW sheets both map to New Market.
STORE_SHEET_PREFIXES = {
    "NW": ("NW", "NM"),
    "HB": ("HB",),
    "CHW": ("CHW",),
}

STORE_NAMES = {
    "NW": "CITIMART - NEW MARKET",
    "HB": "CITIMART - HATIBAGAN",
    "CHW": "CITIMART - CHOWRINGEE",
}

DETAIL_SUFFIXES = ("1",)
DAILY_SUFFIXES = ("2",)
DEFAULT_DAILY_HORIZON = 30
MIN_FORECAST_OBSERVATIONS = 60

QUARTER_DEFINITIONS = {
    "Q1": "January to March",
    "Q2": "April to June",
    "Q3": "July to September",
    "Q4": "October to December",
}
