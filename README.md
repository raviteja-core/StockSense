# StockSense: Demand Forecasting & Inventory Risk Simulator

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![SQL Server 2022](https://img.shields.io/badge/SQL%20Server-2022%20Developer-CC292B.svg)](https://www.microsoft.com/en-us/sql-server/sql-server-downloads)
[![Power BI](https://img.shields.io/badge/Power%20BI-Desktop-F2C811.svg)](https://powerbi.microsoft.com/)
[![Tests](https://img.shields.io/badge/pytest-7%20passed-brightgreen.svg)](https://docs.pytest.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> An end-to-end analytics engineering and decision science platform that forecasts multi-echelon retail demand, models supplier uncertainty, and optimizes periodic-review $(s, S)$ inventory reorder policies via Monte Carlo simulation.

---

## 1. Business Problem & Executive Summary

Retail inventory management balances an expensive trade-off: **holding too much stock** inflates working capital carrying costs, while **holding too little** causes out-of-stock events, lost revenue, and customer churn. 

Traditional inventory heuristics rely on static "weeks-of-cover" rules or classical textbook formulas ($s = \mu_{LT} + z \cdot \sigma_{LT}$) that assume normally distributed demand and constant supplier lead times. In practice, retail demand exhibits extreme seasonal spikes (e.g., Thanksgiving/Black Friday), heavy right-skew, and stochastic supplier transit delays.

**StockSense** solves this by bridging statistical demand forecasting with stochastic inventory optimization:
1. **Demand Forecasting:** Forecasts Store $\times$ Department weekly series using regularized machine learning (Ridge autoregression), univariate statistical time-series models (Holt-Winters Exponential Smoothing), and naive seasonal benchmarks across a 4-fold walk-forward backtest.
2. **Decision Simulation:** Runs a 10,000-iteration vectorized Monte Carlo simulation per policy scenario, drawing stochastic demand from empirical backtest residual distributions alongside discrete lead times (1–3 weeks) to find cost-optimal $(s, S)$ policies.
3. **Data Platform & BI Delivery:** Engineered as a star schema in Microsoft SQL Server 2022 with an interactive 4-page Power BI executive dashboard.

---

## 2. Key Measured Results

All metrics below are computed directly from executable pipeline code on the 421,570 Walmart sales records across 52 test weeks (4 folds $\times$ 13-week test horizons):

### A. Forecasting Benchmark (Top 100 Revenue Series)
- **Ridge Regression Baseline** achieved the lowest median error (**7.04% WAPE**) and near-zero bias (**+$103.73** median signed error), successfully factoring in promotional markdowns and macroeconomic shifts.
- **Holt-Winters Exponential Smoothing** achieved a median WAPE of **7.08%** with the tightest interquartile stability (**P25: 5.05%, P75: 9.26%**), winning 37 out of 100 series by smoothing seasonal trends.
- **Naive Seasonal Benchmark** achieved an 8.32% mean WAPE, but suffered from severe under-forecasting bias (**-$2,727.05**) on growing store departments.

### B. Inventory Risk Simulation (Top 20 Revenue Series — 10,000 Runs/Scenario)
- **$306,345 in Cost Savings (6.01% Reduction):** The Monte Carlo optimal $(s, S)$ policy reduced 13-week total operating cost to **$4,791,610** compared to **$5,097,955** under the traditional 2.5-week fixed-cover heuristic.
- **Higher Customer Service Level:** The optimal policy improved the aggregate fill rate from **97.85% to 98.34%** while reducing stockout probability from **61.0% to 49.3%**.
- **Working Capital Efficiency:** Compared to the textbook normal formula ($z=1.65$), Monte Carlo eliminated over-buffering, holding **~20,000 fewer inventory units on average** and saving **$65,334** in holding costs without compromising fill rate.

---

## 3. System Architecture

```
┌────────────────────────────────┐
│   Kaggle Retail Source Data    │
│  train.csv, features, stores   │
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│     Python ETL & Cleaning      │  ──► Validates data types, maps holidays,
│      (src/load_data.py)        │      flags returns, imputes markdowns
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────┐
│        Microsoft SQL Server 2022 (Docker/WSL2)         │
│  Star Schema: dim_store, dim_date, fact_sales_weekly   │
└───────────────┬────────────────────────────────────────┘
                │
        ┌───────┴────────────────────────┐
        ▼                                ▼
┌──────────────────────────────┐ ┌──────────────────────────────┐
│   Walk-Forward Forecasting   │ │    Monte Carlo Simulation    │
│    (src/forecast_pipeline)   │ │     (src/sim_pipeline)       │
│  - Naive Seasonal Lag 52     │ │  - 10,000 Vectorized Runs    │
│  - Recursive Ridge Baseline  │ │  - Bootstrapped Errors       │
│  - Holt-Winters 52-wk ETS    │ │  - Discrete Lead Times       │
│  Writes: fact_forecast,      │ │  - Grid of Reorder Points    │
│          fact_model_metrics  │ │  Writes: fact_sim_summary,   │
│                              │ │          fact_sim_paths      │
└───────────────┬──────────────┘ └──────────────┬───────────────┘
                │                               │
                └───────────────┬───────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────┐
│             Power BI Desktop (Import Mode)             │
│   4-Page Dashboard: Exec Overview, Forecast Accuracy,  │
│      Inventory Risk, What-If Dynamic Simulation        │
└────────────────────────────────────────────────────────┘
```

---

## 4. Visualizations & Analytical Charts

Generated charts are saved to [`docs/figures/`](docs/figures/):

| Visual Analysis | Description | Preview |
|---|---|---|
| **Inventory Cost Trade-Off Curve** | Balances weekly holding costs against stockout penalties across reorder points $s$ to locate the exact cost-minimizing policy at a 95% service level. | [`docs/figures/cost_vs_reorder_point.png`](docs/figures/cost_vs_reorder_point.png) |
| **Model Accuracy Boxplot** | Distribution of WAPE across the top 100 series comparing Naive Seasonal, Ridge Baseline, and Holt-Winters. | [`docs/figures/model_comparison_boxplot.png`](docs/figures/model_comparison_boxplot.png) |
| **Simulation Convergence Check** | Confirms stability and convergence (< 0.5% variance) between 5,000 and 10,000 iterations. | [`docs/figures/sim_convergence_check.png`](docs/figures/sim_convergence_check.png) |
| **Forecast Error by Horizon** | Tracks error degradation across the 13-week forecasting horizon (Week 1 through Week 13). | [`docs/figures/error_by_horizon.png`](docs/figures/error_by_horizon.png) |
| **Sample Inventory Trajectories** | Visualizes 50 Monte Carlo on-hand inventory trajectory paths over time against stockout thresholds. | [`docs/figures/inventory_paths_sample.png`](docs/figures/inventory_paths_sample.png) |

---

## 5. Repository Structure

```
StockSense/
├── README.md                           # Platform documentation & results
├── requirements.txt                    # Pinned Python dependencies
├── .env.example                        # Database connection template (never commit secrets)
├── .gitignore                          # Ignores credentials, bytecode, and raw data
├── data/
│   ├── raw/                            # Source Kaggle CSVs (train.csv, features.csv, stores.csv)
│   └── processed/                      # Parquet cache for ETL and residual bootstrap ratios
├── sql/
│   ├── 01_create_tables.sql            # Star schema DDL with clustered PKs and indexes
│   ├── 02_views.sql                    # Analytical reporting views
│   └── 03_sample_queries.sql           # Data hygiene and audit validation queries
├── src/
│   ├── config.py                       # Connection management via URL.create and retry decorator
│   ├── init_db.py                      # Re-runnable SQL batch initializer
│   ├── load_data.py                    # Star schema ETL with fast_executemany batching
│   ├── features.py                     # Leakage-free lag, rolling, calendar, and markdown features
│   ├── forecast_baseline.py            # Naive Seasonal & recursive Ridge Baseline models
│   ├── forecast_timeseries.py          # Per-series Holt-Winters Exponential Smoothing
│   ├── evaluate.py                     # WAPE, RMSE, MASE, Bias calculation engine
│   ├── write_results.py                # SQL Server persistence and visualization generator
│   ├── forecast_pipeline.py            # 4-fold walk-forward cross-validation orchestrator
│   ├── simulate_inventory.py           # Vectorized (s, S) Monte Carlo simulation engine
│   └── sim_pipeline.py                 # 10,000-run simulation orchestrator across top 20 series
├── notebooks/
│   ├── 01_eda.py / 01_eda.ipynb        # Exploratory analysis (returns, holidays, markdowns)
│   ├── 02_forecasting.py / .ipynb      # Interactive model inspection & residual evaluation
│   └── 03_simulation.py / .ipynb       # Interactive policy trade-off curves and path analysis
├── powerbi/
│   ├── build_guide.md                  # Complete step-by-step Power BI build guide & DAX
│   └── stocksense_theme.json           # Corporate color palette and visual styling theme
├── docs/
│   ├── assumptions.md                  # Comprehensive disclosure of all economic & lead time assumptions
│   ├── local_sql_server_setup.md       # Docker and WSL2 SQL Server 2022 setup guide
│   └── figures/                        # Generated evaluation charts (PNG)
└── tests/
    ├── test_data_loading.py            # Schema validation and connection retry tests
    ├── test_forecasting.py             # Feature leakage and metric hand-calculation tests
    └── test_simulation.py              # Zero-variance deterministic hand-calculation test
```

---

## 6. How to Run & Reproduce

### Prerequisites
- Python 3.11+ (Conda environment recommended, e.g. `twel`)
- Microsoft SQL Server 2022 (Docker on WSL2 or native)
- Microsoft ODBC Driver 18 for SQL Server
- Power BI Desktop (Windows)

### Step 1: Environment & Dependencies
```bash
# Clone the repository
git clone https://github.com/your-username/StockSense.git
cd StockSense

# Activate your environment and install dependencies
conda activate twel
pip install -r requirements.txt
```

### Step 2: Configure Environment Credentials
```bash
cp .env.example .env
```
Edit `.env` with your SQL Server credentials (this file is excluded from version control):
```env
DB_SERVER=localhost,1433
DB_NAME=stocksense
DB_USER=stocksense_user
DB_PASSWORD=YourSecurePassword
DB_DRIVER=ODBC Driver 18 for SQL Server
DB_TRUST_SERVER_CERT=yes
```

### Step 3: Run Unit Tests
```bash
pytest -v
```
*Expected Output:* `7 passed` (Verifies schema transformation, connection retries, zero-leakage feature engineering, metric formulas, and zero-variance inventory simulation).

### Step 4: Initialize Database & Load Data
Ensure `train.csv`, `features.csv`, and `stores.csv` are in `data/raw/`, then run:
```bash
# Create star schema tables and views in SQL Server
python -m src.init_db

# Clean, transform, and load 421,570 records into SQL Server
python -m src.load_data
```

### Step 5: Execute Demand Forecasting Pipeline
```bash
# Run 4-fold walk-forward validation across top 100 series (Ridge, Holt-Winters, Naive)
python -m src.forecast_pipeline
```
*Populates `dbo.fact_forecast` (15,600 rows), `dbo.fact_model_metrics` (1,500 rows), caches residual ratios, and generates forecasting figures.*

### Step 6: Execute Monte Carlo Inventory Simulation
```bash
# Run 10,000-run simulation grid across top 20 revenue series
python -m src.sim_pipeline
```
*Populates `dbo.fact_sim_summary` (280 rows) and `dbo.fact_sim_paths_sample` (13,000 rows), and generates inventory cost curves and convergence charts.*

### Step 7: Open Power BI & Connect
Follow the instructions in [`powerbi/build_guide.md`](powerbi/build_guide.md) to import tables and build the 4-page dashboard.

---

## 7. Assumptions & Limitations

To maintain full transparency, all modeling constraints and proxy choices are documented in detail in [`docs/assumptions.md`](docs/assumptions.md):
- **Demand Proxy:** The dataset provides weekly dollar sales (`Weekly_Sales`), not unit counts. Dollar sales serve as a demand proxy; unit costs are modeled at $10.00.
- **Negative Sales (Returns):** Represented 0.305% of rows (primarily apparel/electronics post-holiday adjustments). They are flagged in SQL and clipped to zero for inventory depletion.
- **Economic Parameters:** Holding rates (20%/yr), shortage penalties (30% lost margin proxy), and fixed ordering costs ($50/PO) are standard retail supply chain assumptions.
- **Lost Sales Assumption:** Unmet weekly demand is lost rather than backlogged, reflecting physical retail behavior.
- **Series Independence:** Store $\times$ Department series are simulated independently; multi-echelon central distribution center pooling is noted for future expansion.

---

## 8. Quality Assurance Checklist

- [x] **No Secrets in Repository:** Credentials strictly injected via `.env` and `URL.create` (special characters handled safely; `.env` gitignored).
- [x] **Zero Feature Leakage:** Verified via automated unit test perturbations across all lags and rolling statistics.
- [x] **Walk-Forward Validation:** 4 non-overlapping folds of 13-week test horizons with no future-data leakage.
- [x] **Simulation Hand-Calculation Verified:** Unit test confirms exact penny-for-penny match against analytical calculations under zero-variance conditions.
- [x] **Convergence Confirmed:** Less than 0.5% variance between 5,000 and 10,000 iterations.
- [x] **Real Data Only:** All metrics and tables derived directly from real execution on Kaggle Walmart dataset.
- [x] **Tested SQL Server 2022 & Power BI Ready:** Clean T-SQL DDL with clustered primary keys, foreign keys, and indexes.
