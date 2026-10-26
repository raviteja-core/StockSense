"""StockSense: Baseline Forecasting Models.

Implements:
1. Naive Seasonal Benchmark (same week last year: lag 52).
2. Ridge Regression Baseline with recursive multi-step forecasting and 80% prediction intervals.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from src.features import FEATURE_COLUMNS

logger = logging.getLogger("stocksense.forecast_baseline")


def predict_naive_seasonal(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame
) -> pd.DataFrame:
    """Generate naive seasonal forecasts (same week last year: lag 52).

    Returns DataFrame with columns:
        [store_id, dept_id, date_key, model_name, fold_id, forecast, lower_80, upper_80, actual]
    """
    results = []

    # Map (store_id, dept_id, week_of_year) to last year's sales from train set
    # Using the most recent 52 weeks of the training set
    train_recent = df_train.sort_values(["store_id", "dept_id", "full_date"]).groupby(
        ["store_id", "dept_id"]
    ).tail(52)

    historical_lookup = train_recent.set_index(["store_id", "dept_id", "week_of_year"])["weekly_sales"].to_dict()
    series_medians = df_train.groupby(["store_id", "dept_id"])["weekly_sales"].median().to_dict()

    for _, row in df_test.iterrows():
        sid = row["store_id"]
        did = row["dept_id"]
        woy = row["week_of_year"]
        actual = row["weekly_sales"]
        date_key = row["date_key"]
        fold_id = row.get("fold_id", 1)

        # Lookup last year's sales for this week of year, fallback to series median
        pred = historical_lookup.get((sid, did, woy), series_medians.get((sid, did), 0.0))
        pred = max(0.0, float(pred))

        # Heuristic 80% interval for naive baseline (+- 20% or empirical standard deviation)
        lower_80 = max(0.0, pred * 0.80)
        upper_80 = pred * 1.20

        results.append({
            "store_id": int(sid),
            "dept_id": int(did),
            "date_key": int(date_key),
            "model_name": "Naive Seasonal",
            "fold_id": int(fold_id),
            "forecast": round(pred, 2),
            "lower_80": round(lower_80, 2),
            "upper_80": round(upper_80, 2),
            "actual": round(float(actual), 2),
            "error": round(float(actual) - pred, 2),
            "abs_error": round(abs(float(actual) - pred), 2)
        })

    return pd.DataFrame(results)


class RidgeForecaster:
    """Regularized Ridge Regression Forecaster for Weekly Retail Demand."""

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.model = Ridge(alpha=self.alpha, random_state=42)
        self.scaler = StandardScaler()
        self.feature_cols = FEATURE_COLUMNS
        self.train_residual_std: Dict[Tuple[int, int], float] = {}

    def fit(self, df_train: pd.DataFrame) -> RidgeForecaster:
        """Fit Ridge model on training set and estimate residual standard deviations."""
        # Drop rows with NaNs resulting from 52-week lag initialization
        valid_train = df_train.dropna(subset=self.feature_cols + ["weekly_sales"]).copy()

        X_train = valid_train[self.feature_cols]
        y_train = valid_train["weekly_sales"]

        X_scaled = self.scaler.fit_transform(X_train)
        self.model.fit(X_scaled, y_train)

        # Compute per-series residual standard deviation for 80% prediction intervals
        preds_train = self.model.predict(X_scaled)
        valid_train["residual"] = y_train.values - preds_train

        std_per_series = valid_train.groupby(["store_id", "dept_id"])["residual"].std().fillna(y_train.std())
        self.train_residual_std = std_per_series.to_dict()
        self.global_std = float(valid_train["residual"].std())

        return self

    def predict_fold(
        self,
        df_train: pd.DataFrame,
        df_test: pd.DataFrame,
        fold_id: int
    ) -> pd.DataFrame:
        """Predict 13-week horizon for all series using recursive autoregression."""
        results = []
        unique_series = df_test[["store_id", "dept_id"]].drop_duplicates().values

        # Build initial history per series from df_train
        for sid, did in unique_series:
            s_train = df_train[(df_train["store_id"] == sid) & (df_train["dept_id"] == did)].sort_values("full_date")
            s_test = df_test[(df_test["store_id"] == sid) & (df_test["dept_id"] == did)].sort_values("full_date")

            if s_test.empty:
                continue

            # Historical sales history list
            history_sales = s_train["weekly_sales"].tolist()
            res_std = self.train_residual_std.get((sid, did), self.global_std)
            z_80 = 1.2816  # 80% normal critical value

            # Predict week-by-week over horizon
            for _, test_row in s_test.iterrows():
                # Dynamically construct autoregressive lags from history
                lag_1 = history_sales[-1] if len(history_sales) >= 1 else 0.0
                lag_2 = history_sales[-2] if len(history_sales) >= 2 else lag_1
                lag_4 = history_sales[-4] if len(history_sales) >= 4 else lag_2
                lag_52 = history_sales[-52] if len(history_sales) >= 52 else lag_4

                roll_4 = float(np.mean(history_sales[-4:])) if len(history_sales) >= 1 else 0.0
                roll_13 = float(np.mean(history_sales[-13:])) if len(history_sales) >= 1 else 0.0

                # Assemble feature vector
                row_dict = {
                    "lag_1": lag_1, "lag_2": lag_2, "lag_4": lag_4, "lag_52": lag_52,
                    "rolling_mean_4": roll_4, "rolling_mean_13": roll_13,
                    "week_of_year": test_row["week_of_year"],
                    "month": test_row["month"],
                    "sin_week": test_row["sin_week"],
                    "cos_week": test_row["cos_week"],
                    "is_holiday_week": test_row["is_holiday_week"],
                    "is_week_before_holiday": test_row["is_week_before_holiday"],
                    "is_week_after_holiday": test_row["is_week_after_holiday"],
                    "temperature": test_row["temperature"],
                    "fuel_price": test_row["fuel_price"],
                    "cpi": test_row["cpi"],
                    "unemployment": test_row["unemployment"],
                    "markdown_total": test_row["markdown_total"],
                    "has_markdown": test_row["has_markdown"],
                    "store_size": test_row["store_size"],
                    "store_type_B": test_row["store_type_B"],
                    "store_type_C": test_row["store_type_C"]
                }

                x_df = pd.DataFrame([row_dict])[self.feature_cols]
                x_scaled = self.scaler.transform(x_df)
                pred = max(0.0, float(self.model.predict(x_scaled)[0]))

                # Update recursive history for subsequent weeks
                history_sales.append(pred)

                actual = float(test_row["weekly_sales"])
                lower_80 = max(0.0, pred - z_80 * res_std)
                upper_80 = pred + z_80 * res_std

                results.append({
                    "store_id": int(sid),
                    "dept_id": int(did),
                    "date_key": int(test_row["date_key"]),
                    "model_name": "Ridge Baseline",
                    "fold_id": int(fold_id),
                    "forecast": round(pred, 2),
                    "lower_80": round(lower_80, 2),
                    "upper_80": round(upper_80, 2),
                    "actual": round(actual, 2),
                    "error": round(actual - pred, 2),
                    "abs_error": round(abs(actual - pred), 2)
                })

        return pd.DataFrame(results)
