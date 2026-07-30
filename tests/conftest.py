from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def daily_fact() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "store_code": ["NW", "NW", "CHW"],
            "store_name": [
                "CITIMART - NEW MARKET",
                "CITIMART - NEW MARKET",
                "CITIMART - CHOWRINGEE",
            ],
            "net_sales": [1000.0, 1500.0, 800.0],
            "gross_sales": [1100.0, 1650.0, 900.0],
            "quantity": [10.0, 12.0, 8.0],
            "footfall": [20.0, 25.0, 16.0],
            "nob": [8.0, 10.0, 6.0],
            "target": [1200.0, 1400.0, 900.0],
        }
    )


@pytest.fixture
def detail_fact() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-03"]
            ),
            "store_code": ["NW", "NW", "NW", "CHW"],
            "store_name": [
                "CITIMART - NEW MARKET",
                "CITIMART - NEW MARKET",
                "CITIMART - NEW MARKET",
                "CITIMART - CHOWRINGEE",
            ],
            "division": ["FMCG", "Apparel", "FMCG", "FMCG"],
            "section": ["Food", "Fashion", "Food", "Food"],
            "department": ["Grocery", "Mens", "Grocery", "Grocery"],
            "net_sales": [400.0, 600.0, 1500.0, 800.0],
            "gross_sales": [450.0, 650.0, 1650.0, 900.0],
            "quantity": [4.0, 6.0, 12.0, 8.0],
        }
    )
