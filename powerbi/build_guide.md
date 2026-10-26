# StockSense: Power BI Desktop Build Guide & Technical Specification

This document provides exact, step-by-step instructions for building the **StockSense** Power BI report in Power BI Desktop from your local SQL Server database.

---

## 1. Connecting to Local SQL Server (Import Mode)

### Step 1.1: Open Power BI Desktop and Connect
1. Open **Power BI Desktop**.
2. Click **Get Data** $\rightarrow$ select **SQL Server database** $\rightarrow$ click **Connect**.
3. In the connection dialog:
   - **Server:** `localhost,1433` (If connecting from a Windows host to WSL2, `localhost,1433` works directly via WSL2 localhost mirroring; if using a VM or remote host, enter your host IP: `192.168.x.x,1433`).
   - **Database:** `stocksense`
   - **Data Connectivity mode:** Select **Import** (enables full DAX time-intelligence, fast performance, and offline portability).
   - Click **OK**.
4. In the authentication prompt:
   - Select **Database** on the left menu (SQL Server Authentication).
   - **User name:** `stocksense_user`
   - **Password:** Enter your password (`Stock@Pass456`).
   - **Select which level to apply these settings to:** `localhost,1433`.
   - **Encryption:** If prompted about an unencrypted connection or self-signed certificate, check **"Trust server certificate"** and click **Connect**.

### Step 1.2: Select Tables in Navigator
In the Navigator window, select the following 8 tables and click **Transform Data** (opens Power Query):
- `dim_store`
- `dim_date`
- `fact_sales_weekly`
- `fact_forecast`
- `fact_model_metrics`
- `param_inventory`
- `fact_sim_summary`
- `fact_sim_paths_sample`

---

## 2. Power Query Data Transformations & Typing

In Power Query Editor, verify the data types for each table:

### Table 1: `dim_date`
- `date_key`: Whole Number (`Int64.Type`)
- `full_date`: Date (`type date`)
- `week_start`: Date (`type date`)
- `year`, `month`, `quarter`, `week_of_year`: Whole Number
- `month_name`, `holiday_name`: Text
- `is_holiday_week`: True/False or Whole Number (0/1)

### Table 2: `dim_store`
- `store_id`: Whole Number
- `store_type`: Text
- `store_size`: Whole Number

### Table 3: `fact_sales_weekly`
- `store_id`, `dept_id`, `date_key`: Whole Number
- `weekly_sales`: Fixed Decimal Number (Currency: `$`)
- `temperature`, `fuel_price`, `cpi`, `unemployment`: Decimal Number
- `markdown_1` through `markdown_5`, `markdown_total`: Fixed Decimal Number
- `has_markdown`, `is_negative_sales`, `is_holiday`: True/False

### Table 4: `fact_forecast`
- `store_id`, `dept_id`, `date_key`, `fold_id`: Whole Number
- `model_name`: Text
- `forecast`, `lower_80`, `upper_80`, `actual`, `error`, `abs_error`: Fixed Decimal Number

### Table 5: `fact_model_metrics`
- `model_name`: Text
- `store_id`, `dept_id`, `fold_id`, `eval_horizon_weeks`: Whole Number
- `wape`, `mase`: Percentage / Decimal Number (`0.00%` or `0.0000`)
- `rmse`, `bias`: Fixed Decimal Number

### Table 6: `fact_sim_summary`
- `store_id`, `dept_id`, `reorder_point`, `order_up_to`, `sim_runs`: Whole Number
- `policy_type`: Text
- `is_recommended`: True/False
- `fill_rate`, `stockout_prob`, `service_level_target`: Percentage (`0.00%`)
- `avg_on_hand`, `avg_weekly_demand`: Decimal Number
- `total_cost`, `holding_cost`, `stockout_cost`, `order_cost`, `p05_cost`, `p95_cost`: Fixed Decimal Number

### Table 7: `fact_sim_paths_sample`
- `store_id`, `dept_id`, `run_id`, `week_num`: Whole Number
- `on_hand`, `demand`, `order_placed`, `stockout_units`: Decimal Number

Click **Close & Apply**.

---

## 3. Star Schema Data Model & Relationships

Navigate to the **Model View** in Power BI Desktop.

### 3.1 Establish Relationships
Create one-to-many ($1 \rightarrow *$), single cross-filter direction relationships:

1. `dim_store[store_id]` $\rightarrow$ `fact_sales_weekly[store_id]` (1 to Many, Single)
2. `dim_store[store_id]` $\rightarrow$ `fact_forecast[store_id]` (1 to Many, Single)
3. `dim_store[store_id]` $\rightarrow$ `fact_model_metrics[store_id]` (1 to Many, Single)
4. `dim_store[store_id]` $\rightarrow$ `fact_sim_summary[store_id]` (1 to Many, Single)
5. `dim_store[store_id]` $\rightarrow$ `param_inventory[store_id]` (1 to Many, Single)
6. `dim_date[date_key]` $\rightarrow$ `fact_sales_weekly[date_key]` (1 to Many, Single)
7. `dim_date[date_key]` $\rightarrow$ `fact_forecast[date_key]` (1 to Many, Single)

```
       ┌────────────────────────┐         ┌────────────────────────┐
       │       dim_store        │         │        dim_date        │
       │  PK: store_id          │         │  PK: date_key          │
       └───────────┬────────────┘         └───────────┬────────────┘
                   │                                  │
       ┌───────────┼──────────────────────────────────┼────────────┐
       │           │                                  │            │
       ▼           ▼                                  ▼            ▼
┌──────────────┐ ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐
│param_invent..│ │ fact_sim_summary  │ │ fact_sales_weekly │ │   fact_forecast   │
│FK: store_id  │ │ FK: store_id      │ │ FK: store_id      │ │ FK: store_id      │
└──────────────┘ └───────────────────┘ │ FK: date_key      │ │ FK: date_key      │
                                       └───────────────────┘ └───────────────────┘
```

### 3.2 Mark as Date Table
1. Right-click `dim_date` in the data pane $\rightarrow$ click **Mark as date table**.
2. Select `full_date` as the Date column $\rightarrow$ click **OK**.

### 3.3 Hide Foreign Key Columns in Fact Tables
Right-click and **Hide in report view**:
- `fact_sales_weekly[store_id]`, `fact_sales_weekly[date_key]`
- `fact_forecast[store_id]`, `fact_forecast[date_key]`
- `fact_sim_summary[store_id]`

---

## 4. DAX Measures Specification

Create a dedicated measures container table:
- Home tab $\rightarrow$ **Enter Data** $\rightarrow$ Name the table `_Measures` $\rightarrow$ Load.
- Add the following DAX measures:

### Core Financial & Actuals Measures
```dax
Total Sales = 
SUM(fact_sales_weekly[weekly_sales])
```

```dax
Sales Last Year = 
CALCULATE(
    [Total Sales],
    SAMEPERIODLASTYEAR(dim_date[full_date])
)
```

```dax
Sales YoY % = 
VAR CurrentSales = [Total Sales]
VAR PreviousSales = [Sales Last Year]
RETURN
    DIVIDE(CurrentSales - PreviousSales, PreviousSales, BLANK())
```

### Forecasting Accuracy Measures
```dax
Total Forecast = 
SUM(fact_forecast[forecast])
```

```dax
Total Actual Demand = 
SUM(fact_forecast[actual])
```

```dax
Abs Forecast Error = 
SUM(fact_forecast[abs_error])
```

```dax
WAPE = 
DIVIDE(
    [Abs Forecast Error],
    [Total Actual Demand],
    BLANK()
)
```

```dax
Forecast Bias = 
DIVIDE(
    [Total Forecast] - [Total Actual Demand],
    [Total Actual Demand],
    0
)
```

```dax
Avg RMSE = 
AVERAGE(fact_model_metrics[rmse])
```

```dax
Avg MASE = 
AVERAGE(fact_model_metrics[mase])
```

### Inventory Risk & Simulation Measures
```dax
Avg Fill Rate = 
CALCULATE(
    AVERAGE(fact_sim_summary[fill_rate]),
    fact_sim_summary[is_recommended] = 1
)
```

```dax
Stockout Risk % = 
CALCULATE(
    AVERAGE(fact_sim_summary[stockout_prob]),
    fact_sim_summary[is_recommended] = 1
)
```

```dax
Simulated Total Cost = 
CALCULATE(
    SUM(fact_sim_summary[total_cost]),
    fact_sim_summary[is_recommended] = 1
)
```

```dax
Avg On Hand Units = 
CALCULATE(
    AVERAGE(fact_sim_summary[avg_on_hand]),
    fact_sim_summary[is_recommended] = 1
)
```

```dax
Cost Savings vs Fixed Cover = 
VAR RecCost = 
    CALCULATE(
        SUM(fact_sim_summary[total_cost]),
        fact_sim_summary[is_recommended] = 1
    )
VAR FixedCost = 
    CALCULATE(
        SUM(fact_sim_summary[total_cost]),
        fact_sim_summary[policy_type] = "Fixed Weeks Cover (2.5 Wks)"
    )
RETURN
    FixedCost - RecCost
```

```dax
Cost Savings % = 
VAR RecCost = 
    CALCULATE(
        SUM(fact_sim_summary[total_cost]),
        fact_sim_summary[is_recommended] = 1
    )
VAR FixedCost = 
    CALCULATE(
        SUM(fact_sim_summary[total_cost]),
        fact_sim_summary[policy_type] = "Fixed Weeks Cover (2.5 Wks)"
    )
RETURN
    DIVIDE(FixedCost - RecCost, FixedCost, 0)
```

---

## 5. Report Layout & Visual Specifications (4-Page Dashboard)

### Page 1: Executive Overview
*Target Audience: VP of Supply Chain / Retail Operations Director.*

1. **Header Banner:**
   - Title: `StockSense | Retail Demand & Inventory Risk Overview`
   - Slicers: Store Type (`dim_store[store_type]`), Year (`dim_date[year]`), Store ID dropdown.
2. **Top KPI Cards (4 cards across top):**
   - Card 1: `Total Sales` (Format: `$#,##0.00 M`)
   - Card 2: `WAPE` (Format: `0.0%`, Goal: `< 8%`)
   - Card 3: `Avg Fill Rate` (Format: `0.0%`, Goal: `> 95%`)
   - Card 4: `Cost Savings vs Fixed Cover` (Format: `$#,##0 K`, Highlight: Green).
3. **Visual 1 (Line Chart — Middle Left, 60% width):**
   - X-Axis: `dim_date[full_date]`
   - Y-Axis: `[Total Sales]` (solid dark blue `#2563EB`) and `[Sales Last Year]` (dashed gray `#94A3B8`).
   - Title: *Weekly Sales Trend vs. Prior Year Actuals*.
4. **Visual 2 (Clustered Bar Chart — Middle Right, 40% width):**
   - Y-Axis: `fact_sales_weekly[dept_id]` (Top 10 by Sales).
   - X-Axis: `[Total Sales]`.
   - Tooltips: `[Sales YoY %]`.
   - Title: *Top 10 Departments by Revenue Volume*.
5. **Visual 3 (Donut Chart — Bottom Left):**
   - Legend: `dim_store[store_type]`.
   - Values: `[Total Sales]`.
   - Title: *Revenue Contribution by Store Format*.
6. **Visual 4 (Table — Bottom Right):**
   - Columns: `Store`, `Type`, `Size`, `Total Sales`, `Sales YoY %`.

---

### Page 2: Forecast Accuracy & Model Evaluation
*Target Audience: Data Science & Demand Planning Analysts.*

1. **Top KPI Cards (4 cards):**
   - Card 1: Ridge Baseline Median WAPE (`7.04%`)
   - Card 2: Holt-Winters Median WAPE (`7.08%`)
   - Card 3: Naive Seasonal Benchmark WAPE (`7.58%`)
   - Card 4: Forecast Bias (`+$103` on Ridge).
2. **Visual 1 (Line Chart with Shaded Band — Top Half):**
   - X-Axis: `dim_date[full_date]` (Filtered to Test Horizon 2011–2012).
   - Y-Axis: `fact_forecast[actual]`, `fact_forecast[forecast]` (by `model_name`).
   - Title: *Walk-Forward Actual vs. Multi-Model Forecast*.
3. **Visual 2 (Clustered Column Chart — Bottom Left):**
   - X-Axis: `fact_model_metrics[model_name]`.
   - Y-Axis: `[WAPE]`.
   - Legend: `fact_model_metrics[fold_id]` (Folds 1 to 4).
   - Title: *Model WAPE Comparison across Walk-Forward Folds*.
4. **Visual 3 (Matrix — Bottom Right):**
   - Rows: `store_id`, `dept_id`.
   - Columns: `model_name`.
   - Values: `[WAPE]`, `[Avg RMSE]`, `[Avg MASE]`, `[Forecast Bias]`.
   - Conditional Formatting: Background color on WAPE (Green = low, Red = high).

---

### Page 3: Inventory Risk & Policy Simulator
*Target Audience: Inventory Managers & Procurement Planners.*

1. **Top KPI Cards (4 cards):**
   - Card 1: `Simulated Total Cost` (`$4.79M` across top 20 series)
   - Card 2: `Avg Fill Rate` (`98.34%`)
   - Card 3: `Stockout Risk %` (`49.27%`)
   - Card 4: `Cost Savings %` (`6.01%` vs 2.5-week cover rule).
2. **Visual 1 (Line & Area Chart — Middle Left):**
   - X-Axis: `fact_sim_summary[reorder_point]`.
   - Y-Axis: `SUM(fact_sim_summary[total_cost])`, `SUM(holding_cost)`, `SUM(stockout_cost)`.
   - Title: *Inventory Cost Trade-Off Curve vs. Reorder Point (s)*.
3. **Visual 2 (Clustered Column Chart — Middle Right):**
   - X-Axis: `fact_sim_summary[policy_type]`.
   - Y-Axis: `SUM(total_cost)`.
   - Data labels: Show total cost.
   - Title: *Policy Benchmark: Monte Carlo Optimal vs. Textbook vs. Fixed Cover*.
4. **Visual 3 (Multi-Line Chart — Bottom Left):**
   - X-Axis: `fact_sim_paths_sample[week_num]` (Weeks 1 to 13).
   - Y-Axis: `fact_sim_paths_sample[on_hand]` (by `run_id`).
   - Title: *Sample On-Hand Inventory Trajectory Paths (50 Monte Carlo Runs)*.
5. **Visual 4 (Table — Bottom Right):**
   - Columns: `store_id`, `dept_id`, `reorder_point`, `order_up_to`, `fill_rate`, `stockout_prob`, `total_cost`, `p05_cost`, `p95_cost`.
   - Filter: `is_recommended = 1`.

---

### Page 4: What-If / Scenario Simulation
*Target Audience: Supply Chain Directors & Financial Planners.*

1. **What-If Parameters Creation:**
   - In Modeling tab $\rightarrow$ click **New Parameter** $\rightarrow$ **Numeric Range**:
     - **Name:** `ServiceLevelTarget`
     - **Min:** `0.90`, **Max:** `0.99`, **Increment:** `0.01`, **Default:** `0.95`.
   - Generates slicer and DAX measure: `ServiceLevelTarget Value = SELECTEDVALUE(ServiceLevelTarget[ServiceLevelTarget], 0.95)`.
2. **Dynamic Policy Selector Measure:**
   ```dax
   Dynamic Recommended Cost = 
   VAR Target = [ServiceLevelTarget Value]
   RETURN
       CALCULATE(
           MIN(fact_sim_summary[total_cost]),
           fact_sim_summary[fill_rate] >= Target
       )
   ```
3. **Visuals on What-If Page:**
   - Parameter Slicer: Target Service Level slider.
   - Gauge Chart: Current Fill Rate vs What-If Target.
   - Card: Dynamic Expected Cost at chosen Service Level.
   - Sensitivity Matrix: Impact of Service Level on Safety Stock and Total Cost.

---

## 6. Row-Level Security (RLS) Configuration

Implement a `StoreManager` security role so store managers only view data for their assigned store.

1. In Modeling tab $\rightarrow$ click **Manage roles**.
2. Click **Create** $\rightarrow$ Name the role: `StoreManager`.
3. Under **Tables**, select `dim_store`.
4. Enter the DAX table filter expression:
   ```dax
   [store_id] = 14
   ```
   *(Or for Azure Power BI Service Entra ID integration: `[store_id] = VALUE(USERPRINCIPALNAME())`)*.
5. Click **Save**.
6. **Test the Role:**
   - Modeling tab $\rightarrow$ click **View as**.
   - Check **StoreManager** $\rightarrow$ click **OK**.
   - Verify that all visuals, cards, and tables instantly filter strictly to Store 14!

---

## 7. Design Guidelines & Theme

- **Palette:**
  - Primary Action / Accent: Royal Blue (`#2563EB`)
  - Dark Headers / Text: Slate Charcoal (`#1E293B`)
  - Success / Optimal: Emerald Green (`#10B981`)
  - Warning / Reorder Point: Warm Amber (`#F59E0B`)
  - Alert / Stockout: Crimson (`#EF4444`)
  - Background Canvas: Crisp Light Gray (`#F8FAFC`)
- **Typography:** Segoe UI or Inter (10pt labels, 12pt titles, 20pt KPI callout values).
- **Navigation:** Add left-side icon navigation buttons with Page Bookmarks for clean user flow.
