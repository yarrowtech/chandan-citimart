from __future__ import annotations

import pandas as pd
import pytest

from src.charts import gauge
from src.kpi_engine import calculate_kpis, kpi_table, safe_divide
from src.ui_components import kpi_card_html
from config.kpi_thresholds import (
    DEFAULT_KPI_COLOR_RULES,
    conversion_status,
    gauge_assessment,
)


def test_safe_division() -> None:
    assert safe_divide(10, 2) == 5
    assert safe_divide(10, 0) is None
    assert safe_divide(None, 2) is None


def test_conversion_status_bands() -> None:
    assert conversion_status(0.4499) == "Red"
    assert conversion_status(0.45) == "Yellow"
    assert conversion_status(0.5499) == "Yellow"
    assert conversion_status(0.55) == "Yellow"
    assert conversion_status(0.5501) == "Green"


def test_all_workbook_rule_boundaries_are_inclusive_for_yellow() -> None:
    expected = {
        "atv": (900, 1100),
        "rpv": (500, 700),
        "basket_size": (2, 5),
        "conversion": (0.45, 0.55),
        "achievement": (0.80, 1.00),
    }
    for metric, (lower, upper) in expected.items():
        rule = DEFAULT_KPI_COLOR_RULES[metric]
        assert rule.status(lower - 0.0001) == "Red"
        assert rule.status(lower) == "Yellow"
        assert rule.status(upper) == "Yellow"
        assert rule.status(upper + 0.0001) == "Green"


def test_gauge_remarks_follow_exact_threshold_boundaries() -> None:
    assert gauge_assessment("atv", 899)[0] == "Red"
    assert gauge_assessment("atv", 900)[0] == "Yellow"
    assert gauge_assessment("atv", 1100)[0] == "Yellow"
    assert gauge_assessment("atv", 1100.1)[0] == "Green"
    assert gauge_assessment("conversion", 0.45)[0] == "Yellow"
    assert gauge_assessment("conversion", 0.55)[0] == "Yellow"
    assert gauge_assessment("conversion", 0.5501)[0] == "Green"
    assert gauge_assessment("achievement", 0.80)[0] == "Yellow"
    assert gauge_assessment("achievement", 1.00)[0] == "Yellow"
    assert gauge_assessment("achievement", 1.001)[0] == "Green"


def test_gauge_uses_compact_dashboard_layout() -> None:
    figure = gauge(
        1300,
        "ATV",
        DEFAULT_KPI_COLOR_RULES["atv"],
        "currency",
        1250,
    )
    assert figure.layout.height == 300
    assert figure.layout.autosize is True
    assert figure.layout.margin.l == 8
    assert figure.layout.margin.r == 8
    assert figure.layout.showlegend is False
    assert len(figure.layout.shapes) == 4
    assert figure.layout.shapes[-1].type == "line"
    assert figure.data[0].mode == "markers"
    annotation_text = [item.text for item in figure.layout.annotations]
    assert "<b>ATV Gauge</b>" in figure.layout.title.text
    assert "<b>₹1,300</b>" in annotation_text


def test_kpi_color_code_is_inside_card() -> None:
    html = kpi_card_html(
        "Total Net Sales",
        {
            "value": 3300,
            "status": "Green",
            "source": "daily summary",
            "formula": "Σ SALE",
        },
    )
    assert 'class="kpi-card"' in html
    assert 'class="kpi-status"' in html
    assert "status-green" in html
    assert 'class="kpi-formula"' in html
    assert "Σ SALE" in html
    assert html.index('class="kpi-status"') < html.rindex("</div>")
    assert "Status:" not in html


def test_net_gross_atv_rpv_basket_conversion_achievement(daily_fact) -> None:
    kpis = calculate_kpis(daily_fact)
    assert kpis["net_sales"]["value"] == 3300
    assert kpis["net_sales"]["status"] == "Neutral"
    assert kpis["gross_sales"]["value"] == 3650
    assert kpis["gross_sales"]["status"] == "Neutral"
    assert kpis["transactions"]["value"] == 24
    assert kpis["atv"]["value"] == 137.5
    assert kpis["rpv"]["value"] == 3300 / 61
    assert kpis["basket_size"]["value"] == 30 / 24
    assert kpis["conversion"]["value"] == 24 / 61
    assert kpis["achievement"]["value"] == 3300 / 3500
    assert kpis["atv"]["status"] == "Red"
    assert kpis["rpv"]["status"] == "Red"
    assert kpis["basket_size"]["status"] == "Red"
    assert kpis["conversion"]["status"] == "Red"
    assert kpis["achievement"]["status"] == "Yellow"
    assert kpis["target"]["source"] == "CitiMart manual SALE_TARGET"
    assert all(payload["formula"] for payload in kpis.values())
    table = kpi_table(kpis)
    assert "Formula" in table
    assert "Color rule" in table
    assert table["Formula"].notna().all()
    assert "Total Units Sold" in table["KPI"].tolist()


def test_gross_sales_derivation() -> None:
    frame = pd.DataFrame(
        {"net_sales": [100.0, 200.0], "discount": [10.0, 20.0]}
    )
    kpis = calculate_kpis(frame)
    assert kpis["gross_sales"]["value"] == 330
    assert kpis["gross_sales"]["source"] == "derived: net sales + discount"


def test_distinct_transaction_count_preferred() -> None:
    frame = pd.DataFrame(
        {
            "net_sales": [100, 200, 50],
            "transaction_id": ["A", "A", "B"],
            "quantity": [1, 2, 1],
        }
    )
    kpis = calculate_kpis(frame)
    assert kpis["transactions"]["value"] == 2
    assert kpis["atv"]["value"] == 175


def test_hierarchy_filter_estimates_unattributable_customer_kpis(
    daily_fact, detail_fact
) -> None:
    """Footfall/NOB/target have no exact per-division source, so a hierarchy
    filter prorates each store-day's total by this selection's net-sales
    share (see kpi_engine.prorate_daily_by_hierarchy_share) instead of
    reporting N/A.

    Expected shares from the fixtures: NW/2026-01-01 is 400/1000 = 0.4,
    NW/2026-01-02 is 1500/1500 = 1.0, CHW/2026-01-03 is 800/800 = 1.0.
    """
    food = detail_fact[detail_fact["section"] == "Food"]
    kpis = calculate_kpis(daily_fact, food, hierarchy_filtered=True)
    assert kpis["net_sales"]["value"] == 2700
    assert kpis["net_sales"]["estimated"] is False

    expected_footfall = 20 * 0.4 + 25 * 1.0 + 16 * 1.0
    expected_transactions = 8 * 0.4 + 10 * 1.0 + 6 * 1.0
    expected_target = 1200 * 0.4 + 1400 * 1.0 + 900 * 1.0
    expected_quantity = 10 * 0.4 + 12 * 1.0 + 8 * 1.0

    assert kpis["footfall"]["value"] == pytest.approx(expected_footfall)
    assert kpis["transactions"]["value"] == pytest.approx(expected_transactions)
    assert kpis["target"]["value"] == pytest.approx(expected_target)
    assert kpis["quantity"]["value"] == pytest.approx(expected_quantity)
    assert kpis["atv"]["value"] == pytest.approx(2700 / expected_transactions)
    assert kpis["rpv"]["value"] == pytest.approx(2700 / expected_footfall)
    assert kpis["basket_size"]["value"] == pytest.approx(
        expected_quantity / expected_transactions
    )
    assert kpis["conversion"]["value"] == pytest.approx(
        expected_transactions / expected_footfall
    )
    assert kpis["achievement"]["value"] == pytest.approx(2700 / expected_target)

    for key in (
        "footfall",
        "transactions",
        "target",
        "quantity",
        "atv",
        "rpv",
        "basket_size",
        "conversion",
        "achievement",
    ):
        assert kpis[key]["estimated"] is True
        assert "estimated" in kpis[key]["source"].casefold()


def test_hierarchy_filter_reports_na_without_comparable_store_days() -> None:
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-01"]),
            "store_code": ["NW"],
            "net_sales": [500.0],
            "footfall": [10.0],
            "nob": [4.0],
        }
    )
    detail = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01"]),
            "store_code": ["NW"],
            "net_sales": [200.0],
        }
    )
    kpis = calculate_kpis(daily, detail, hierarchy_filtered=True)
    assert kpis["net_sales"]["value"] == 200
    assert kpis["footfall"]["value"] is None
    assert kpis["footfall"]["message"] is not None
