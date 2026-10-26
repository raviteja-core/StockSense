"""StockSense: Results Persistence & Visualizations.

Writes forecasts, prediction intervals, and evaluation metrics back to SQL Server.
Caches walk-forward residual ratios for Monte Carlo simulation.
Generates evaluation charts and saves them to docs/figures/.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple
import numpy as np
import pandas as pd
import matplotlib
import os

if not os.environ.get("DISPLAY"):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from sqlalchemy import text

from src.config import get_db_engine, retry_on_db_error, DATA_PROCESSED_DIR, PROJECT_ROOT

logger = logging.getLogger("stocksense.write_results")
FIGURES_DIR = PROJECT_ROOT / "docs" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)


@retry_on_db_error()
def save_forecasts_and_metrics_to_sql(
    df_forecasts: pd.DataFrame,
    df_metrics: pd.DataFrame,
    chunksize: int = 5000
) -> None:
    """Save fact_forecast and fact_model_metrics to SQL Server with fast_executemany."""
    engine = get_db_engine()
    logger.info("Writing forecast actuals and metrics to SQL Server...")

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM dbo.fact_forecast;"))
        conn.execute(text("DELETE FROM dbo.fact_model_metrics;"))

        logger.info(f"Inserting {len(df_forecasts):,} rows into 'fact_forecast'...")
        # Subset exact columns matching schema
        fc_cols = [
            "store_id", "dept_id", "date_key", "model_name", "fold_id",
            "forecast", "lower_80", "upper_80", "actual", "error", "abs_error"
        ]
        df_forecasts[fc_cols].to_sql(
            name="fact_forecast", con=conn, if_exists="append", index=False, chunksize=chunksize
        )

        logger.info(f"Inserting {len(df_metrics):,} rows into 'fact_model_metrics'...")
        metric_cols = [
            "model_name", "store_id", "dept_id", "fold_id",
            "wape", "rmse", "mase", "bias", "eval_horizon_weeks"
        ]
        df_metrics[metric_cols].to_sql(
            name="fact_model_metrics", con=conn, if_exists="append", index=False, chunksize=chunksize
        )

    logger.info("Successfully updated fact_forecast and fact_model_metrics in SQL Server.")


def save_residual_ratios(df_forecasts: pd.DataFrame) -> Path:
    """Compute and cache walk-forward residual ratios (actual / forecast) per series.

    These empirical error ratios are bootstrapped in Phase 3 Monte Carlo simulation.
    """
    logger.info("Computing walk-forward residual ratios for simulation bootstrapping...")
    df = df_forecasts.copy()

    # Avoid zero division: clip forecast denominator
    safe_forecast = np.clip(df["forecast"].values, a_min=1.0, a_max=None)
    actuals = np.clip(df["actual"].values, a_min=0.0, a_max=None)
    df["residual_ratio"] = np.round(actuals / safe_forecast, 4)

    residuals_path = DATA_PROCESSED_DIR / "forecast_residuals.parquet"
    save_cols = ["store_id", "dept_id", "date_key", "model_name", "fold_id", "forecast", "actual", "residual_ratio"]
    df[save_cols].to_parquet(residuals_path, index=False)

    logger.info(f"Saved {len(df):,} residual ratio records to {residuals_path}.")
    return residuals_path


def generate_evaluation_figures(
    df_forecasts: pd.DataFrame,
    df_metrics: pd.DataFrame,
    example_series: List[Tuple[int, int]]
) -> None:
    """Generate and save the 3 required evaluation charts to docs/figures/."""
    logger.info("Generating evaluation charts in docs/figures/...")
    sns.set_theme(style="whitegrid", palette="muted")

    # --------------------------------------------------------------------------
    # Chart 1: Actual vs Forecast with 80% Prediction Interval for 3 Series
    # --------------------------------------------------------------------------
    fig, axes = plt.subplots(len(example_series), 1, figsize=(14, 4 * len(example_series)), sharex=False)
    if len(example_series) == 1:
        axes = [axes]

    for ax, (sid, did) in zip(axes, example_series):
        sub_fc = df_forecasts[(df_forecasts["store_id"] == sid) & (df_forecasts["dept_id"] == did)].copy()
        if sub_fc.empty:
            continue

        # Sort chronologically by date_key
        sub_fc = sub_fc.sort_values("date_key")
        dates = sub_fc[sub_fc["model_name"] == "Ridge Baseline"]["date_key"].astype(str)

        # Plot Actuals
        ridge_rows = sub_fc[sub_fc["model_name"] == "Ridge Baseline"]
        ax.plot(dates, ridge_rows["actual"].values, label="Actual Sales", color="black", linewidth=2.5, marker="o", markersize=4)

        # Plot Ridge Baseline
        ax.plot(dates, ridge_rows["forecast"].values, label="Ridge Baseline", color="#1f77b4", linestyle="--", linewidth=1.8)
        ax.fill_between(
            dates,
            ridge_rows["lower_80"].values,
            ridge_rows["upper_80"].values,
            color="#1f77b4",
            alpha=0.15,
            label="Ridge 80% Confidence Band"
        )

        # Plot Holt-Winters if available
        hw_rows = sub_fc[sub_fc["model_name"] == "Holt-Winters"]
        if not hw_rows.empty:
            ax.plot(dates, hw_rows["forecast"].values, label="Holt-Winters", color="#2ca02c", linestyle="-.", linewidth=1.8)

        # Plot Naive Seasonal
        naive_rows = sub_fc[sub_fc["model_name"] == "Naive Seasonal"]
        if not naive_rows.empty:
            ax.plot(dates, naive_rows["forecast"].values, label="Naive Seasonal", color="#d62728", linestyle=":", linewidth=1.5)

        ax.set_title(f"Walk-Forward Forecast vs. Actuals — Store {sid}, Dept {did} (52 Test Weeks)", fontsize=12, fontweight="bold")
        ax.set_ylabel("Weekly Sales ($)", fontsize=10)
        ax.set_xlabel("Date Key (YYYYMMDD)", fontsize=10)
        ax.tick_params(axis="x", rotation=45)
        ax.legend(loc="upper right", framealpha=0.9)

    plt.tight_layout()
    chart1_path = FIGURES_DIR / "actual_vs_forecast_examples.png"
    plt.savefig(chart1_path, dpi=300)
    plt.close()
    logger.info(f"Saved: {chart1_path}")

    # --------------------------------------------------------------------------
    # Chart 2: Model Comparison Boxplot (WAPE across series, fold_id = 0)
    # --------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 6))
    overall_metrics = df_metrics[df_metrics["fold_id"] == 0].copy()

    # Filter to common series present in all 3 models
    common_models = ["Naive Seasonal", "Ridge Baseline", "Holt-Winters"]
    valid_data = overall_metrics[overall_metrics["model_name"].isin(common_models)]

    palette = {"Naive Seasonal": "#d62728", "Ridge Baseline": "#1f77b4", "Holt-Winters": "#2ca02c"}
    sns.boxplot(
        data=valid_data,
        x="model_name",
        y="wape",
        palette=palette,
        ax=ax,
        width=0.45,
        showmeans=True,
        meanprops={"marker": "D", "markerfacecolor": "yellow", "markeredgecolor": "black", "markersize": 7}
    )

    ax.set_title("Forecast Accuracy Distribution (WAPE) across Top 100 Revenue Series", fontsize=13, fontweight="bold")
    ax.set_xlabel("Model", fontsize=11)
    ax.set_ylabel("WAPE (Lower is Better)", fontsize=11)
    ax.set_ylim(0.0, min(0.40, valid_data["wape"].quantile(0.98) * 1.25))

    # Add text annotations for medians
    medians = valid_data.groupby("model_name")["wape"].median()
    for idx, (mname, med) in enumerate(medians.items()):
        ax.text(idx, med + 0.008, f"Median: {med:.1%}", horizontalalignment="center", fontweight="bold", fontsize=10)

    plt.tight_layout()
    chart2_path = FIGURES_DIR / "model_comparison_boxplot.png"
    plt.savefig(chart2_path, dpi=300)
    plt.close()
    logger.info(f"Saved: {chart2_path}")

    # --------------------------------------------------------------------------
    # Chart 3: Forecast Error by Horizon (Week 1 through Week 13)
    # --------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    df_horizon = df_forecasts.copy()
    # Assign horizon week 1..13 within each fold
    df_horizon["horizon_week"] = df_horizon.groupby(["model_name", "store_id", "dept_id", "fold_id"]).cumcount() + 1

    horizon_wape = df_horizon.groupby(["model_name", "horizon_week"]).apply(
        lambda g: np.sum(np.abs(g["actual"] - g["forecast"])) / np.sum(g["actual"])
    ).reset_index(name="wape")

    for mname in common_models:
        sub_h = horizon_wape[horizon_wape["model_name"] == mname]
        if not sub_h.empty:
            ax.plot(sub_h["horizon_week"], sub_h["wape"], label=mname, marker="o", linewidth=2.2, color=palette.get(mname))

    ax.set_title("Forecast Error (WAPE) Degradation across 13-Week Horizon", fontsize=13, fontweight="bold")
    ax.set_xlabel("Forecast Horizon (Weeks Ahead)", fontsize=11)
    ax.set_ylabel("Aggregate WAPE", fontsize=11)
    ax.set_xticks(range(1, 14))
    ax.legend(title="Model", framealpha=0.9)

    plt.tight_layout()
    chart3_path = FIGURES_DIR / "error_by_horizon.png"
    plt.savefig(chart3_path, dpi=300)
    plt.close()
    logger.info(f"Saved: {chart3_path}")
