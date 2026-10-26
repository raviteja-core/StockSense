# %% [markdown]
# # StockSense — Phase 3: Monte Carlo Inventory Risk Simulation
# **Project:** Demand Forecasting & Inventory Risk Simulator  
# **Scope:** Top 20 Revenue Store $\times$ Department Series  
# **Iterations:** 10,000 Monte Carlo runs per policy scenario  
# 
# ### Objectives:
# 1. **Periodic-Review $(s, S)$ Inventory Simulation:**
#    - Weekly review cycle with stochastic discrete lead times (1 wk 50%, 2 wks 35%, 3 wks 15%).
#    - Non-normal demand generated via empirical walk-forward residual bootstrapping.
# 2. **Policy Evaluation:**
#    - Grid of reorder points $s$ comparing stockout probability, fill rate, and total cost percentiles (P05, P50, P95).
#    - Optimal cost policy selection meeting 95% fill rate target.
#    - Head-to-head comparison against Textbook Formula ($s = \mu_{LT} + z \sigma_{LT}$) and Fixed Weeks of Cover.
# 3. **Convergence Validation:**
#    - Stability check between 5,000 and 10,000 runs (< 0.5% delta).

# %%
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
if not os.environ.get("DISPLAY"):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

root_dir = Path(__file__).resolve().parent.parent if "__file__" in locals() else (
    Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
)
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.sim_pipeline import run_monte_carlo_pipeline
from src.config import DATA_PROCESSED_DIR

# %%
print("Executing Phase 3 Monte Carlo Simulation...")
df_sim_summary, df_sim_paths = run_monte_carlo_pipeline(n_runs=10000)

# %%
# Policy Comparison for Top Revenue Series (Store 14, Dept 92)
s14_d92 = df_sim_summary[(df_sim_summary["store_id"] == 14) & (df_sim_summary["dept_id"] == 92)]
print("\n=== INVENTORY POLICY GRID FOR STORE 14, DEPT 92 ===")
cols = ["policy_type", "reorder_point", "order_up_to", "fill_rate", "stockout_prob", "avg_on_hand", "total_cost", "p05_cost", "p95_cost", "is_recommended"]
print(s14_d92[cols].to_string(index=False))

# %%
# Optimal Policy Summary Across All Top 20 Series
print("\n=== RECOMMENDED OPTIMAL POLICIES ACROSS ALL TOP 20 SERIES ===")
rec_df = df_sim_summary[df_sim_summary["is_recommended"] == 1]
rec_cols = ["store_id", "dept_id", "reorder_point", "order_up_to", "fill_rate", "stockout_prob", "avg_on_hand", "total_cost", "p05_cost", "p95_cost"]
print(rec_df[rec_cols].to_string(index=False))
