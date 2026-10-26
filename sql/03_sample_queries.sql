-- =============================================================================
-- StockSense: Quality Assurance & Pipeline Verification Queries
-- File: sql/03_sample_queries.sql
-- =============================================================================

-- Query 1: Table Row Counts & Hygiene Check
SELECT 'dim_store' AS table_name, COUNT(*) AS row_count FROM dbo.dim_store
UNION ALL
SELECT 'dim_date', COUNT(*) FROM dbo.dim_date
UNION ALL
SELECT 'fact_sales_weekly', COUNT(*) FROM dbo.fact_sales_weekly
UNION ALL
SELECT 'fact_forecast', COUNT(*) FROM dbo.fact_forecast
UNION ALL
SELECT 'fact_model_metrics', COUNT(*) FROM dbo.fact_model_metrics
UNION ALL
SELECT 'param_inventory', COUNT(*) FROM dbo.param_inventory
UNION ALL
SELECT 'fact_sim_summary', COUNT(*) FROM dbo.fact_sim_summary
UNION ALL
SELECT 'fact_sim_paths_sample', COUNT(*) FROM dbo.fact_sim_paths_sample;

-- Query 2: Date Coverage & Calendar Span
SELECT 
    MIN(full_date) AS min_date,
    MAX(full_date) AS max_date,
    COUNT(DISTINCT full_date) AS unique_reporting_weeks,
    SUM(CASE WHEN is_holiday_week = 1 THEN 1 ELSE 0 END) AS holiday_weeks_count
FROM dbo.dim_date;

-- Query 3: Negative Sales / Returns Audit
SELECT 
    is_negative_sales,
    COUNT(*) AS record_count,
    SUM(weekly_sales) AS total_sales_volume,
    MIN(weekly_sales) AS most_negative_value,
    AVG(weekly_sales) AS avg_sales
FROM dbo.fact_sales_weekly
GROUP BY is_negative_sales;

-- Query 4: Markdown Availability Summary (pre- vs post-Nov 2011)
SELECT 
    d.year,
    COUNT(*) AS total_records,
    SUM(CASE WHEN f.has_markdown = 1 THEN 1 ELSE 0 END) AS records_with_markdowns,
    CAST(SUM(CASE WHEN f.has_markdown = 1 THEN 1.0 ELSE 0.0 END) / COUNT(*) * 100 AS DECIMAL(5,2)) AS markdown_coverage_pct,
    AVG(f.markdown_total) AS avg_markdown_amount
FROM dbo.fact_sales_weekly f
JOIN dbo.dim_date d ON f.date_key = d.date_key
GROUP BY d.year
ORDER BY d.year;

-- Query 5: Top 20 Candidate Series for Monte Carlo Simulation
SELECT TOP 20
    store_id,
    dept_id,
    store_type,
    total_weeks,
    total_revenue,
    avg_weekly_sales,
    std_weekly_sales,
    revenue_rank
FROM dbo.vw_top_series_revenue
ORDER BY revenue_rank ASC;

-- Query 6: Model Accuracy Comparison (WAPE, RMSE, MASE, Bias)
SELECT 
    model_name,
    AVG(wape) AS avg_wape,
    AVG(rmse) AS avg_rmse,
    AVG(mase) AS avg_mase,
    AVG(bias) AS avg_bias
FROM dbo.fact_model_metrics
WHERE fold_id = 0
GROUP BY model_name
ORDER BY avg_wape ASC;

-- Query 7: Optimal Policy vs Textbook Formula Cost Comparison
SELECT 
    store_id,
    dept_id,
    policy_type,
    reorder_point,
    order_up_to,
    fill_rate,
    stockout_prob,
    expected_total_cost,
    p05_cost,
    p95_cost
FROM dbo.vw_optimal_inventory_policies
ORDER BY store_id, dept_id;
