# %% [markdown]
# # StockSense — Phase 1: Exploratory Data Analysis (EDA)
# **Project:** Demand Forecasting & Inventory Risk Simulator  
# **Dataset:** Walmart Recruiting - Store Sales Forecasting (Kaggle)  
# **Unit of Analysis:** Store $\times$ Department Weekly Series  

# %%
import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
# Use Agg backend if running in headless terminal environment
if not os.environ.get("DISPLAY"):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style="whitegrid", palette="muted")
plt.rcParams["figure.figsize"] = (12, 6)

root_dir = Path(__file__).resolve().parent.parent if "__file__" in locals() else (
    Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
)
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.config import DATA_PROCESSED_DIR, DATA_RAW_DIR
from src.load_data import HOLIDAY_MAP, build_star_schema

# %%
print("=" * 80)
print("STOCKSENSE PHASE 1: EXPLORATORY DATA ANALYSIS (EDA)")
print("=" * 80)

# Check for processed parquet cache, else read directly from raw
parquet_path = DATA_PROCESSED_DIR / "fact_sales_weekly.parquet"
if not parquet_path.exists():
    print("Processed parquet not found. Running build_star_schema on raw CSVs...")
    dim_store, dim_date, fact_sales, param_inv = build_star_schema(DATA_RAW_DIR)
else:
    print(f"Loading cached parquet files from {DATA_PROCESSED_DIR}...")
    fact_sales = pd.read_parquet(DATA_PROCESSED_DIR / "fact_sales_weekly.parquet")
    dim_date = pd.read_parquet(DATA_PROCESSED_DIR / "dim_date.parquet")
    dim_store = pd.read_parquet(DATA_PROCESSED_DIR / "dim_store.parquet")

df = fact_sales.merge(dim_date, on="date_key", how="inner")
df = df.merge(dim_store, on="store_id", how="inner")
df["full_date"] = pd.to_datetime(df["full_date"])
df = df.sort_values(["store_id", "dept_id", "full_date"]).reset_index(drop=True)

# %%
# 1. Scope & Cardinality
min_date = df["full_date"].min().strftime("%Y-%m-%d")
max_date = df["full_date"].max().strftime("%Y-%m-%d")
unique_weeks = df["full_date"].nunique()
num_stores = df["store_id"].nunique()
num_depts = df["dept_id"].nunique()
series_df = df.groupby(["store_id", "dept_id"]).size().reset_index(name="week_count")
total_series = len(series_df)

print("\n--- 1. DATASET SCOPE & CARDINALITY ---")
print(f"Total Sales Records (Rows): {len(df):,}")
print(f"Date Range: {min_date} to {max_date} ({unique_weeks} reporting weeks)")
print(f"Number of Unique Stores: {num_stores}")
print(f"Number of Unique Departments: {num_depts}")
print(f"Total Store-Department Series: {total_series:,}")

# %%
# 2. Negative Weekly Sales (Returns) Audit
neg_sales = df[df["weekly_sales"] < 0]
neg_count = len(neg_sales)
total_count = len(df)
neg_pct = (neg_count / total_count) * 100

print("\n--- 2. NEGATIVE SALES & RETURNS AUDIT ---")
print(f"Negative Sales Records: {neg_count:,} out of {total_count:,} ({neg_pct:.3f}%)")
if neg_count > 0:
    print(f"Minimum Sales Value (Largest Return): ${neg_sales['weekly_sales'].min():,.2f}")
    print(f"Total Dollar Volume of Returns: ${neg_sales['weekly_sales'].sum():,.2f}")
    print(f"Average Return Size: ${neg_sales['weekly_sales'].mean():,.2f}")

# %%
# 3. Series Continuity & Length Filtering (>= 104 Weeks)
series_104 = series_df[series_df["week_count"] >= 104]
count_104 = len(series_104)
pct_104 = (count_104 / total_series) * 100
full_143 = (series_df["week_count"] == unique_weeks).sum()

print("\n--- 3. SERIES CONTINUITY & FILTERING ---")
print(f"Series with full {unique_weeks} weeks: {full_143:,} ({(full_143 / total_series) * 100:.1f}%)")
print(f"Series with >= 104 weeks (>= 2 full years): {count_104:,} ({pct_104:.1f}%)")
print(f"Series dropped (< 104 weeks): {total_series - count_104:,} ({100 - pct_104:.1f}%)")

# %%
# 4. Holiday Lift Analysis
hol_stats = df.groupby("is_holiday_week")["weekly_sales"].agg(["count", "mean", "median"]).reset_index()
non_hol_mean = hol_stats.loc[hol_stats["is_holiday_week"] == 0, "mean"].values[0]
hol_mean = hol_stats.loc[hol_stats["is_holiday_week"] == 1, "mean"].values[0]
lift = ((hol_mean / non_hol_mean) - 1) * 100

print("\n--- 4. HOLIDAY EFFECTS ---")
print(f"Non-Holiday Average Weekly Sales: ${non_hol_mean:,.2f}")
print(f"Holiday Average Weekly Sales:     ${hol_mean:,.2f}")
print(f"Overall Holiday Sales Lift:       +{lift:.2f}%")

named = df[df["holiday_name"].notna()].groupby("holiday_name")["weekly_sales"].agg(["count", "mean"]).reset_index()
named["lift_pct"] = ((named["mean"] / non_hol_mean) - 1) * 100
named = named.sort_values("mean", ascending=False)
print("\nNamed Holiday Event Breakdown:")
for _, r in named.iterrows():
    print(f" - {r['holiday_name']:<14}: ${r['mean']:,.2f} ({r['lift_pct']:+.1f}% vs baseline)")

# %%
# 5. Top 20 Store-Department Series by Historical Revenue (Qualified >= 104 weeks)
qualified_series = series_104[["store_id", "dept_id"]]
df_qual = df.merge(qualified_series, on=["store_id", "dept_id"], how="inner")

top20 = df_qual.groupby(["store_id", "dept_id", "store_type"]).agg(
    total_revenue=("weekly_sales", "sum"),
    mean_weekly_sales=("weekly_sales", "mean"),
    std_weekly_sales=("weekly_sales", "std"),
    weeks_available=("weekly_sales", "count")
).reset_index()

top20["cv_demand"] = (top20["std_weekly_sales"] / top20["mean_weekly_sales"]).round(3)
top20 = top20.sort_values("total_revenue", ascending=False).reset_index(drop=True)
top20["revenue_rank"] = top20.index + 1

print("\n--- 5. TOP 20 STORE-DEPARTMENT SERIES BY REVENUE (SIMULATION CANDIDATES) ---")
display_cols = ["revenue_rank", "store_id", "dept_id", "store_type", "total_revenue", "mean_weekly_sales", "std_weekly_sales", "cv_demand"]
print(top20[display_cols].head(20).to_string(index=False, formatters={
    "total_revenue": "${:,.2f}".format,
    "mean_weekly_sales": "${:,.2f}".format,
    "std_weekly_sales": "${:,.2f}".format,
}))
print("=" * 80)
