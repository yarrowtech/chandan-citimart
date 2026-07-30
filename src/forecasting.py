"""Leakage-safe time-series forecasting with chronological validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# Respect constrained Windows/VDI environments before importing scikit-learn.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from config.settings import MIN_FORECAST_OBSERVATIONS


@dataclass
class ForecastResult:
    model_name: str
    frequency: str
    training_start: pd.Timestamp
    training_end: pd.Timestamp
    horizon: int
    metrics: dict[str, float | None]
    history: pd.DataFrame
    validation: pd.DataFrame
    future: pd.DataFrame
    candidate_metrics: pd.DataFrame
    explanation: str
    warning: str | None = None


FEATURE_COLUMNS = [
    "day_of_week",
    "day_of_month",
    "week_of_year",
    "month",
    "quarter",
    "year",
    "weekend",
    "lag_1",
    "lag_7",
    "lag_14",
    "lag_28",
    "rolling_7",
    "rolling_14",
    "rolling_28",
    "rolling_std_7",
]


def build_features(series: pd.Series) -> pd.DataFrame:
    """Create calendar and strictly past-only lag/rolling features."""
    values = series.astype(float).copy()
    index = pd.DatetimeIndex(values.index)
    features = pd.DataFrame(index=index)
    features["day_of_week"] = index.dayofweek
    features["day_of_month"] = index.day
    features["week_of_year"] = index.isocalendar().week.astype(int).to_numpy()
    features["month"] = index.month
    features["quarter"] = index.quarter
    features["year"] = index.year
    features["weekend"] = (index.dayofweek >= 5).astype(int)
    for lag in (1, 7, 14, 28):
        features[f"lag_{lag}"] = values.shift(lag)
    past = values.shift(1)
    for window in (7, 14, 28):
        features[f"rolling_{window}"] = past.rolling(window, min_periods=window).mean()
    features["rolling_std_7"] = past.rolling(7, min_periods=7).std().fillna(0)
    return features


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mae = float(mean_absolute_error(actual, predicted))
    rmse = float(np.sqrt(mean_squared_error(actual, predicted)))
    nonzero = actual != 0
    mape = (
        float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])))
        if nonzero.any()
        else None
    )
    denominator = float(np.abs(actual).sum())
    wape = float(np.abs(actual - predicted).sum() / denominator) if denominator else None
    r2 = float(r2_score(actual, predicted)) if len(actual) > 1 else None
    return {"MAE": mae, "RMSE": rmse, "MAPE": mape, "WAPE": wape, "R²": r2}


def prepare_series(daily: pd.DataFrame) -> tuple[pd.Series, str]:
    """Aggregate net sales and choose a defensible frequency from observed history."""
    if daily.empty or "date" not in daily or "net_sales" not in daily:
        return pd.Series(dtype=float), "D"
    values = (
        daily.dropna(subset=["date", "net_sales"])
        .groupby("date")["net_sales"]
        .sum()
        .sort_index()
    )
    if values.empty:
        return pd.Series(dtype=float), "D"
    full_daily = values.reindex(
        pd.date_range(values.index.min(), values.index.max(), freq="D"), fill_value=0.0
    )
    if len(full_daily) >= MIN_FORECAST_OBSERVATIONS:
        return full_daily.astype(float), "D"
    weekly = full_daily.resample("W-SUN").sum()
    if len(weekly) >= 24:
        return weekly, "W"
    return full_daily.resample("MS").sum(), "MS"


def _candidate_models() -> dict[str, Any]:
    return {
        "Ridge Regression": make_pipeline(StandardScaler(), Ridge(alpha=2.0)),
        "Random Forest Regressor": RandomForestRegressor(
            n_estimators=180,
            min_samples_leaf=2,
            random_state=42,
            # Single-process fitting avoids Windows worker-pipe permission failures
            # in locked-down production/VDI environments.
            n_jobs=1,
        ),
        "HistGradientBoosting Regressor": HistGradientBoostingRegressor(
            max_iter=180, learning_rate=0.05, max_leaf_nodes=15, random_state=42
        ),
    }


def _future_index(last: pd.Timestamp, periods: int, frequency: str) -> pd.DatetimeIndex:
    offset = {"D": "D", "W": "W-SUN", "MS": "MS"}[frequency]
    return pd.date_range(last, periods=periods + 1, freq=offset)[1:]


def train_forecast(daily: pd.DataFrame, horizon: int = 30) -> ForecastResult:
    """Evaluate baselines and ML candidates, then recursively forecast."""
    series, frequency = prepare_series(daily)
    minimum = 60 if frequency == "D" else 18
    if len(series) < minimum:
        raise ValueError(
            f"Insufficient history: {len(series)} {frequency} observations; "
            f"at least {minimum} are required."
        )
    features = build_features(series)
    dataset = features.assign(target=series).dropna()
    validation_size = max(14 if frequency == "D" else 6, int(len(dataset) * 0.2))
    validation_size = min(validation_size, max(len(dataset) // 3, 1))
    train = dataset.iloc[:-validation_size]
    valid = dataset.iloc[-validation_size:]
    if len(train) < 20:
        raise ValueError("Insufficient feature-complete history for stable validation.")

    candidates: list[tuple[str, dict[str, float | None], np.ndarray, Any]] = []
    # Baselines use only information available before each predicted timestamp.
    seasonal = series.shift(7).reindex(valid.index).to_numpy()
    moving = series.shift(1).rolling(7).mean().reindex(valid.index).to_numpy()
    for name, predictions in (
        ("Seasonal Naive (7-period)", seasonal),
        ("Moving Average (7-period)", moving),
    ):
        candidates.append((name, _metrics(valid["target"].to_numpy(), predictions), predictions, None))

    for name, model in _candidate_models().items():
        model.fit(train[FEATURE_COLUMNS], train["target"])
        predictions = np.clip(model.predict(valid[FEATURE_COLUMNS]), 0, None)
        candidates.append(
            (name, _metrics(valid["target"].to_numpy(), predictions), predictions, model)
        )

    candidates.sort(key=lambda item: (item[1]["RMSE"], item[1]["MAE"]))
    best_name, best_metrics, best_predictions, best_model = candidates[0]

    extended = series.copy()
    if best_model is not None:
        best_model.fit(dataset[FEATURE_COLUMNS], dataset["target"])
    future_rows = []
    for timestamp in _future_index(series.index.max(), horizon, frequency):
        if best_name.startswith("Seasonal Naive"):
            lag_timestamp = timestamp - (pd.Timedelta(days=7) if frequency == "D" else pd.Timedelta(weeks=7))
            prediction = float(extended.get(lag_timestamp, extended.iloc[-1]))
        elif best_name.startswith("Moving Average"):
            prediction = float(extended.iloc[-7:].mean())
        else:
            temp = pd.concat([extended, pd.Series([np.nan], index=[timestamp])])
            row = build_features(temp).loc[[timestamp], FEATURE_COLUMNS]
            prediction = float(np.clip(best_model.predict(row)[0], 0, None))
        extended.loc[timestamp] = prediction
        future_rows.append((timestamp, prediction))

    future = pd.DataFrame(future_rows, columns=["date", "forecast"])
    interval = 1.96 * float(best_metrics["RMSE"])
    future["lower"] = np.clip(future["forecast"] - interval, 0, None)
    future["upper"] = future["forecast"] + interval
    validation = pd.DataFrame(
        {
            "date": valid.index,
            "actual": valid["target"].to_numpy(),
            "prediction": best_predictions,
        }
    )
    metric_rows = [{"Model": name, **metrics} for name, metrics, _, _ in candidates]
    explanation = (
        "Selected by chronological holdout RMSE. Calendar, lag, and rolling-average "
        "features use prior observations only; future predictions are generated recursively."
    )
    return ForecastResult(
        model_name=best_name,
        frequency=frequency,
        training_start=series.index.min(),
        training_end=series.index.max(),
        horizon=horizon,
        metrics=best_metrics,
        history=pd.DataFrame({"date": series.index, "actual": series.to_numpy()}),
        validation=validation,
        future=future,
        candidate_metrics=pd.DataFrame(metric_rows),
        explanation=explanation,
    )
