"""StockSense: Monte Carlo Inventory Risk Simulation Pipeline.

Simulates 10,000 runs per policy scenario across the top 20 revenue series.
Compares Monte Carlo optimal (s, S) policies against Textbook Formula (z=1.65)
and Fixed Weeks of Cover (2.5 Wks).
Persists results to SQL Server and generates figures.
"""

from __future__ import annotations

import sys
import logging
from datetime import datetime
from typing import List, Tuple
import numpy as np
import pandas as pd
from sqlalchemy import text

from src.config import get_db_engine, DATA_PROCESSED_DIR
from src.simulate_inventory import (
    run_simulation_grid_for_series,
    save_simulation_results_to_sql,
    generate_simulation_charts,
)

logger = logging.getLogger("stocksense.sim_pipeline")


def get_top_20_revenue_series() -> List[Tuple[int, int]]:
    """Query top 20 series by revenue from SQL Server view vw_top_series_revenue."""
    engine = get_db_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT TOP 20 store_id, dept_id 
            FROM dbo.vw_top_series_revenue 
            WHERE total_weeks >= 104
            ORDER BY total_revenue DESC;
        """)).fetchall()
        return [(int(r[0]), int(r[1])) for r in result]


def run_monte_carlo_pipeline(n_runs: int = 10000) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Execute inventory simulation across top 20 series."""
    start_time = datetime.now()
    logger.info("=" * 80)
    logger.info(f"STARTING STOCKSENSE MONTE CARLO SIMULATION ({n_runs:,} RUNS / SCENARIO)")
    logger.info("=" * 80)

    # Load forecast and residual data
    engine = get_db_engine()
    top_20 = get_top_20_revenue_series()
    logger.info(f"Loaded {len(top_20)} target series for inventory optimization.")

    residuals_df = pd.read_parquet(DATA_PROCESSED_DIR / "forecast_residuals.parquet")
    fact_sales = pd.read_parquet(DATA_PROCESSED_DIR / "fact_sales_weekly.parquet")

    # Load 13-week forecast horizon from best available backtest fold (Fold 4)
    forecasts_query = """
        SELECT store_id, dept_id, date_key, forecast, actual, model_name
        FROM dbo.fact_forecast
        WHERE fold_id = 4
        ORDER BY store_id, dept_id, date_key;
    """
    df_fc = pd.read_sql(forecasts_query, engine)

    all_summaries = []
    all_sample_paths = []

    for idx, (sid, did) in enumerate(top_20, 1):
        logger.info(f"Simulating Series {idx}/20: Store {sid}, Dept {did}...")

        # Get 13-week horizon (prefer Ridge Baseline or Holt-Winters from fold 4)
        sub_fc = df_fc[(df_fc["store_id"] == sid) & (df_fc["dept_id"] == did)]
        if sub_fc.empty:
            # Fallback to overall average weekly sales
            avg_sales = fact_sales[(fact_sales["store_id"] == sid) & (fact_sales["dept_id"] == did)]["weekly_sales"].mean()
            fc_horizon = np.full(13, avg_sales)
        else:
            # Pick Ridge Baseline or first available model
            model_sub = sub_fc[sub_fc["model_name"] == "Ridge Baseline"]
            if model_sub.empty:
                model_sub = sub_fc
            fc_horizon = model_sub.head(13)["forecast"].values

        # Get empirical residual ratios
        sub_res = residuals_df[(residuals_df["store_id"] == sid) & (residuals_df["dept_id"] == did)]
        if sub_res.empty:
            ratios = np.array([0.9, 0.95, 1.0, 1.05, 1.1])
        else:
            ratios = sub_res["residual_ratio"].values

        # Historical std of demand
        hist_std = float(fact_sales[(fact_sales["store_id"] == sid) & (fact_sales["dept_id"] == did)]["weekly_sales"].std())

        # Run grid simulation
        df_grid, paths = run_simulation_grid_for_series(
            store_id=sid,
            dept_id=did,
            forecast_horizon=fc_horizon,
            residual_ratios=ratios,
            historical_std=hist_std,
            n_runs=n_runs
        )

        all_summaries.append(df_grid)
        all_sample_paths.extend(paths)

    df_all_summaries = pd.concat(all_summaries, ignore_index=True)
    df_all_paths = pd.DataFrame(all_sample_paths)

    logger.info(f"Total scenario evaluation records: {len(df_all_summaries):,}")
    logger.info(f"Total trajectory sample points: {len(df_all_paths):,}")

    # Cache locally
    df_all_summaries.to_parquet(DATA_PROCESSED_DIR / "sim_summary.parquet", index=False)
    df_all_paths.to_parquet(DATA_PROCESSED_DIR / "sim_paths_sample.parquet", index=False)

    # Save to SQL Server
    save_simulation_results_to_sql(df_all_summaries, df_all_paths)

    # Generate charts (using top revenue series: Store 14, Dept 92)
    generate_simulation_charts(df_all_summaries, df_all_paths, representative_series=(14, 92))

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"Monte Carlo simulation pipeline completed successfully in {elapsed:.1f} seconds!")

    return df_all_summaries, df_all_paths


if __name__ == "__main__":
    run_monte_carlo_pipeline(n_runs=10000)
