from __future__ import annotations

import numpy as np
import pandas as pd

from src.charts import forecast_chart, same_day_comparison
from src.comparison_engine import aligned_monthly_daily, is_partial_month
from src.forecasting import build_features, train_forecast


def test_forecast_features_do_not_use_future_values() -> None:
    index = pd.date_range("2026-01-01", periods=50, freq="D")
    original = pd.Series(np.arange(50, dtype=float), index=index)
    changed = original.copy()
    changed.iloc[40:] = 1_000_000
    original_features = build_features(original)
    changed_features = build_features(changed)
    pd.testing.assert_series_equal(
        original_features.loc[index[39]],
        changed_features.loc[index[39]],
    )
    assert original_features.loc[index[20], "rolling_7"] == original.iloc[13:20].mean()


def test_partial_month_logic_and_alignment() -> None:
    assert is_partial_month(pd.Timestamp("2026-02-20"))
    assert not is_partial_month(pd.Timestamp("2026-02-28"))
    frame = pd.DataFrame(
        {
            "date": list(pd.date_range("2026-01-01", "2026-01-31"))
            + list(pd.date_range("2026-02-01", "2026-02-20")),
            "net_sales": 1.0,
        }
    )
    aligned = aligned_monthly_daily(frame)
    assert aligned.groupby("year_month")["day"].max().to_dict() == {
        "2026-01": 20,
        "2026-02": 20,
    }


def test_selected_day_monthly_comparison() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-02-01", "2026-02-02"]
            ),
            "net_sales": [100, 200, 300, 400],
        }
    )
    _, table = same_day_comparison(frame, selected_day=2)
    assert table["Month"].tolist() == ["Jan-2026", "Feb-2026"]
    assert table["Day of month"].tolist() == ["Day 2", "Day 2"]
    assert table["Net Sales"].tolist() == [200, 400]


def test_forecast_uses_chronological_validation() -> None:
    dates = pd.date_range("2025-01-01", periods=120, freq="D")
    values = 1000 + np.arange(120) * 2 + 50 * np.sin(np.arange(120) / 7)
    daily = pd.DataFrame({"date": dates, "net_sales": values})
    result = train_forecast(daily, horizon=7)
    assert result.validation["date"].min() > result.training_start
    assert result.future["date"].min() > result.training_end
    assert len(result.future) == 7
    assert result.model_name in set(result.candidate_metrics["Model"])
    figure, _ = forecast_chart(result)
    assert all(
        isinstance(value, str)
        for trace in figure.data
        for value in trace.x
    )
    assert isinstance(figure.layout.shapes[0].x0, str)
