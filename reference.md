# StockSense — Demand Forecasting & Inventory Risk Simulator

**Reference document** · Resume portfolio project · Stack: Python · Azure SQL · Power BI · GitHub

---

## 1. Project snapshot

**One-liner:** An end-to-end analytics project that forecasts weekly retail demand, then uses Monte Carlo simulation to find reorder points that balance stockouts against holding cost, with everything stored in Azure SQL and presented in Power BI.

**Business question it answers:** *"How much stock should we hold, and when should we reorder, given that demand and supplier lead times are uncertain?"*

**Why it works on a resume:** it covers the full chain a hiring manager looks for: data engineering (SQL), modeling (regression and time series), decision science (simulation), BI delivery (Power BI), and cloud (Azure). It also maps directly onto the PL-300 exam.

**Target roles:** Data Analyst, BI Analyst, Supply Chain Analyst, Junior Data Scientist, Analytics Engineer.

---

## 2. Key decisions

| Decision | Choice | Reason |
|---|---|---|
| Dataset | **Walmart Store Sales Forecasting** (Kaggle, "Walmart Recruiting - Store Sales Forecasting") | Weekly data, 45 stores, many departments, holiday flags, temperature, fuel price, CPI, unemployment, markdowns. Small enough for the Azure SQL free tier. |
| Fallback dataset | M5 Forecasting (Walmart, Kaggle) or any Kaggle supply-chain dataset | Larger and daily, but heavier to load. |
| Granularity | Store × Department weekly series | Acts as the "SKU" unit for inventory simulation. |
| Scope | Top ~20 store-department series by revenue for simulation; broader set for forecasting | Keeps simulation readable and fast. |
| Baseline model | Regularized linear regression (Ridge) with lag, calendar and holiday features | Simple, explainable benchmark. |
| Time-series model | SARIMA or Holt-Winters (statsmodels). Prophet is optional | Captures trend and yearly seasonality. |
| Validation | Walk-forward (rolling origin) backtest | Prevents time leakage. |
| Inventory policy | Periodic-review (s, S) policy | Standard, easy to explain in interviews. |
| Simulation size | 10,000 runs per scenario | Stable percentiles, still fast with NumPy. |
| Power BI mode | Import mode | Most reliable; works offline. |

> **Honesty note (important):** the Walmart dataset gives *sales dollars*, not units, and has no real inventory, cost or lead-time data. Treat weekly sales as a demand proxy, and state every inventory parameter (unit cost, holding cost, stockout penalty, lead time) clearly as an **assumption** in the README. Never present assumed numbers as real business findings.

---

## 3. Architecture

```
Kaggle CSVs
    │
    ▼
Python ETL (pandas) ──► Azure SQL Database (free offer)
                              │   dim_store, dim_date, fact_sales_weekly
                              ▼
              Forecasting (Ridge baseline + SARIMA/ETS)
                              │   writes fact_forecast, fact_model_metrics
                              ▼
              Monte Carlo inventory simulation (NumPy)
                              │   writes fact_sim_summary, fact_sim_paths_sample
                              ▼
                    Power BI (Import mode)
                              │
                              ▼
          GitHub repo: code + README + screenshots + .pbix
```

---

## 4. Repository structure

```
stocksense/
├── README.md
├── requirements.txt
├── .env.example                 # DB connection placeholders, never real secrets
├── .gitignore                   # .env, data/raw, __pycache__
├── data/
│   ├── raw/                     # Kaggle CSVs (gitignored)
│   └── processed/
├── sql/
│   ├── 01_create_tables.sql
│   ├── 02_views.sql
│   └── 03_sample_queries.sql
├── src/
│   ├── config.py
│   ├── load_data.py             # CSV → Azure SQL
│   ├── features.py
│   ├── forecast_baseline.py     # Ridge regression
│   ├── forecast_timeseries.py   # SARIMA / Holt-Winters
│   ├── evaluate.py              # walk-forward backtest, metrics
│   ├── simulate_inventory.py    # Monte Carlo
│   └── write_results.py
├── notebooks/
│   ├── 01_eda.ipynb
│   ├── 02_forecasting.ipynb
│   └── 03_simulation.ipynb
├── powerbi/
│   ├── stocksense.pbix
│   └── screenshots/
└── docs/
    └── assumptions.md
```

---

## 5. Data and Azure SQL

### 5.1 Raw files (Walmart Store Sales Forecasting)
- `train.csv`: Store, Dept, Date, Weekly_Sales, IsHoliday
- `features.csv`: Store, Date, Temperature, Fuel_Price, MarkDown1–5, CPI, Unemployment, IsHoliday
- `stores.csv`: Store, Type, Size

### 5.2 Suggested schema (star schema)

| Table | Purpose | Key columns |
|---|---|---|
| `dim_store` | Store attributes | store_id, store_type, store_size |
| `dim_date` | Calendar | date_key, week_start, year, month, week_of_year, is_holiday_week |
| `fact_sales_weekly` | Actuals | store_id, dept_id, date_key, weekly_sales, temperature, fuel_price, cpi, unemployment, markdown_total |
| `fact_forecast` | Model outputs | store_id, dept_id, date_key, model_name, forecast, lower_80, upper_80, fold_id |
| `fact_model_metrics` | Accuracy | model_name, store_id, dept_id, wape, rmse, mase, bias |
| `param_inventory` | Assumptions | store_id, dept_id, unit_cost, holding_rate, stockout_cost, lead_time_probs |
| `fact_sim_summary` | Simulation results | store_id, dept_id, reorder_point, order_up_to, stockout_prob, fill_rate, avg_on_hand, total_cost, p05_cost, p95_cost |
| `fact_sim_paths_sample` | Example inventory paths (about 50 per series) | run_id, week, on_hand, store_id, dept_id |

### 5.3 Azure SQL free-tier setup notes
1. Create an Azure account and use the **Azure SQL Database free offer** (a monthly allowance of compute and storage at no charge; check the current limits on the Azure pricing page).
2. When creating the database, choose the option that **pauses the database when the free allowance runs out** instead of continuing with charges.
3. Add your client IP to the server firewall.
4. Set up a **budget alert** in Azure Cost Management so a mistake never becomes a bill.
5. Connect from Python using `pyodbc` or `SQLAlchemy` with the ODBC Driver 18 for SQL Server.
6. Keep credentials in `.env` and never commit them.
7. Load with batched inserts (`fast_executemany=True`).
8. Serverless databases auto-pause when idle, so the first connection after a pause can be slow. Add a retry in your code.
9. Do not leave the database running with open firewall rules (`0.0.0.0–255.255.255.255`).

---

## 6. Forecasting plan

### 6.1 EDA (notebook 01)
- Weekly sales distribution; check negative values (returns) and clip or flag them.
- Seasonality, especially holiday weeks (Super Bowl, Labor Day, Thanksgiving, Christmas).
- Missing markdown values, which should be filled with 0 and flagged.
- Series length per store-department, and drop series with too little history (for example under 2 years).

### 6.2 Features (baseline)
- Lags: 1, 2, 4, 52 weeks
- Rolling means: 4 and 13 weeks (computed on past data only)
- Calendar: week of year, month, holiday flag, week before/after holiday
- Exogenous: temperature, fuel price, CPI, unemployment, markdown total
- Store type and size

### 6.3 Models
1. **Naive seasonal** (same week last year) as the floor benchmark.
2. **Ridge regression**, the required regression baseline.
3. **SARIMA or Holt-Winters** per series, the required time-series model.
4. *(Optional stretch)* Gradient boosting such as LightGBM, as a third comparison.

### 6.4 Validation
- Walk-forward backtest: for example 3 to 4 folds, each training on all data up to a cutoff and testing on the next 13 weeks.
- Never shuffle. Never compute features using future rows.

### 6.5 Metrics
- **WAPE** (primary; robust to zeros)
- **RMSE**
- **MASE** (vs. naive seasonal)
- **Bias** (mean signed error)
- Report per model, and summarized across series (median and distribution, not just a single average).

### 6.6 Deliverable
A comparison table plus 2 to 3 charts (actual vs forecast, error by horizon, model comparison). Be honest if the baseline wins on some series; a clear explanation of *why* is a strong interview answer.

---

## 7. Monte Carlo inventory simulation

### 7.1 Inputs
- Weekly demand forecast for a 13-week horizon (from the best model per series)
- **Forecast error distribution**: bootstrap from walk-forward residual ratios (`actual / forecast`), or fit a Gamma or Normal if the sample is small
- **Lead time**: discrete distribution, for example 1 week (50%), 2 weeks (35%), 3 weeks (15%). *Assumption.*
- Starting inventory: for example 2 weeks of average demand. *Assumption.*
- Costs *(all assumptions, documented in `docs/assumptions.md`)*:
  - Holding cost: about 20% of unit cost per year, prorated weekly
  - Stockout (lost sales) cost: lost margin per unit short
  - Fixed ordering cost per order

### 7.2 Policy: periodic review (s, S)
Each week:
1. Receive any orders arriving this week.
2. Draw demand = forecast × sampled error ratio.
3. Fulfil from on-hand stock; record unmet demand (lost sales).
4. If **inventory position** (on-hand + on-order) ≤ **s**, order up to **S**.
5. Draw a lead time for the new order.

### 7.3 Experiments
- Grid of reorder points `s`, defined as multiples of average lead-time demand or as safety-stock levels (z = 0.5 … 2.5).
- Compare against the textbook formula: `s = μ_LT + z · σ_LT` (z from the target service level).
- Pick the `s` that **minimizes expected total cost** subject to a service-level target (for example fill rate ≥ 95%).

### 7.4 Outputs (per series and reorder point)
- Stockout probability (share of runs with at least one stockout)
- Fill rate (units fulfilled ÷ units demanded)
- Average on-hand inventory
- Expected total cost, with 5th and 95th percentiles
- A cost-vs-reorder-point curve showing the optimum

### 7.5 Implementation tips
- Vectorize across runs with NumPy (shape: runs × weeks) for speed.
- Set a random seed for reproducibility: `rng = np.random.default_rng(42)`.
- Run a convergence check: confirm results barely change between 5,000 and 10,000 runs.
- Unit tests: with zero demand variance and a fixed lead time, results should match a hand calculation.

---

## 8. Power BI dashboard

### 8.1 Model
Import the star schema from Azure SQL. Relationships: `dim_store` and `dim_date` → fact tables (one-to-many, single direction). Mark `dim_date` as the date table.

### 8.2 Pages
1. **Executive Overview**: KPI cards (total sales, forecast WAPE, average fill rate, average stockout risk), sales trend, top series.
2. **Forecast Accuracy**: actual vs forecast line chart with confidence band, model comparison, WAPE by store type, bias.
3. **Inventory Risk**: cost vs reorder-point curve, stockout probability by series, recommended `s` and `S`, risk heatmap.
4. **What-if / Scenarios**: parameters for target service level and lead-time shift; shows the effect on cost and stockout risk. Use what-if parameters or pre-computed scenarios.
5. *(Optional)* **Methodology**: assumptions and data notes, so reviewers see you were transparent.

### 8.3 DAX measures to write
```DAX
Total Sales = SUM(fact_sales_weekly[weekly_sales])

WAPE =
DIVIDE(
    SUMX(fact_forecast, ABS(fact_forecast[actual] - fact_forecast[forecast])),
    SUM(fact_forecast[actual])
)

Forecast Bias =
DIVIDE(SUM(fact_forecast[forecast]) - SUM(fact_forecast[actual]), SUM(fact_forecast[actual]))

Avg Fill Rate = AVERAGE(fact_sim_summary[fill_rate])

Stockout Risk % = AVERAGE(fact_sim_summary[stockout_prob])

Sales YoY % =
VAR Prev = CALCULATE([Total Sales], SAMEPERIODLASTYEAR(dim_date[date]))
RETURN DIVIDE([Total Sales] - Prev, Prev)
```
(Adjust column names to match your actual schema; you may need to join forecast and actuals into one table or view.)

### 8.4 Design rules
- Consistent colors, limited fonts, clear titles that state the takeaway.
- Tooltips and drill-through to a store-department detail page.
- Bookmarks and slicers (store, department, date, model).
- Check mobile layout.

### 8.5 Practical notes
- **Power BI Desktop runs on Windows only.** On Mac or Linux, use a Windows machine or VM, or Power BI Service in a browser (more limited).
- Publishing to the Power BI Service usually needs a work or school account. If you can't publish, deliver a `.pbix`, PDF export and screenshots in the repo, plus a short screen recording.

---

## 9. PL-300 prep (Microsoft Power BI Data Analyst)

Check the **official PL-300 study guide on Microsoft Learn** for the current skills outline and weightings, as they change. The four areas are:

| Exam area | Where StockSense gives you practice |
|---|---|
| Prepare the data | Connecting to Azure SQL, Power Query cleaning, data types, query folding, merge/append |
| Model the data | Star schema, relationships, date table, DAX measures, calculated columns, hierarchies |
| Visualize and analyze the data | Report pages, slicers, drill-through, tooltips, forecasting/analytics pane, accessibility |
| Manage and secure Power BI | Workspaces, refresh, row-level security, sharing, sensitivity concepts |

**Prep plan**
1. Work through the free **Microsoft Learn PL-300 learning path**.
2. Build the dashboard as hands-on practice, adding **row-level security** (for example, a Store Manager role) even if only to demonstrate it.
3. Practice DAX daily: `CALCULATE`, filter context, time intelligence, `VAR`/`RETURN`, `SUMX`, `DIVIDE`.
4. Take the **official Microsoft practice assessment** and review wrong answers by domain.
5. Book the exam when practice scores are consistently comfortable; check the current exam price and any student or voucher options on the Microsoft Learn exam page.
6. Add the certification to the resume only after passing. Until then, write "preparing for PL-300".

---

## 10. Timeline (about 4 weeks)

| Week | Goal | Done when |
|---|---|---|
| 1 | Setup, data load, EDA | Azure SQL populated, schema script in repo, EDA notebook |
| 2 | Forecasting | Baseline and time-series models with backtest metrics written to SQL |
| 3 | Monte Carlo simulation | Simulation results table and cost curve; tests pass |
| 4 | Power BI, README, polish; begin PL-300 study | `.pbix`, screenshots, README complete, repo public |
| 5 and onward | PL-300 prep and exam | Exam passed; send the project for the tailored resume |

---

## 11. Resume bullets (fill with your real numbers)

> Use only metrics you actually measured. Replace the `[X]` placeholders.

- Built an end-to-end demand forecasting pipeline on **[N]** store-department weekly series (Walmart retail dataset), loading data into **Azure SQL** and comparing a Ridge regression baseline against SARIMA/Holt-Winters with walk-forward validation (**WAPE [X]%** vs naive **[Y]%**).
- Developed a **Monte Carlo inventory simulation** (**10,000 runs per scenario**) using bootstrapped forecast errors and variable lead times to evaluate reorder-point policies on stockout probability, fill rate and total cost.
- Identified reorder points that **reduced simulated total cost by [X]%** at a **[Y]% fill-rate target** versus a fixed-weeks-of-cover rule (simulated, based on documented assumptions).
- Designed a **4-page Power BI dashboard** (star schema, DAX measures, what-if parameters, row-level security) to present forecast accuracy and inventory risk to non-technical stakeholders.
- Documented methodology, assumptions and reproducible code in a public **GitHub** repository (SQL scripts, Python modules, unit tests, README with results).

**Skills line:** Python (pandas, NumPy, scikit-learn, statsmodels) · SQL / Azure SQL · Power BI (DAX, Power Query) · Time-series forecasting · Monte Carlo simulation · Inventory optimization · Git/GitHub

---

## 12. README outline

1. Title, one-line summary, badge row, hero screenshot of the dashboard
2. Business problem
3. Key results (3 to 5 bullets with real numbers)
4. Architecture diagram
5. Data (source, license note, what each table is)
6. Methodology: forecasting, simulation, assumptions (link to `docs/assumptions.md`)
7. Results: model comparison table, cost curve, dashboard screenshots
8. How to run (environment, `.env`, load, forecast, simulate)
9. Limitations (dollar sales as demand proxy, assumed costs, lost-sales assumption, no real lead times)
10. Future work (hierarchical forecasting, ML models, multi-echelon inventory, automated refresh)
11. Author and contact links

---

## 13. Quality checklist

- [ ] No secrets in the repo (check git history)
- [ ] Random seeds set; results reproducible
- [ ] No time leakage in features or validation
- [ ] Negative sales handled and documented
- [ ] Every assumed number labeled as an assumption
- [ ] Model comparison includes a naive benchmark
- [ ] Simulation tested against a hand-calculable case
- [ ] Dashboard numbers match the SQL/Python outputs (spot-check 3 values)
- [ ] README renders correctly with images
- [ ] Azure budget alert set; unused resources paused or deleted after the project

---

## 14. Interview talking points

- **Why Ridge and SARIMA?** One is an explainable feature-based benchmark, the other a classic statistical model; comparing them shows judgment rather than model-chasing.
- **Why walk-forward validation?** It mimics real deployment and avoids leaking future information.
- **Why Monte Carlo instead of just a safety-stock formula?** The formula assumes normal demand and fixed lead time; simulation handles skewed demand, variable lead time and a cost trade-off, and gives a *distribution* of outcomes.
- **What would you change with real data?** Use unit-level demand, actual supplier lead times, real costs, censored-demand handling (stockouts hide true demand) and a pilot test.
- **What are the limitations?** Dollar sales as a proxy, assumed costs, lost-sales assumption, independence between series.

---

## 15. Useful references

- Kaggle: Walmart Recruiting - Store Sales Forecasting; M5 Forecasting - Accuracy
- Hyndman & Athanasopoulos, *Forecasting: Principles and Practice* (free online)
- statsmodels documentation (SARIMAX, ExponentialSmoothing)
- scikit-learn documentation (Ridge, TimeSeriesSplit)
- Microsoft Learn: PL-300 study guide, learning path, practice assessment
- Microsoft Learn: Azure SQL Database free offer documentation