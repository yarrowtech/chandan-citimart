from __future__ import annotations

import base64
import re

import pandas as pd
import plotly.graph_objects as go

import src.pdf_report as pdf_report
from src.pdf_report import generate_pdf


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
    "EQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_pdf_places_each_chart_on_a_dedicated_page(monkeypatch) -> None:
    exported_titles: list[str] = []

    def fake_export_chart_images(figures):
        exported_titles.extend(title for title, _ in figures)
        return [ONE_PIXEL_PNG for _ in figures], []

    monkeypatch.setattr(
        pdf_report,
        "_export_chart_images",
        fake_export_chart_images,
    )
    kpis = {
        "net_sales": {
            "value": 1000,
            "formula": "SALE",
            "status": "Neutral",
            "color_rule": "No rule",
            "source": "daily summary",
        },
        "quantity": {
            "value": 25,
            "formula": "SUM_OF_BILL_QUANTITY",
            "status": "Neutral",
            "color_rule": "No rule",
            "source": "store-day summary",
        },
    }
    comparison = pd.DataFrame(
        {
            "KPI": ["Total Net Sales", "Total Units Sold"],
            "Current value": ["1,000", "25"],
        }
    )
    pdf_bytes, warnings = generate_pdf(
        {"Stores": "All", "Date coverage": "01-01-2026–31-01-2026"},
        kpis,
        comparison,
        [("Store scorecard", comparison)],
        {"Method": "No forecast"},
        [],
        [
            ("Sales chart", go.Figure()),
            ("Conversion chart", go.Figure()),
        ],
    )

    assert warnings == []
    assert pdf_bytes.startswith(b"%PDF")
    assert exported_titles == ["Sales chart", "Conversion chart"]
    page_count = len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))
    assert page_count >= 6
