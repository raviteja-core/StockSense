"""StockSense: Walk-Forward Backtest Evaluation & Metrics Engine.

Computes WAPE, RMSE, MASE, and Bias across rolling origin backtest folds.
Produces comprehensive metrics distribution summaries (median, IQR, mean)
and prepares data for SQL Server ingestion.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger("stocksense.evaluate")


def compute_wape(actuals: np.ndarray, forecasts: np.ndarray) -> float:
    """Calculate Weighted Absolute Percentage Error (WAPE).

    WAPE = Sum(|Actual - Forecast|) / Sum(Actual)
    Primary metric; robust to zero-demand weeks.
    """
    act = np.asarray(actuals, dtype=float)
    fc = np.asarray(forecasts, dtype=float)
    sum_actual = np.sum(act)
    if sum_actual == 0:
        return 0.0 if np.all(act == fc) else 1.0
    return float(np.sum(np.abs(act - fc)) / sum_actual)


def compute_rmse(actuals: np.ndarray, forecasts: np.ndarray) -> float:
    """Calculate Root Mean Squared Error (RMSE)."""
    act = np.asarray(actuals, dtype=float)
    fc = np.asarray(forecasts, dtype=float)
    return float(np.sqrt(np.mean((act - fc) ** 2)))


def compute_mase(
    actuals: np.ndarray,
    forecasts: np.ndarray,
    naive_forecasts: np.ndarray
) -> float:
    """Calculate Mean Absolute Scaled Error (MASE) relative to naive seasonal."""
    act = np.asarray(actuals, dtype=float)
    fc = np.asarray(forecasts, dtype=float)
    naive = np.asarray(naive_forecasts, dtype=float)

    mae_model = float(np.mean(np.abs(act - fc)))
    mae_naive = float(np.mean(np.abs(act - naive)))

    if mae_naive == 0.0:
        return 1.0 if mae_model == 0.0 else 2.0
    return float(mae_model / mae_naive)


def compute_bias(actuals: np.ndarray, forecasts: np.ndarray) -> float:
    """Calculate Mean Signed Error (Bias).

    Positive indicates systematic over-forecasting; negative indicates under-forecasting.
    """
    act = np.asarray(actuals, dtype=float)
    fc = np.asarray(forecasts, dtype=float)
    return float(np.mean(fc - act))


def evaluate_forecast_dataframe(
    df_forecasts: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate WAPE, RMSE, MASE, and Bias per model, series, and fold.

    Returns:
        (metrics_df, summary_stats_df)
    """
    logger.info("Computing evaluation metrics per series and fold...")

    # Group by model, store, dept, fold
    naive_lookup = (
        df_forecasts[df_forecasts["model_name"] == "Naive Seasonal"]
        .set_index(["store_id", "dept_id", "fold_id", "date_key"])["forecast"]
        .to_dict()
    )

    metric_rows = []
    grouped = df_forecasts.groupby(["model_name", "store_id", "dept_id", "fold_id"])

    for (model, sid, did, fold), group in grouped:
        actuals = group["actual"].values
        forecasts = group["forecast"].values

        # Retrieve aligned naive seasonal forecasts for MASE
        naive_fcs = np.array([
            naive_lookup.get((sid, did, fold, dk), actuals[idx])
            for idx, dk in enumerate(group["date_key"].values)
        ])

        w = compute_wape(actuals, forecasts)
        r = compute_rmse(actuals, forecasts)
        m = compute_mase(actuals, forecasts, naive_fcs)
        b = compute_bias(actuals, forecasts)

        metric_rows.append({
            "model_name": model,
            "store_id": int(sid),
            "dept_id": int(did),
            "fold_id": int(fold),
            "wape": round(w, 4),
            "rmse": round(r, 2),
            "mase": round(m, 4),
            "bias": round(b, 2),
            "eval_horizon_weeks": len(group)
        })

    df_fold_metrics = pd.DataFrame(metric_rows)

    # Compute overall fold_id = 0 metrics averaged across the 4 folds
    overall_rows = []
    overall_grouped = df_forecasts.groupby(["model_name", "store_id", "dept_id"])
    for (model, sid, did), group in overall_grouped:
        actuals = group["actual"].values
        forecasts = group["forecast"].values
        naive_fcs = np.array([
            naive_lookup.get((sid, did, fold, dk), actuals[idx])
            for idx, (fold, dk) in enumerate(zip(group["fold_id"].values, group["date_key"].values))
        ])

        w = compute_wape(actuals, forecasts)
        r = compute_rmse(actuals, forecasts)
        m = compute_mase(actuals, forecasts, naive_fcs)
        b = compute_bias(actuals, forecasts)

        overall_rows.append({
            "model_name": model,
            "store_id": int(sid),
            "dept_id": int(did),
            "fold_id": 0,  # 0 indicates full backtest evaluation
            "wape": round(w, 4),
            "rmse": round(r, 2),
            "mase": round(m, 4),
            "bias": round(b, 2),
            "eval_horizon_weeks": len(group)
        })

    df_all_metrics = pd.concat([df_fold_metrics, pd.DataFrame(overall_rows)], ignore_index=True)

    # Summary distribution statistics (Overall fold_id = 0)
    summary_list = []
    for model, grp in df_all_metrics[df_all_metrics["fold_id"] == 0].groupby("model_name"):
        summary_list.append({
            "Model": model,
            "Series Count": len(grp),
            "Mean WAPE": round(grp["wape"].mean(), 4),
            "Median WAPE": round(grp["wape"].median(), 4),
            "P25 WAPE": round(grp["wape"].quantile(0.25), 4),
            "P75 WAPE": round(grp["wape"].quantile(0.75), 4),
            "Mean RMSE": round(grp["rmse"].mean(), 2),
            "Median RMSE": round(grp["rmse"].median(), 2),
            "Median MASE": round(grp["mase"].median(), 4),
            "Mean Bias": round(grp["bias"].mean(), 2),
            "Median Bias": round(grp["bias"].median(), 2)
        })

    summary_df = pd.DataFrame(summary_list).sort_values("Median WAPE")
    return df_all_metrics, summary_df
