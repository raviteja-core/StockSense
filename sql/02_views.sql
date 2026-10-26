-- =============================================================================
-- StockSense: Analytical Views for Reporting & Power BI Modeling
-- File: sql/02_views.sql
-- =============================================================================

-- View 1: Unified Weekly Sales & Attributes (Training & Reporting View)
IF OBJECT_ID('dbo.vw_weekly_sales_features', 'V') IS NOT NULL DROP VIEW dbo.vw_weekly_sales_features;
GO
CREATE VIEW dbo.vw_weekly_sales_features AS
SELECT 
    f.store_id,
    s.store_type,
    s.store_size,
    f.dept_id,
    f.date_key,
    d.full_date,
    d.week_start,
    d.year,
    d.month,
    d.month_name,
    d.week_of_year,
    d.is_holiday_week,
    d.holiday_name,
    f.weekly_sales,
    f.temperature,
    f.fuel_price,
    f.cpi,
    f.unemployment,
    f.markdown_1,
    f.markdown_2,
    f.markdown_3,
    f.markdown_4,
    f.markdown_5,
    f.markdown_total,
    f.has_markdown,
    f.is_negative_sales
FROM dbo.fact_sales_weekly f
INNER JOIN dbo.dim_store s ON f.store_id = s.store_id
INNER JOIN dbo.dim_date d ON f.date_key = d.date_key;
GO

-- View 2: Actual vs Forecast Combined View for Power BI Visuals
IF OBJECT_ID('dbo.vw_actual_vs_forecast', 'V') IS NOT NULL DROP VIEW dbo.vw_actual_vs_forecast;
GO
CREATE VIEW dbo.vw_actual_vs_forecast AS
SELECT 
    fc.forecast_id,
    fc.store_id,
    s.store_type,
    s.store_size,
    fc.dept_id,
    fc.date_key,
    d.full_date,
    d.week_of_year,
    d.year,
    fc.model_name,
    fc.fold_id,
    fc.forecast,
    fc.lower_80,
    fc.upper_80,
    COALESCE(fc.actual, f.weekly_sales) AS actual_sales,
    COALESCE(fc.error, COALESCE(fc.actual, f.weekly_sales) - fc.forecast) AS forecast_error,
    COALESCE(fc.abs_error, ABS(COALESCE(fc.actual, f.weekly_sales) - fc.forecast)) AS abs_forecast_error
FROM dbo.fact_forecast fc
INNER JOIN dbo.dim_store s ON fc.store_id = s.store_id
INNER JOIN dbo.dim_date d ON fc.date_key = d.date_key
LEFT JOIN dbo.fact_sales_weekly f 
    ON fc.store_id = f.store_id 
    AND fc.dept_id = f.dept_id 
    AND fc.date_key = f.date_key;
GO

-- View 3: Model Accuracy Leaderboard across Store-Departments
IF OBJECT_ID('dbo.vw_model_leaderboard', 'V') IS NOT NULL DROP VIEW dbo.vw_model_leaderboard;
GO
CREATE VIEW dbo.vw_model_leaderboard AS
SELECT 
    m.model_name,
    COUNT(DISTINCT CONCAT(m.store_id, '-', m.dept_id)) AS series_evaluated,
    AVG(m.wape) AS mean_wape,
    AVG(m.rmse) AS mean_rmse,
    AVG(m.mase) AS mean_mase,
    AVG(m.bias) AS mean_bias
FROM dbo.fact_model_metrics m
WHERE m.fold_id = 0  -- Overall average across folds
GROUP BY m.model_name;
GO

-- View 4: Recommended vs Baseline Inventory Policies
IF OBJECT_ID('dbo.vw_optimal_inventory_policies', 'V') IS NOT NULL DROP VIEW dbo.vw_optimal_inventory_policies;
GO
CREATE VIEW dbo.vw_optimal_inventory_policies AS
SELECT 
    sim.store_id,
    s.store_type,
    sim.dept_id,
    sim.policy_type,
    sim.reorder_point AS recommended_s_reorder_point,
    sim.order_up_to AS recommended_S_order_up_to,
    sim.service_level_target,
    sim.fill_rate,
    sim.stockout_prob,
    sim.avg_on_hand,
    sim.total_cost AS expected_total_cost,
    sim.p05_cost,
    sim.p95_cost
FROM dbo.fact_sim_summary sim
INNER JOIN dbo.dim_store s ON sim.store_id = s.store_id
WHERE sim.is_recommended = 1;
GO

-- View 5: Top Series by Total Historical Revenue (Used to Select Top 20 for Simulation)
IF OBJECT_ID('dbo.vw_top_series_revenue', 'V') IS NOT NULL DROP VIEW dbo.vw_top_series_revenue;
GO
CREATE VIEW dbo.vw_top_series_revenue AS
SELECT 
    f.store_id,
    s.store_type,
    s.store_size,
    f.dept_id,
    COUNT(*) AS total_weeks,
    SUM(f.weekly_sales) AS total_revenue,
    AVG(f.weekly_sales) AS avg_weekly_sales,
    STDEV(f.weekly_sales) AS std_weekly_sales,
    ROW_NUMBER() OVER (ORDER BY SUM(f.weekly_sales) DESC) AS revenue_rank
FROM dbo.fact_sales_weekly f
INNER JOIN dbo.dim_store s ON f.store_id = s.store_id
GROUP BY f.store_id, s.store_type, s.store_size, f.dept_id;
GO
