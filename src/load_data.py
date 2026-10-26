"""StockSense: Data Ingestion & Star Schema ETL Pipeline.

Loads real Walmart Kaggle CSV files (train.csv, features.csv, stores.csv),
performs cleaning and star schema transformations, and loads dimension and
fact tables into SQL Server using batched inserts with fast_executemany.
"""

from __future__ import annotations

import argparse
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd
import numpy as np
from sqlalchemy import text

from src.config import (
    get_db_engine,
    retry_on_db_error,
    DATA_RAW_DIR,
    DATA_PROCESSED_DIR,
    DB_BACKEND,
)

logger = logging.getLogger("stocksense.load_data")

# Known Walmart Kaggle Special Holiday Dates
HOLIDAY_MAP: Dict[str, str] = {
    # Super Bowl
    "2010-02-12": "Super Bowl",
    "2011-02-11": "Super Bowl",
    "2012-02-10": "Super Bowl",
    "2013-02-08": "Super Bowl",
    # Labor Day
    "2010-09-10": "Labor Day",
    "2011-09-09": "Labor Day",
    "2012-09-07": "Labor Day",
    "2013-09-06": "Labor Day",
    # Thanksgiving
    "2010-11-26": "Thanksgiving",
    "2011-11-25": "Thanksgiving",
    "2012-11-23": "Thanksgiving",
    "2013-11-29": "Thanksgiving",
    # Christmas
    "2010-12-31": "Christmas",
    "2011-12-30": "Christmas",
    "2012-12-28": "Christmas",
    "2013-12-27": "Christmas",
}


def check_raw_files(raw_dir: Path) -> bool:
    """Check if all three required Kaggle CSV files exist."""
    required = ["train.csv", "features.csv", "stores.csv"]
    return all((raw_dir / f).exists() for f in required)


def generate_mock_walmart_data(raw_dir: Path) -> None:
    """Explicitly generate synthetic sample data in data/raw/ ONLY if requested via flag.

    Must never be called in the default execution path for real results.
    """
    logger.warning("Generating synthetic mock data in data/raw/ via explicit --generate-mock flag...")
    raw_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)

    stores_data = []
    store_types = ["A", "B", "C"]
    for s in range(1, 11):
        stype = store_types[(s - 1) % 3]
        size = 150000 if stype == "A" else (100000 if stype == "B" else 40000)
        stores_data.append({"Store": s, "Type": stype, "Size": size})
    pd.DataFrame(stores_data).to_csv(raw_dir / "stores.csv", index=False)

    dates = pd.date_range("2010-02-05", "2012-10-26", freq="W-FRI")

    features_rows = []
    for s in range(1, 11):
        for dt in dates:
            d_str = dt.strftime("%Y-%m-%d")
            is_hol = d_str in HOLIDAY_MAP
            features_rows.append({
                "Store": s, "Date": d_str, "Temperature": float(rng.normal(60.0, 15.0)),
                "Fuel_Price": float(rng.uniform(2.5, 4.0)),
                "MarkDown1": float(rng.uniform(500, 15000)) if dt >= pd.Timestamp("2011-11-01") else np.nan,
                "MarkDown2": float(rng.uniform(100, 8000)) if dt >= pd.Timestamp("2011-11-01") else np.nan,
                "MarkDown3": float(rng.uniform(50, 4000)) if dt >= pd.Timestamp("2011-11-01") else np.nan,
                "MarkDown4": float(rng.uniform(100, 5000)) if dt >= pd.Timestamp("2011-11-01") else np.nan,
                "MarkDown5": float(rng.uniform(500, 10000)) if dt >= pd.Timestamp("2011-11-01") else np.nan,
                "CPI": float(rng.uniform(180.0, 225.0)), "Unemployment": float(rng.uniform(5.5, 9.5)),
                "IsHoliday": is_hol
            })
    pd.DataFrame(features_rows).to_csv(raw_dir / "features.csv", index=False)

    train_rows = []
    for s in range(1, 11):
        for d in range(1, 6):
            base_sales = 15000.0 + (s * 1000.0) + (d * 3000.0)
            for dt in dates:
                d_str = dt.strftime("%Y-%m-%d")
                is_hol = d_str in HOLIDAY_MAP
                hol_mult = 1.35 if is_hol else 1.0
                week_of_year = dt.isocalendar()[1]
                season_mult = 1.0 + 0.25 * np.sin(2 * np.pi * week_of_year / 52)
                sales = base_sales * hol_mult * season_mult * rng.normal(1.0, 0.12)
                if rng.random() < 0.005:
                    sales = -float(rng.uniform(50.0, 300.0))
                train_rows.append({
                    "Store": s, "Dept": d, "Date": d_str,
                    "Weekly_Sales": round(sales, 2), "IsHoliday": is_hol
                })
    pd.DataFrame(train_rows).to_csv(raw_dir / "train.csv", index=False)
    logger.info("Mock data generated successfully.")


def build_star_schema(
    raw_dir: Path
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read real Kaggle CSVs, apply cleaning rules, and transform into star schema DataFrames.

    Returns:
        (dim_store, dim_date, fact_sales_weekly, param_inventory)
    """
    stores_path = raw_dir / "stores.csv"
    features_path = raw_dir / "features.csv"
    train_path = raw_dir / "train.csv"

    if not (stores_path.exists() and features_path.exists() and train_path.exists()):
        raise FileNotFoundError(
            f"Missing required Kaggle dataset files in '{raw_dir}'. Expected: "
            "train.csv, features.csv, and stores.csv. (test.csv and sampleSubmission.csv are ignored)."
        )

    logger.info(f"Reading raw CSVs from {raw_dir}...")
    df_stores = pd.read_csv(stores_path)
    df_features = pd.read_csv(features_path)
    df_train = pd.read_csv(train_path)

    # Standardize column casing & whitespace
    df_stores.columns = df_stores.columns.str.strip()
    df_features.columns = df_features.columns.str.strip()
    df_train.columns = df_train.columns.str.strip()

    # Parse Dates
    df_features["Date"] = pd.to_datetime(df_features["Date"])
    df_train["Date"] = pd.to_datetime(df_train["Date"])

    # --------------------------------------------------------------------------
    # 1. Build dim_store
    # --------------------------------------------------------------------------
    logger.info("Transforming dim_store...")
    dim_store = pd.DataFrame({
        "store_id": df_stores["Store"].astype(int),
        "store_type": df_stores["Type"].astype(str),
        "store_size": df_stores["Size"].astype(int)
    }).drop_duplicates().sort_values("store_id").reset_index(drop=True)

    # --------------------------------------------------------------------------
    # 2. Build dim_date
    # --------------------------------------------------------------------------
    logger.info("Transforming dim_date calendar...")
    # Derive calendar span strictly from actuals and features
    unique_dates = pd.date_range(
        start=df_train["Date"].min(),
        end=df_train["Date"].max(),
        freq="W-FRI"
    )

    date_rows = []
    for dt in unique_dates:
        d_str = dt.strftime("%Y-%m-%d")
        date_key = int(dt.strftime("%Y%m%d"))
        week_start = dt - pd.Timedelta(days=6)
        is_holiday = d_str in HOLIDAY_MAP
        holiday_name = HOLIDAY_MAP.get(d_str, None)

        date_rows.append({
            "date_key": date_key,
            "full_date": dt.date(),
            "week_start": week_start.date(),
            "year": int(dt.year),
            "month": int(dt.month),
            "month_name": dt.strftime("%B"),
            "quarter": int((dt.month - 1) // 3 + 1),
            "week_of_year": int(dt.isocalendar()[1]),
            "is_holiday_week": 1 if is_holiday else 0,
            "holiday_name": holiday_name
        })
    dim_date = pd.DataFrame(date_rows).drop_duplicates().sort_values("date_key").reset_index(drop=True)

    # --------------------------------------------------------------------------
    # 3. Clean & Merge fact_sales_weekly (Actuals from train.csv + exogenous features)
    # --------------------------------------------------------------------------
    logger.info("Cleaning markdowns and merging train with features into fact_sales_weekly...")
    for md_col in ["MarkDown1", "MarkDown2", "MarkDown3", "MarkDown4", "MarkDown5"]:
        if md_col in df_features.columns:
            df_features[md_col] = df_features[md_col].fillna(0.0).astype(float)
        else:
            df_features[md_col] = 0.0

    df_features["markdown_total"] = (
        df_features["MarkDown1"] +
        df_features["MarkDown2"] +
        df_features["MarkDown3"] +
        df_features["MarkDown4"] +
        df_features["MarkDown5"]
    ).round(2)
    df_features["has_markdown"] = (df_features["markdown_total"] > 0).astype(int)

    # Merge train actuals with exogenous features on Store and Date
    merged = pd.merge(
        df_train,
        df_features[[
            "Store", "Date", "Temperature", "Fuel_Price", "CPI", "Unemployment",
            "MarkDown1", "MarkDown2", "MarkDown3", "MarkDown4", "MarkDown5",
            "markdown_total", "has_markdown"
        ]],
        on=["Store", "Date"],
        how="inner"
    )

    merged["date_key"] = merged["Date"].dt.strftime("%Y%m%d").astype(int)
    merged["is_negative_sales"] = (merged["Weekly_Sales"] < 0).astype(int)
    merged["is_holiday"] = merged["IsHoliday"].astype(int)

    fact_sales_weekly = pd.DataFrame({
        "store_id": merged["Store"].astype(int),
        "dept_id": merged["Dept"].astype(int),
        "date_key": merged["date_key"],
        "weekly_sales": merged["Weekly_Sales"].round(2),
        "is_holiday": merged["is_holiday"],
        "temperature": merged["Temperature"].round(2),
        "fuel_price": merged["Fuel_Price"].round(3),
        "cpi": merged["CPI"].round(6),
        "unemployment": merged["Unemployment"].round(4),
        "markdown_1": merged["MarkDown1"].round(2),
        "markdown_2": merged["MarkDown2"].round(2),
        "markdown_3": merged["MarkDown3"].round(2),
        "markdown_4": merged["MarkDown4"].round(2),
        "markdown_5": merged["MarkDown5"].round(2),
        "markdown_total": merged["markdown_total"],
        "has_markdown": merged["has_markdown"],
        "is_negative_sales": merged["is_negative_sales"]
    }).drop_duplicates(subset=["store_id", "dept_id", "date_key"]).reset_index(drop=True)

    # --------------------------------------------------------------------------
    # 4. Initialize param_inventory
    # --------------------------------------------------------------------------
    logger.info("Initializing inventory parameters for each Store x Dept series...")
    unique_series = fact_sales_weekly[["store_id", "dept_id"]].drop_duplicates().sort_values(["store_id", "dept_id"])
    param_inventory = pd.DataFrame({
        "store_id": unique_series["store_id"],
        "dept_id": unique_series["dept_id"],
        "unit_cost": 10.00,
        "holding_rate_annual": 0.2000,
        "stockout_penalty_rate": 0.3000,
        "order_cost_fixed": 50.00,
        "lead_time_p1": 0.500,
        "lead_time_p2": 0.350,
        "lead_time_p3": 0.150
    }).reset_index(drop=True)

    return dim_store, dim_date, fact_sales_weekly, param_inventory


@retry_on_db_error()
def load_all_to_database(
    dim_store: pd.DataFrame,
    dim_date: pd.DataFrame,
    fact_sales_weekly: pd.DataFrame,
    param_inventory: pd.DataFrame,
    chunksize: int = 5000
) -> None:
    """Insert DataFrames in foreign-key safe order with fast_executemany."""
    engine = get_db_engine()
    logger.info("Connecting to database and clearing existing data in foreign-key safe order...")

    with engine.begin() as conn:
        if DB_BACKEND == "sqlite":
            conn.execute(text("DELETE FROM param_inventory;"))
            conn.execute(text("DELETE FROM fact_sales_weekly;"))
            conn.execute(text("DELETE FROM dim_date;"))
            conn.execute(text("DELETE FROM dim_store;"))
        else:
            # SQL Server
            conn.execute(text("DELETE FROM dbo.param_inventory;"))
            conn.execute(text("DELETE FROM dbo.fact_sales_weekly;"))
            conn.execute(text("DELETE FROM dbo.dim_date;"))
            conn.execute(text("DELETE FROM dbo.dim_store;"))

        logger.info(f"Loading {len(dim_store):,} rows into 'dim_store'...")
        dim_store.to_sql(
            name="dim_store", con=conn, if_exists="append", index=False,
            chunksize=1000, method="multi" if DB_BACKEND == "sqlite" else None
        )

        logger.info(f"Loading {len(dim_date):,} rows into 'dim_date'...")
        dim_date.to_sql(
            name="dim_date", con=conn, if_exists="append", index=False,
            chunksize=1000, method="multi" if DB_BACKEND == "sqlite" else None
        )

        logger.info(f"Loading {len(fact_sales_weekly):,} rows into 'fact_sales_weekly' (chunksize {chunksize})...")
        fact_sales_weekly.to_sql(
            name="fact_sales_weekly", con=conn, if_exists="append", index=False,
            chunksize=chunksize, method="multi" if DB_BACKEND == "sqlite" else None
        )

        logger.info(f"Loading {len(param_inventory):,} rows into 'param_inventory'...")
        param_inventory.to_sql(
            name="param_inventory", con=conn, if_exists="append", index=False,
            chunksize=1000, method="multi" if DB_BACKEND == "sqlite" else None
        )


def run_pipeline(generate_mock: bool = False) -> None:
    """Execute data ingestion pipeline."""
    start_time = datetime.now()
    logger.info("Starting StockSense Data Ingestion Pipeline...")

    if generate_mock:
        generate_mock_walmart_data(DATA_RAW_DIR)

    if not check_raw_files(DATA_RAW_DIR):
        raise FileNotFoundError(
            f"Kaggle CSV files missing in {DATA_RAW_DIR}. Expected: train.csv, features.csv, stores.csv. "
            "Please ensure real Kaggle CSV files are placed in data/raw/."
        )

    dim_store, dim_date, fact_sales_weekly, param_inventory = build_star_schema(DATA_RAW_DIR)

    # Save local Parquet cache
    logger.info(f"Caching clean processed parquet files to {DATA_PROCESSED_DIR}...")
    dim_store.to_parquet(DATA_PROCESSED_DIR / "dim_store.parquet", index=False)
    dim_date.to_parquet(DATA_PROCESSED_DIR / "dim_date.parquet", index=False)
    fact_sales_weekly.to_parquet(DATA_PROCESSED_DIR / "fact_sales_weekly.parquet", index=False)
    param_inventory.to_parquet(DATA_PROCESSED_DIR / "param_inventory.parquet", index=False)

    # Load to SQL database
    load_all_to_database(dim_store, dim_date, fact_sales_weekly, param_inventory)

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"Data ingestion pipeline completed successfully in {elapsed:.1f} seconds!")
    logger.info("Ingested Records Summary:")
    logger.info(f" - Stores: {len(dim_store):,}")
    logger.info(f" - Reporting Weeks: {len(dim_date):,}")
    logger.info(f" - Weekly Sales Records: {len(fact_sales_weekly):,}")
    logger.info(f" - Store x Dept Series: {len(param_inventory):,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StockSense Real Data Ingestion Pipeline")
    parser.add_argument(
        "--generate-mock",
        action="store_true",
        help="Explicitly generate mock sample data in data/raw/ (for testing only)"
    )
    args = parser.parse_args()

    run_pipeline(generate_mock=args.generate_mock)
