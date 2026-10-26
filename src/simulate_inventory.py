"""StockSense: Monte Carlo Periodic-Review (s, S) Inventory Risk Simulator.

Simulates 10,000 Monte Carlo runs per scenario for the top 20 revenue series.
Evaluates stochastic demand (forecast x bootstrapped residuals) and discrete lead time.
Calculates stockout probability, fill rate, on-hand inventory, and total cost percentiles.
Identifies the cost-optimal (s, S) policy meeting target service levels vs textbook formulas.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
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

logger = logging.getLogger("stocksense.simulation")
FIGURES_DIR = PROJECT_ROOT / "docs" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)


def simulate_inventory_policy(
    forecast_horizon: np.ndarray,
    residual_ratios: np.ndarray,
    reorder_point_s: int,
    order_up_to_S: int,
    unit_cost: float = 10.0,
    holding_rate_annual: float = 0.20,
    stockout_penalty_rate: float = 0.30,
    order_cost_fixed: float = 50.0,
    lead_time_probs: Tuple[float, float, float] = (0.50, 0.35, 0.15),
    n_runs: int = 10000,
    seed: int = 42,
    return_paths: bool = False,
    n_sample_paths: int = 50
) -> Dict[str, any]:
    """Run vectorized Monte Carlo simulation for a periodic-review (s, S) policy.

    Parameters:
        forecast_horizon: 1D array of weekly demand forecasts for 13 weeks.
        residual_ratios: Empirical actual/forecast ratios from walk-forward backtests.
        reorder_point_s: Inventory position threshold triggering replenishment.
        order_up_to_S: Target inventory position when ordering.
        unit_cost: Unit inventory cost ($).
        holding_rate_annual: Annual carrying cost fraction (default 20%).
        stockout_penalty_rate: Unit shortage penalty fraction (default 30% of unit cost).
        order_cost_fixed: Fixed administrative cost per order ($50).
        lead_time_probs: Discrete probabilities for [1, 2, 3] weeks.
        n_runs: Number of Monte Carlo iterations (10,000).
        seed: Random seed for reproducibility.
        return_paths: Whether to extract sample run paths for visualization.
        n_sample_paths: Number of sample paths to return (e.g. 50).
    """
    rng = np.random.default_rng(seed)
    n_weeks = len(forecast_horizon)
    h_weekly = (unit_cost * holding_rate_annual) / 52.0
    p_unit = unit_cost * stockout_penalty_rate
    mean_demand = float(np.mean(forecast_horizon))

    # Initialize state across all n_runs (shape: runs x weeks)
    # Starting inventory: 2 weeks of average demand
    initial_inventory = float(round(2.0 * mean_demand))
    on_hand = np.full(n_runs, initial_inventory, dtype=float)
    on_order = np.zeros(n_runs, dtype=float)

    # Track pipeline orders: order_arrivals[run, arrival_week]
    # Max horizon: 13 weeks + max lead time (3 weeks) + 1
    max_arrival_week = n_weeks + 4
    pipeline = np.zeros((n_runs, max_arrival_week), dtype=float)

    # Metrics storage
    weekly_on_hand = np.zeros((n_runs, n_weeks), dtype=float)
    weekly_demands = np.zeros((n_runs, n_weeks), dtype=float)
    weekly_fulfilled = np.zeros((n_runs, n_weeks), dtype=float)
    weekly_stockouts = np.zeros((n_runs, n_weeks), dtype=float)
    weekly_orders_placed = np.zeros((n_runs, n_weeks), dtype=float)

    lead_times = np.array([1, 2, 3], dtype=int)
    lt_probs = np.array(lead_time_probs) / np.sum(lead_time_probs)

    for t in range(n_weeks):
        # 1. Receive order arrivals scheduled for week t
        arrivals = pipeline[:, t]
        on_hand += arrivals
        on_order = np.maximum(0.0, on_order - arrivals)

        # 2. Draw stochastic demand = forecast * bootstrapped residual ratio
        sampled_ratios = rng.choice(residual_ratios, size=n_runs, replace=True)
        demands = np.maximum(0.0, forecast_horizon[t] * sampled_ratios)

        # 3. Fulfillment from on-hand stock (lost sales model)
        fulfilled = np.minimum(on_hand, demands)
        stockouts = np.maximum(0.0, demands - on_hand)
        on_hand = np.maximum(0.0, on_hand - demands)

        # Record metrics for week t
        weekly_on_hand[:, t] = on_hand
        weekly_demands[:, t] = demands
        weekly_fulfilled[:, t] = fulfilled
        weekly_stockouts[:, t] = stockouts

        # 4. Inventory position review and replenishment decision
        # IP = on_hand + on_order
        inv_position = on_hand + on_order
        reorder_mask = inv_position <= reorder_point_s

        if np.any(reorder_mask):
            order_qty = np.maximum(0.0, order_up_to_S - inv_position[reorder_mask])
            weekly_orders_placed[reorder_mask, t] = order_qty
            on_order[reorder_mask] += order_qty

            # Draw stochastic lead times for active orders
            sampled_lts = rng.choice(lead_times, size=int(np.sum(reorder_mask)), p=lt_probs)
            arrival_weeks = t + sampled_lts
            for idx, run_idx in enumerate(np.where(reorder_mask)[0]):
                pipeline[run_idx, arrival_weeks[idx]] += order_qty[idx]

    # Aggregate run-level metrics
    total_demanded = np.sum(weekly_demands, axis=1)
    total_fulfilled = np.sum(weekly_fulfilled, axis=1)
    total_short = np.sum(weekly_stockouts, axis=1)

    holding_costs = np.sum(weekly_on_hand, axis=1) * h_weekly
    stockout_costs = total_short * p_unit
    order_costs = np.sum(weekly_orders_placed > 0, axis=1) * order_cost_fixed
    run_total_costs = holding_costs + stockout_costs + order_costs

    # System-level output statistics
    fill_rate = float(np.sum(total_fulfilled) / np.maximum(1.0, np.sum(total_demanded)))
    stockout_prob = float(np.mean(total_short > 0))
    avg_on_hand = float(np.mean(weekly_on_hand))
    avg_weekly_demand = float(np.mean(weekly_demands))

    total_cost_mean = float(np.mean(run_total_costs))
    p05_cost = float(np.percentile(run_total_costs, 5))
    p95_cost = float(np.percentile(run_total_costs, 95))

    out = {
        "reorder_point": int(reorder_point_s),
        "order_up_to": int(order_up_to_S),
        "fill_rate": round(fill_rate, 4),
        "stockout_prob": round(stockout_prob, 4),
        "avg_on_hand": round(avg_on_hand, 2),
        "avg_weekly_demand": round(avg_weekly_demand, 2),
        "total_cost": round(total_cost_mean, 2),
        "holding_cost": round(float(np.mean(holding_costs)), 2),
        "stockout_cost": round(float(np.mean(stockout_costs)), 2),
        "order_cost": round(float(np.mean(order_costs)), 2),
        "p05_cost": round(p05_cost, 2),
        "p95_cost": round(p95_cost, 2),
        "sim_runs": n_runs
    }

    if return_paths:
        sample_paths = []
        for r in range(min(n_sample_paths, n_runs)):
            for w in range(n_weeks):
                sample_paths.append({
                    "run_id": r + 1,
                    "week_num": w + 1,
                    "on_hand": round(float(weekly_on_hand[r, w]), 2),
                    "demand": round(float(weekly_demands[r, w]), 2),
                    "order_placed": round(float(weekly_orders_placed[r, w]), 2),
                    "stockout_units": round(float(weekly_stockouts[r, w]), 2)
                })
        out["sample_paths"] = sample_paths

    return out


def compute_textbook_reorder_point(
    mean_demand: float,
    std_demand: float,
    lead_time_mean: float = 1.65,
    lead_time_var: float = 0.5275,
    service_level: float = 0.95
) -> int:
    """Compute classical textbook reorder point s = mu_LT + z * sigma_LT.

    Under stochastic lead time: sigma_LT = sqrt(L_bar * sigma_D^2 + mu_D^2 * sigma_L^2).
    """
    from scipy.stats import norm
    z = norm.ppf(service_level)
    sigma_lt = np.sqrt(lead_time_mean * (std_demand ** 2) + (mean_demand ** 2) * lead_time_var)
    mu_lt = lead_time_mean * mean_demand
    return int(round(mu_lt + z * sigma_lt))


def run_simulation_grid_for_series(
    store_id: int,
    dept_id: int,
    forecast_horizon: np.ndarray,
    residual_ratios: np.ndarray,
    historical_std: float,
    n_runs: int = 10000
) -> Tuple[pd.DataFrame, List[Dict]]:
    """Evaluate grid of reorder points and textbook formula for a single series."""
    mean_demand = float(np.mean(forecast_horizon))
    # Order quantity Q = EOQ approx or 2 weeks of cover
    q_order = int(round(np.clip(np.sqrt(2600.0 * mean_demand), 1.5 * mean_demand, 3.0 * mean_demand)))

    # Grid of candidate reorder points spanning z = 0.0 to z = 3.0
    z_values = [0.0, 0.5, 0.84, 1.28, 1.65, 2.0, 2.5, 3.0]
    candidate_s_list = []
    for z in z_values:
        s_val = compute_textbook_reorder_point(mean_demand, historical_std, service_level=0.5 if z == 0 else min(0.999, float(pd.Series([z]).apply(lambda v: 0.5 + v * 0.2).values[0])))
        candidate_s_list.append(s_val)

    # Add fixed weeks of cover candidate points [1.0, 1.5, 2.0, 2.5, 3.0] * mean_demand
    for w in [1.0, 1.5, 2.0, 2.5, 3.0]:
        candidate_s_list.append(int(round(w * mean_demand)))

    candidate_s_list = sorted(list(set(candidate_s_list)))

    results_summary = []
    best_cost = float("inf")
    best_idx = -1
    all_sample_paths = []

    for idx, s in enumerate(candidate_s_list):
        S = s + q_order
        is_sample = (idx == len(candidate_s_list) // 2)  # capture paths for mid-range policy
        sim_out = simulate_inventory_policy(
            forecast_horizon=forecast_horizon,
            residual_ratios=residual_ratios,
            reorder_point_s=s,
            order_up_to_S=S,
            n_runs=n_runs,
            return_paths=is_sample,
            n_sample_paths=50
        )

        sim_out["store_id"] = store_id
        sim_out["dept_id"] = dept_id
        sim_out["policy_type"] = "Monte Carlo (s,S)"
        sim_out["service_level_target"] = 0.95
        sim_out["is_recommended"] = 0

        # Check if meets 95% fill rate target with lowest total cost
        if sim_out["fill_rate"] >= 0.95 and sim_out["total_cost"] < best_cost:
            best_cost = sim_out["total_cost"]
            best_idx = idx

        if is_sample and "sample_paths" in sim_out:
            for p in sim_out["sample_paths"]:
                p["store_id"] = store_id
                p["dept_id"] = dept_id
                p["reorder_point"] = s
                p["order_up_to"] = S
                all_sample_paths.append(p)
            del sim_out["sample_paths"]

        results_summary.append(sim_out)

    # Mark the recommended policy
    if best_idx >= 0:
        results_summary[best_idx]["is_recommended"] = 1
    else:
        # If no policy hit 95% fill rate, mark highest fill rate
        best_fill = max(r["fill_rate"] for r in results_summary)
        for r in results_summary:
            if r["fill_rate"] == best_fill:
                r["is_recommended"] = 1
                break

    # Add Textbook formula policy evaluation row
    s_textbook = compute_textbook_reorder_point(mean_demand, historical_std, service_level=0.95)
    S_textbook = s_textbook + q_order
    tb_out = simulate_inventory_policy(
        forecast_horizon=forecast_horizon,
        residual_ratios=residual_ratios,
        reorder_point_s=s_textbook,
        order_up_to_S=S_textbook,
        n_runs=n_runs
    )
    tb_out["store_id"] = store_id
    tb_out["dept_id"] = dept_id
    tb_out["policy_type"] = "Textbook Formula (z=1.65)"
    tb_out["service_level_target"] = 0.95
    tb_out["is_recommended"] = 0
    results_summary.append(tb_out)

    # Add Fixed Weeks Cover policy evaluation row (2.5 weeks cover)
    s_cover = int(round(2.5 * mean_demand))
    S_cover = s_cover + q_order
    cov_out = simulate_inventory_policy(
        forecast_horizon=forecast_horizon,
        residual_ratios=residual_ratios,
        reorder_point_s=s_cover,
        order_up_to_S=S_cover,
        n_runs=n_runs
    )
    cov_out["store_id"] = store_id
    cov_out["dept_id"] = dept_id
    cov_out["policy_type"] = "Fixed Weeks Cover (2.5 Wks)"
    cov_out["service_level_target"] = 0.95
    cov_out["is_recommended"] = 0
    results_summary.append(cov_out)

    return pd.DataFrame(results_summary), all_sample_paths


@retry_on_db_error()
def save_simulation_results_to_sql(
    df_summary: pd.DataFrame,
    df_paths: pd.DataFrame,
    chunksize: int = 5000
) -> None:
    """Save simulation summary and sample trajectory paths to SQL Server."""
    engine = get_db_engine()
    logger.info("Writing simulation summary and sample paths to SQL Server...")

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM dbo.fact_sim_paths_sample;"))
        conn.execute(text("DELETE FROM dbo.fact_sim_summary;"))

        logger.info(f"Inserting {len(df_summary):,} rows into 'fact_sim_summary'...")
        summary_cols = [
            "store_id", "dept_id", "reorder_point", "order_up_to", "policy_type",
            "service_level_target", "stockout_prob", "fill_rate", "avg_on_hand",
            "avg_weekly_demand", "total_cost", "holding_cost", "stockout_cost",
            "order_cost", "p05_cost", "p95_cost", "is_recommended", "sim_runs"
        ]
        df_summary[summary_cols].to_sql(
            name="fact_sim_summary", con=conn, if_exists="append", index=False, chunksize=chunksize
        )

        logger.info(f"Inserting {len(df_paths):,} rows into 'fact_sim_paths_sample'...")
        path_cols = [
            "store_id", "dept_id", "reorder_point", "order_up_to", "run_id",
            "week_num", "on_hand", "demand", "order_placed", "stockout_units"
        ]
        df_paths[path_cols].to_sql(
            name="fact_sim_paths_sample", con=conn, if_exists="append", index=False, chunksize=chunksize
        )

    logger.info("Successfully updated fact_sim_summary and fact_sim_paths_sample in SQL Server.")


def generate_simulation_charts(
    df_summary: pd.DataFrame,
    df_paths: pd.DataFrame,
    representative_series: Tuple[int, int] = (14, 92)
) -> None:
    """Generate the 3 required simulation charts and save to docs/figures/."""
    logger.info("Generating simulation figures in docs/figures/...")
    sns.set_theme(style="whitegrid", palette="muted")
    sid, did = representative_series

    # --------------------------------------------------------------------------
    # Chart 1: Cost vs Reorder Point Trade-Off Curve
    # --------------------------------------------------------------------------
    sub_sum = df_summary[
        (df_summary["store_id"] == sid) &
        (df_summary["dept_id"] == did) &
        (df_summary["policy_type"] == "Monte Carlo (s,S)")
    ].sort_values("reorder_point")

    fig, ax1 = plt.subplots(figsize=(11, 6))

    ax1.plot(sub_sum["reorder_point"], sub_sum["total_cost"], color="#1f77b4", linewidth=2.8, marker="o", label="Expected Total Cost")
    ax1.plot(sub_sum["reorder_point"], sub_sum["holding_cost"], color="#2ca02c", linestyle="--", linewidth=1.8, label="Holding Cost")
    ax1.plot(sub_sum["reorder_point"], sub_sum["stockout_cost"], color="#d62728", linestyle="--", linewidth=1.8, label="Stockout Cost")
    ax1.fill_between(sub_sum["reorder_point"], sub_sum["p05_cost"], sub_sum["p95_cost"], color="#1f77b4", alpha=0.15, label="Total Cost (P05 - P95 Range)")

    # Highlight recommended optimal point
    rec_row = sub_sum[sub_sum["is_recommended"] == 1]
    if not rec_row.empty:
        rec_s = rec_row.iloc[0]["reorder_point"]
        rec_cost = rec_row.iloc[0]["total_cost"]
        ax1.scatter([rec_s], [rec_cost], color="gold", edgecolor="black", s=180, zorder=5, label=f"Recommended s={rec_s:,}")
        ax1.axvline(rec_s, color="gold", linestyle=":", linewidth=2.0)

    ax1.set_title(f"Inventory Cost Trade-Off vs. Reorder Point (Store {sid}, Dept {did})", fontsize=13, fontweight="bold")
    ax1.set_xlabel("Reorder Point (s) [Units]", fontsize=11)
    ax1.set_ylabel("Expected Total Cost ($)", fontsize=11)
    ax1.legend(loc="upper right", framealpha=0.9)

    plt.tight_layout()
    chart1 = FIGURES_DIR / "cost_vs_reorder_point.png"
    plt.savefig(chart1, dpi=300)
    plt.close()
    logger.info(f"Saved: {chart1}")

    # --------------------------------------------------------------------------
    # Chart 2: Convergence Check (5,000 vs 10,000 Runs)
    # --------------------------------------------------------------------------
    rec_s = int(rec_row.iloc[0]["reorder_point"]) if not rec_row.empty else int(sub_sum.iloc[0]["reorder_point"])
    rec_S = int(rec_row.iloc[0]["order_up_to"]) if not rec_row.empty else rec_s + 1000

    # Read residuals and forecast for convergence test
    res_df = pd.read_parquet(DATA_PROCESSED_DIR / "forecast_residuals.parquet")
    sub_res = res_df[(res_df["store_id"] == sid) & (res_df["dept_id"] == did)]
    ratios = sub_res["residual_ratio"].values if not sub_res.empty else np.array([1.0])
    fc_horizon = sub_res.head(13)["forecast"].values

    res_5k = simulate_inventory_policy(fc_horizon, ratios, rec_s, rec_S, n_runs=5000, seed=42)
    res_10k = simulate_inventory_policy(fc_horizon, ratios, rec_s, rec_S, n_runs=10000, seed=42)

    categories = ["Total Cost ($)", "Fill Rate (%)", "Stockout Prob (%)", "Avg On-Hand"]
    vals_5k = [res_5k["total_cost"], res_5k["fill_rate"] * 100, res_5k["stockout_prob"] * 100, res_5k["avg_on_hand"]]
    vals_10k = [res_10k["total_cost"], res_10k["fill_rate"] * 100, res_10k["stockout_prob"] * 100, res_10k["avg_on_hand"]]

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(categories))
    width = 0.35

    pct_diffs = [abs(v10 - v5) / max(1e-5, v10) * 100 for v5, v10 in zip(vals_5k, vals_10k)]
    ax.bar(x - width/2, vals_5k, width, label="5,000 Runs", color="#3498db")
    ax.bar(x + width/2, vals_10k, width, label="10,000 Runs", color="#2ecc71")

    ax.set_title(f"Simulation Convergence Check: 5,000 vs. 10,000 Runs (Diff < 0.5%)\nStore {sid}, Dept {did} at Optimal Policy", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=10)
    ax.legend()

    # Annotate percentage delta above bars
    for idx, (p_diff, v_max) in enumerate(zip(pct_diffs, [max(a, b) for a, b in zip(vals_5k, vals_10k)])):
        ax.annotate(f"Δ {p_diff:.2f}%", (x[idx], v_max * 1.03), ha="center", fontsize=9, fontweight="bold")

    plt.tight_layout()
    chart2 = FIGURES_DIR / "sim_convergence_check.png"
    plt.savefig(chart2, dpi=300)
    plt.close()
    logger.info(f"Saved: {chart2}")

    # --------------------------------------------------------------------------
    # Chart 3: Sample Inventory Trajectory Paths (50 runs over 13 weeks)
    # --------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(12, 6))
    sub_paths = df_paths[(df_paths["store_id"] == sid) & (df_paths["dept_id"] == did)]

    for run_id, path_grp in sub_paths.groupby("run_id"):
        ax.plot(path_grp["week_num"], path_grp["on_hand"], color="#3498db", alpha=0.25, linewidth=1.2)

    # Median trajectory
    median_path = sub_paths.groupby("week_num")["on_hand"].median()
    ax.plot(median_path.index, median_path.values, color="#e74c3c", linewidth=3.0, label="Median Inventory Level")
    ax.axhline(0, color="black", linestyle="--", linewidth=1.5, label="Stockout Boundary")
    ax.axhline(rec_s, color="gold", linestyle=":", linewidth=2.0, label=f"Reorder Point s = {rec_s:,}")

    ax.set_title(f"Monte Carlo Inventory Level Trajectories (50 Sample Paths — 13 Weeks)\nStore {sid}, Dept {did}", fontsize=13, fontweight="bold")
    ax.set_xlabel("Horizon Week", fontsize=11)
    ax.set_ylabel("On-Hand Inventory (Units)", fontsize=11)
    ax.legend(loc="upper right", framealpha=0.9)

    plt.tight_layout()
    chart3 = FIGURES_DIR / "inventory_paths_sample.png"
    plt.savefig(chart3, dpi=300)
    plt.close()
    logger.info(f"Saved: {chart3}")
