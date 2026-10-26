# %% [markdown]
# # StockSense — Phase 2: Demand Forecasting & Walk-Forward Validation
# **Project:** Demand Forecasting & Inventory Risk Simulator  
# **Dataset:** Walmart Recruiting - Store Sales Forecasting (Kaggle)  
# **Scope:** Top 100 Revenue Store $\times$ Department Series  
# 
# ### Objectives:
# 1. **Feature Engineering:** Autoregressive lags (1, 2, 4, 52), rolling means (4, 13 wks), calendar/holiday signals, exogenous markdowns and macro variables.
# 2. **Models Evaluated:**
#    - **Naive Seasonal:** Same week last year benchmark ($y_{t-52}$).
#    - **Ridge Baseline:** Regularized linear regression with recursive multi-step forecasting.
#    - **Holt-Winters:** Additive seasonal (52 periods) exponential smoothing per series.
# 3. **Validation Strategy:** 4-fold walk-forward cross-validation (52 total test weeks), strictly leakage-free.
# 4. **Metrics:** WAPE (primary), RMSE, MASE, Bias.

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

from src.forecast_pipeline import run_forecasting_pipeline
from src.config import DATA_PROCESSED_DIR

# %%
print("Executing Phase 2 Forecasting Pipeline...")
df_forecasts, df_metrics, summary_df = run_forecasting_pipeline(top_n_series=100)

# %%
print("\n=== OVERALL MODEL PERFORMANCE SUMMARY (TOP 100 SERIES) ===")
print(summary_df.to_string(index=False))

# %%
# Head of forecasts
print("\nSample Forecasts with 80% Prediction Intervals:")
print(df_forecasts.head(10).to_string(index=False))

# %%
# Head of metrics
print("\nSample Fold Metrics per Series:")
print(df_metrics[df_metrics["fold_id"] == 0].head(10).to_string(index=False))
