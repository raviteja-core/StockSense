"""StockSense: End-to-End Demand Forecasting Pipeline.

Executes walk-forward cross-validation (4 folds x 13-week test horizons) comparing:
1. Naive Seasonal Benchmark
2. Regularized Ridge Regression Baseline
3. Holt-Winters Exponential Smoothing

Evaluates WAPE, RMSE, MASE, and Bias across top 100 revenue series.
Persists forecasts and metrics to SQL Server and generates charts.
"""

from __future__ import annotations

import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple
import numpy as np
import pandas as pd

from src.config import DATA_PROCESSED_DIR, DATA_RAW_DIR
from src.features import build_feature_dataset
from src.forecast_baseline import predict_naive_seasonal, RidgeForecaster
from src.forecast_timeseries import predict_timeseries_fold
from src.evaluate import evaluate_forecast_dataframe
from src.write_results import (
    save_forecasts_and_metrics_to_sql,
    save_residual_ratios,
    generate_evaluation_figures,
)

logger = logging.getLogger("stocksense.forecast_pipeline")


def get_top_n_series(df: pd.DataFrame, n: int = 100) -> List[Tuple[int, int]]:
    """Identify top N Store x Dept series by total revenue."""
    series_rev = (
        df.groupby(["store_id", "dept_id"])["weekly_sales"]
        .sum()
        .sort_values(ascending=False)
        .head(n)
        .index.tolist()
    )
    return series_rev


def run_forecasting_pipeline(top_n_series: int = 100) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Execute the full 4-fold walk-forward forecasting pipeline."""
    start_time = datetime.now()
    logger.info("=" * 80)
    logger.info("STARTING STOCKSENSE DEMAND FORECASTING PIPELINE")
    logger.info("=" * 80)

    # 1. Load data
    fact_sales = pd.read_parquet(DATA_PROCESSED_DIR / "fact_sales_weekly.parquet")
    dim_date = pd.read_parquet(DATA_PROCESSED_DIR / "dim_date.parquet")
    dim_store = pd.read_parquet(DATA_PROCESSED_DIR / "dim_store.parquet")

    df_raw = fact_sales.merge(dim_date, on="date_key", how="inner")
    df_raw = df_raw.merge(dim_store, on="store_id", how="inner")
    df_raw["full_date"] = pd.to_datetime(df_raw["full_date"])
    df_raw = df_raw.sort_values(["store_id", "dept_id", "full_date"]).reset_index(drop=True)

    # 2. Build feature matrix (filters series >= 104 weeks)
    df_features = build_feature_dataset(df_raw)

    # 3. Select top N series by revenue for fair model benchmark
    target_series = get_top_n_series(df_features, n=top_n_series)
    logger.info(f"Targeting top {len(target_series)} revenue series for model comparison.")

    # Filter feature dataset to the evaluation series
    df_eval = df_features[
        df_features.set_index(["store_id", "dept_id"]).index.isin(target_series)
    ].copy()

    # 4. Define 4 walk-forward folds of 13-week test windows
    # Total unique dates = 143
    unique_dates = np.sort(df_eval["full_date"].unique())
    n_dates = len(unique_dates)  # 143

    # 4 test windows of 13 weeks each:
    # Fold 1: train 0..90 (91 wks), test 91..103 (13 wks)
    # Fold 2: train 0..103 (104 wks), test 104..116 (13 wks)
    # Fold 3: train 0..116 (117 wks), test 117..129 (13 wks)
    # Fold 4: train 0..129 (130 wks), test 130..142 (13 wks)
    fold_splits = [
        (1, 91, 104),   # Fold 1
        (2, 104, 117),  # Fold 2
        (3, 117, 130),  # Fold 3
        (4, 130, 143),  # Fold 4
    ]

    all_forecasts_list = []

    for fold_id, train_end_idx, test_end_idx in fold_splits:
        train_dates = unique_dates[:train_end_idx]
        test_dates = unique_dates[train_end_idx:test_end_idx]

        train_start = pd.to_datetime(train_dates[0]).strftime("%Y-%m-%d")
        train_end = pd.to_datetime(train_dates[-1]).strftime("%Y-%m-%d")
        test_start = pd.to_datetime(test_dates[0]).strftime("%Y-%m-%d")
        test_end = pd.to_datetime(test_dates[-1]).strftime("%Y-%m-%d")

        logger.info(
            f"--- Walk-Forward Fold {fold_id}/4 ---"
            f"\n  Train: {train_start} to {train_end} ({len(train_dates)} weeks)"
            f"\n  Test:  {test_start} to {test_end} ({len(test_dates)} weeks)"
        )

        df_train = df_eval[df_eval["full_date"].isin(train_dates)].copy()
        df_test = df_eval[df_eval["full_date"].isin(test_dates)].copy()
        df_test["fold_id"] = fold_id

        # Model 1: Naive Seasonal Benchmark
        logger.info(f"  Fitting Model 1: Naive Seasonal (Fold {fold_id})...")
        naive_preds = predict_naive_seasonal(df_train, df_test)
        all_forecasts_list.append(naive_preds)

        # Model 2: Ridge Regression Baseline
        logger.info(f"  Fitting Model 2: Ridge Baseline (Fold {fold_id})...")
        ridge_model = RidgeForecaster(alpha=10.0).fit(df_train)
        ridge_preds = ridge_model.predict_fold(df_train, df_test, fold_id=fold_id)
        all_forecasts_list.append(ridge_preds)

        # Model 3: Holt-Winters Exponential Smoothing
        logger.info(f"  Fitting Model 3: Holt-Winters Time-Series (Fold {fold_id})...")
        hw_preds = predict_timeseries_fold(
            df_train, df_test, fold_id=fold_id, target_series=target_series
        )
        all_forecasts_list.append(hw_preds)

    # 5. Aggregate all forecasts
    df_all_forecasts = pd.concat(all_forecasts_list, ignore_index=True)
    logger.info(f"Total forecast records generated: {len(df_all_forecasts):,}")

    # 6. Evaluate metrics
    df_metrics, summary_df = evaluate_forecast_dataframe(df_all_forecasts)

    logger.info("\n" + "=" * 80)
    logger.info("MODEL PERFORMANCE COMPARISON (TOP 100 SERIES — 4 FOLDS x 13 WEEKS):")
    logger.info("=" * 80)
    print("\n" + summary_df.to_string(index=False) + "\n")

    # 7. Persist to SQL Server
    save_forecasts_and_metrics_to_sql(df_all_forecasts, df_metrics)

    # 8. Cache residual ratios for Phase 3 Monte Carlo simulation
    save_residual_ratios(df_all_forecasts)

    # 9. Generate figures for top 3 revenue series
    example_series = target_series[:3]  # (14, 92), (2, 92), (20, 92)
    generate_evaluation_figures(df_all_forecasts, df_metrics, example_series)

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"Forecasting pipeline completed successfully in {elapsed:.1f} seconds!")

    return df_all_forecasts, df_metrics, summary_df


if __name__ == "__main__":
    run_forecasting_pipeline(top_n_series=100)
