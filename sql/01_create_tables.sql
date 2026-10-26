-- =============================================================================
-- StockSense: T-SQL Star Schema DDL for SQL Server 2022
-- File: sql/01_create_tables.sql
-- Description: Creates the star schema dimension and fact tables for weekly
--              demand forecasting, backtest evaluation, and inventory simulation.
-- Safe re-runnable script (drops child tables before parent dimension tables).
-- =============================================================================

-- Drop child fact / sample tables first to prevent foreign key conflicts
IF OBJECT_ID('dbo.fact_sim_paths_sample', 'U') IS NOT NULL DROP TABLE dbo.fact_sim_paths_sample;
IF OBJECT_ID('dbo.fact_sim_summary', 'U') IS NOT NULL DROP TABLE dbo.fact_sim_summary;
IF OBJECT_ID('dbo.param_inventory', 'U') IS NOT NULL DROP TABLE dbo.param_inventory;
IF OBJECT_ID('dbo.fact_model_metrics', 'U') IS NOT NULL DROP TABLE dbo.fact_model_metrics;
IF OBJECT_ID('dbo.fact_forecast', 'U') IS NOT NULL DROP TABLE dbo.fact_forecast;
IF OBJECT_ID('dbo.fact_sales_weekly', 'U') IS NOT NULL DROP TABLE dbo.fact_sales_weekly;
IF OBJECT_ID('dbo.dim_date', 'U') IS NOT NULL DROP TABLE dbo.dim_date;
IF OBJECT_ID('dbo.dim_store', 'U') IS NOT NULL DROP TABLE dbo.dim_store;
GO

-- 1. Dimension: Store Attributes
CREATE TABLE dbo.dim_store (
    store_id            INT NOT NULL,
    store_type          CHAR(1) NOT NULL,           -- 'A', 'B', 'C'
    store_size          INT NOT NULL,               -- Square footage
    created_at          DATETIME2 DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_dim_store PRIMARY KEY CLUSTERED (store_id)
);
GO

-- 2. Dimension: Date Calendar
CREATE TABLE dbo.dim_date (
    date_key            INT NOT NULL,               -- Format: YYYYMMDD
    full_date           DATE NOT NULL,
    week_start          DATE NOT NULL,
    year                SMALLINT NOT NULL,
    month               TINYINT NOT NULL,
    month_name          VARCHAR(15) NOT NULL,
    quarter             TINYINT NOT NULL,
    week_of_year        TINYINT NOT NULL,
    is_holiday_week     BIT NOT NULL DEFAULT 0,
    holiday_name        VARCHAR(50) NULL,           -- 'Super Bowl', 'Labor Day', 'Thanksgiving', 'Christmas'
    CONSTRAINT PK_dim_date PRIMARY KEY CLUSTERED (date_key)
);
CREATE UNIQUE NONCLUSTERED INDEX UX_dim_date_full_date ON dbo.dim_date (full_date);
GO

-- 3. Fact Table: Weekly Store Sales (Actuals & Exogenous Signals)
CREATE TABLE dbo.fact_sales_weekly (
    store_id            INT NOT NULL,
    dept_id             INT NOT NULL,
    date_key            INT NOT NULL,
    weekly_sales        DECIMAL(18, 2) NOT NULL,
    is_holiday          BIT NOT NULL DEFAULT 0,
    temperature         DECIMAL(9, 2) NULL,
    fuel_price          DECIMAL(9, 3) NULL,
    cpi                 DECIMAL(12, 6) NULL,
    unemployment        DECIMAL(9, 4) NULL,
    markdown_1          DECIMAL(18, 2) NOT NULL DEFAULT 0.0,
    markdown_2          DECIMAL(18, 2) NOT NULL DEFAULT 0.0,
    markdown_3          DECIMAL(18, 2) NOT NULL DEFAULT 0.0,
    markdown_4          DECIMAL(18, 2) NOT NULL DEFAULT 0.0,
    markdown_5          DECIMAL(18, 2) NOT NULL DEFAULT 0.0,
    markdown_total      DECIMAL(18, 2) NOT NULL DEFAULT 0.0,
    has_markdown        BIT NOT NULL DEFAULT 0,
    is_negative_sales   BIT NOT NULL DEFAULT 0,     -- Flag for returns / adjustments
    CONSTRAINT PK_fact_sales_weekly PRIMARY KEY CLUSTERED (store_id, dept_id, date_key),
    CONSTRAINT FK_fact_sales_store FOREIGN KEY (store_id) REFERENCES dbo.dim_store (store_id),
    CONSTRAINT FK_fact_sales_date FOREIGN KEY (date_key) REFERENCES dbo.dim_date (date_key)
);
CREATE NONCLUSTERED INDEX IX_fact_sales_dept ON dbo.fact_sales_weekly (dept_id, date_key);
CREATE NONCLUSTERED INDEX IX_fact_sales_date ON dbo.fact_sales_weekly (date_key);
GO

-- 4. Fact Table: Forecasts & Prediction Intervals
CREATE TABLE dbo.fact_forecast (
    forecast_id         BIGINT IDENTITY(1,1) NOT NULL,
    store_id            INT NOT NULL,
    dept_id             INT NOT NULL,
    date_key            INT NOT NULL,
    model_name          VARCHAR(50) NOT NULL,       -- 'Naive Seasonal', 'Ridge Baseline', 'SARIMA'
    fold_id             INT NOT NULL,               -- Walk-forward fold index (1, 2, 3...)
    forecast            DECIMAL(18, 2) NOT NULL,
    lower_80            DECIMAL(18, 2) NULL,
    upper_80            DECIMAL(18, 2) NULL,
    actual              DECIMAL(18, 2) NULL,
    error               DECIMAL(18, 2) NULL,
    abs_error           DECIMAL(18, 2) NULL,
    created_at          DATETIME2 DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_fact_forecast PRIMARY KEY CLUSTERED (forecast_id),
    CONSTRAINT FK_fact_forecast_store FOREIGN KEY (store_id) REFERENCES dbo.dim_store (store_id),
    CONSTRAINT FK_fact_forecast_date FOREIGN KEY (date_key) REFERENCES dbo.dim_date (date_key)
);
CREATE NONCLUSTERED INDEX IX_fact_forecast_lookup 
ON dbo.fact_forecast (store_id, dept_id, model_name, fold_id, date_key);
GO

-- 5. Fact Table: Model Performance Metrics (WAPE, RMSE, MASE, Bias)
CREATE TABLE dbo.fact_model_metrics (
    model_name          VARCHAR(50) NOT NULL,
    store_id            INT NOT NULL,
    dept_id             INT NOT NULL,
    fold_id             INT NOT NULL,               -- 0 for overall average, 1..N for specific fold
    wape                DECIMAL(9, 4) NOT NULL,     -- Primary Metric: Sum(|Actual - Forecast|) / Sum(Actual)
    rmse                DECIMAL(18, 2) NOT NULL,
    mase                DECIMAL(9, 4) NOT NULL,     -- Mean Absolute Scaled Error (relative to naive seasonal)
    bias                DECIMAL(18, 2) NOT NULL,    -- Mean signed error
    eval_horizon_weeks  INT NOT NULL DEFAULT 13,
    created_at          DATETIME2 DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_fact_model_metrics PRIMARY KEY CLUSTERED (model_name, store_id, dept_id, fold_id),
    CONSTRAINT FK_fact_metrics_store FOREIGN KEY (store_id) REFERENCES dbo.dim_store (store_id)
);
GO

-- 6. Dimension/Parameter Table: Inventory Assumptions
CREATE TABLE dbo.param_inventory (
    store_id                INT NOT NULL,
    dept_id                 INT NOT NULL,
    unit_cost               DECIMAL(10, 2) NOT NULL DEFAULT 10.00,
    holding_rate_annual     DECIMAL(5, 4) NOT NULL DEFAULT 0.2000,   -- 20% / yr
    stockout_penalty_rate   DECIMAL(5, 4) NOT NULL DEFAULT 0.3000,   -- 30% lost margin proxy
    order_cost_fixed        DECIMAL(10, 2) NOT NULL DEFAULT 50.00,   -- $50 per PO
    lead_time_p1            DECIMAL(4, 3) NOT NULL DEFAULT 0.500,    -- 50% chance 1 week
    lead_time_p2            DECIMAL(4, 3) NOT NULL DEFAULT 0.350,    -- 35% chance 2 weeks
    lead_time_p3            DECIMAL(4, 3) NOT NULL DEFAULT 0.150,    -- 15% chance 3 weeks
    updated_at              DATETIME2 DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_param_inventory PRIMARY KEY CLUSTERED (store_id, dept_id)
);
GO

-- 7. Fact Table: Simulation Summary & Policy Evaluation
CREATE TABLE dbo.fact_sim_summary (
    sim_id              BIGINT IDENTITY(1,1) NOT NULL,
    store_id            INT NOT NULL,
    dept_id             INT NOT NULL,
    reorder_point       INT NOT NULL,               -- s
    order_up_to         INT NOT NULL,               -- S
    policy_type         VARCHAR(50) NOT NULL,       -- 'Monte Carlo (s,S)', 'Textbook Formula', 'Fixed Weeks Cover'
    service_level_target DECIMAL(5, 4) NULL,        -- e.g. 0.95
    stockout_prob       DECIMAL(7, 4) NOT NULL,     -- Fraction of runs with >=1 stockout
    fill_rate           DECIMAL(7, 4) NOT NULL,     -- Total fulfilled / Total demanded
    avg_on_hand         DECIMAL(14, 2) NOT NULL,    -- Mean average on-hand units
    avg_weekly_demand   DECIMAL(14, 2) NOT NULL,
    total_cost          DECIMAL(14, 2) NOT NULL,    -- Holding + Stockout + Ordering
    holding_cost        DECIMAL(14, 2) NOT NULL,
    stockout_cost       DECIMAL(14, 2) NOT NULL,
    order_cost          DECIMAL(14, 2) NOT NULL,
    p05_cost            DECIMAL(14, 2) NOT NULL,    -- 5th percentile total cost
    p95_cost            DECIMAL(14, 2) NOT NULL,    -- 95th percentile total cost
    is_recommended      BIT NOT NULL DEFAULT 0,     -- Flag for optimal cost policy at target service level
    sim_runs            INT NOT NULL DEFAULT 10000,
    created_at          DATETIME2 DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_fact_sim_summary PRIMARY KEY CLUSTERED (sim_id),
    CONSTRAINT FK_fact_sim_store FOREIGN KEY (store_id) REFERENCES dbo.dim_store (store_id)
);
CREATE NONCLUSTERED INDEX IX_fact_sim_lookup 
ON dbo.fact_sim_summary (store_id, dept_id, reorder_point, is_recommended);
GO

-- 8. Fact Table: Sample Simulation Paths for Visualizing Trajectories (50 paths per series)
CREATE TABLE dbo.fact_sim_paths_sample (
    path_id             BIGINT IDENTITY(1,1) NOT NULL,
    store_id            INT NOT NULL,
    dept_id             INT NOT NULL,
    reorder_point       INT NOT NULL,
    order_up_to         INT NOT NULL,
    run_id              INT NOT NULL,               -- Monte Carlo run index (1..50)
    week_num            INT NOT NULL,               -- 1..13
    on_hand             DECIMAL(14, 2) NOT NULL,
    demand              DECIMAL(14, 2) NOT NULL,
    order_placed        DECIMAL(14, 2) NOT NULL,
    stockout_units      DECIMAL(14, 2) NOT NULL,
    CONSTRAINT PK_fact_sim_paths_sample PRIMARY KEY CLUSTERED (path_id)
);
CREATE NONCLUSTERED INDEX IX_fact_sim_paths_lookup
ON dbo.fact_sim_paths_sample (store_id, dept_id, reorder_point, run_id, week_num);
GO
