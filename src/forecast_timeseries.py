"""StockSense: Time-Series Forecasting Model (Holt-Winters Exponential Smoothing).

Fits univariate seasonal time-series models per Store x Department series
with annual seasonality (52 periods) and additive trend.
Covers the top 100 series by revenue for fast, robust evaluation.
"""

from __future__ import annotations

import logging
from typing import List, Tuple, Optional
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

logger = logging.getLogger("stocksense.forecast_timeseries")


def fit_predict_holt_winters_series(
    y_train: pd.Series,
    horizon: int = 13
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit Holt-Winters model to a single weekly series and predict horizon.

    Returns:
        (forecasts, lower_80, upper_80)
    """
    z_80 = 1.2816
    # Ensure positive non-zero series for stability
    y_clean = y_train.clip(lower=0.0).values
    n_obs = len(y_clean)

    # Attempt additive seasonal (52 periods) + additive trend
    if n_obs >= 104:
        try:
            model = ExponentialSmoothing(
                y_clean,
                seasonal_periods=52,
                trend="add",
                seasonal="add",
                initialization_method="estimated"
            )
            fit = model.fit(optimized=True)
            preds = fit.forecast(horizon)
            residuals = y_clean - fit.fittedvalues
            res_std = float(np.std(residuals)) if len(residuals) > 0 else float(np.std(y_clean))
            preds = np.clip(preds, 0.0, None)
            lower_80 = np.clip(preds - z_80 * res_std, 0.0, None)
            upper_80 = preds + z_80 * res_std
            return preds, lower_80, upper_80
        except Exception:
            pass  # Fall through to trend-only model

    # Fallback 1: Trend-only model
    try:
        model = ExponentialSmoothing(
            y_clean,
            trend="add",
            initialization_method="estimated"
        )
        fit = model.fit(optimized=True)
        preds = fit.forecast(horizon)
        res_std = float(np.std(y_clean - fit.fittedvalues))
        preds = np.clip(preds, 0.0, None)
        lower_80 = np.clip(preds - z_80 * res_std, 0.0, None)
        upper_80 = preds + z_80 * res_std
        return preds, lower_80, upper_80
    except Exception:
        pass

    # Fallback 2: Simple median / trailing average
    median_val = float(np.median(y_clean[-52:])) if n_obs >= 52 else float(np.median(y_clean))
    std_val = float(np.std(y_clean[-52:])) if n_obs >= 52 else float(np.std(y_clean))
    preds = np.full(horizon, median_val)
    lower_80 = np.clip(preds - z_80 * std_val, 0.0, None)
    upper_80 = preds + z_80 * std_val
    return preds, lower_80, upper_80


def predict_timeseries_fold(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    fold_id: int,
    target_series: Optional[List[Tuple[int, int]]] = None
) -> pd.DataFrame:
    """Run Holt-Winters forecasting on target series for the given test fold."""
    results = []
    if target_series is None:
        target_series = df_test[["store_id", "dept_id"]].drop_duplicates().values.tolist()

    for sid, did in target_series:
        s_train = df_train[(df_train["store_id"] == sid) & (df_train["dept_id"] == did)].sort_values("full_date")
        s_test = df_test[(df_test["store_id"] == sid) & (df_test["dept_id"] == did)].sort_values("full_date")

        if s_test.empty or s_train.empty:
            continue

        horizon = len(s_test)
        preds, lower_80, upper_80 = fit_predict_holt_winters_series(s_train["weekly_sales"], horizon=horizon)

        for idx, (_, test_row) in enumerate(s_test.iterrows()):
            pred = round(float(preds[idx]), 2)
            actual = round(float(test_row["weekly_sales"]), 2)
            low = round(float(lower_80[idx]), 2)
            upp = round(float(upper_80[idx]), 2)

            results.append({
                "store_id": int(sid),
                "dept_id": int(did),
                "date_key": int(test_row["date_key"]),
                "model_name": "Holt-Winters",
                "fold_id": int(fold_id),
                "forecast": pred,
                "lower_80": low,
                "upper_80": upp,
                "actual": actual,
                "error": round(actual - pred, 2),
                "abs_error": round(abs(actual - pred), 2)
            })

    return pd.DataFrame(results)
