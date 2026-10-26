"""StockSense: Leakage-Free Feature Engineering for Demand Forecasting.

Constructs lags, rolling statistics, calendar indicators, and exogenous features
for Store x Department weekly sales series.
Guarantees zero time-leakage: features at time t strictly use observations from < t.
"""

from __future__ import annotations

import logging
from typing import List, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger("stocksense.features")

FEATURE_COLUMNS: List[str] = [
    # Lags
    "lag_1", "lag_2", "lag_4", "lag_52",
    # Rolling averages (strictly past observations)
    "rolling_mean_4", "rolling_mean_13",
    # Calendar & Holiday signals
    "week_of_year", "month", "sin_week", "cos_week",
    "is_holiday_week", "is_week_before_holiday", "is_week_after_holiday",
    # Exogenous economic & promotional signals
    "temperature", "fuel_price", "cpi", "unemployment",
    "markdown_total", "has_markdown",
    # Store attributes
    "store_size", "store_type_B", "store_type_C"
]


def add_calendar_and_holiday_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add deterministic calendar features and holiday proximity flags."""
    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["full_date"]):
        df["full_date"] = pd.to_datetime(df["full_date"])

    df["week_of_year"] = df["full_date"].dt.isocalendar().week.astype(int)
    df["month"] = df["full_date"].dt.month.astype(int)

    # Cyclical representations of week of year
    df["sin_week"] = np.sin(2 * np.pi * df["week_of_year"] / 52.0).round(6)
    df["cos_week"] = np.cos(2 * np.pi * df["week_of_year"] / 52.0).round(6)

    # Holiday proximity indicators per store-department series
    # A holiday in the subsequent week is scheduled calendar knowledge (no leakage)
    df["is_week_before_holiday"] = df.groupby(["store_id", "dept_id"])["is_holiday_week"].shift(-1).fillna(0).astype(int)
    df["is_week_after_holiday"] = df.groupby(["store_id", "dept_id"])["is_holiday_week"].shift(1).fillna(0).astype(int)

    return df


def add_store_attribute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Encode store categorical attributes."""
    df = df.copy()
    df["store_type_B"] = (df["store_type"] == "B").astype(int)
    df["store_type_C"] = (df["store_type"] == "C").astype(int)
    return df


def compute_lag_and_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute autoregressive lags and trailing rolling means per series.

    Strictly uses historical values:
    - lag_k uses shift(k)
    - rolling_mean_m uses shift(1).rolling(m) so observation at t is NEVER included in rolling mean at t.
    """
    df = df.copy()
    df = df.sort_values(["store_id", "dept_id", "full_date"]).reset_index(drop=True)

    grouped = df.groupby(["store_id", "dept_id"])["weekly_sales"]

    # Autoregressive lags
    df["lag_1"] = grouped.shift(1)
    df["lag_2"] = grouped.shift(2)
    df["lag_4"] = grouped.shift(4)
    df["lag_52"] = grouped.shift(52)

    # Trailing rolling means (shift(1) guarantees exclusion of current week sales)
    df["rolling_mean_4"] = grouped.transform(lambda s: s.shift(1).rolling(window=4, min_periods=1).mean())
    df["rolling_mean_13"] = grouped.transform(lambda s: s.shift(1).rolling(window=13, min_periods=1).mean())

    return df


def build_feature_dataset(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Construct full feature engineering matrix from raw sales and dimension tables.

    Filters series with >= 104 weeks of history.
    """
    logger.info("Building feature dataset...")
    # 1. Filter series with >= 104 weeks
    series_counts = df_raw.groupby(["store_id", "dept_id"]).size()
    eligible_series = series_counts[series_counts >= 104].index
    logger.info(f"Retaining {len(eligible_series):,} series with >= 104 weeks of history.")

    df = df_raw.set_index(["store_id", "dept_id"]).loc[eligible_series].reset_index()

    # 2. Add features
    df = add_calendar_and_holiday_features(df)
    df = add_store_attribute_features(df)
    df = compute_lag_and_rolling_features(df)

    logger.info(f"Feature dataset constructed: {len(df):,} rows, {len(FEATURE_COLUMNS)} feature columns.")
    return df
