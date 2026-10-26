"""Unit tests for StockSense Phase 1: Data Ingestion and Star Schema Building."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import tempfile

from src.load_data import (
    generate_mock_walmart_data,
    build_star_schema,
)
from src.config import retry_on_db_error, parse_db_server


def test_parse_db_server():
    """Test parsing comma-delimited and standard server strings."""
    host, port = parse_db_server("localhost,1433")
    assert host == "localhost"
    assert port == 1433

    host2, port2 = parse_db_server("127.0.0.1:1433")
    assert host2 == "127.0.0.1"
    assert port2 == 1433

    host3, port3 = parse_db_server("sqlserver_container")
    assert host3 == "sqlserver_container"
    assert port3 == 1433


def test_mock_data_generation_and_schema():
    """Test generating mock data and verifying star schema transformations."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_path = Path(tmp_dir)
        generate_mock_walmart_data(raw_path)

        assert (raw_path / "stores.csv").exists()
        assert (raw_path / "features.csv").exists()
        assert (raw_path / "train.csv").exists()

        dim_store, dim_date, fact_sales, param_inv = build_star_schema(raw_path)

        # 1. Check dim_store
        assert not dim_store.empty
        assert set(dim_store.columns) == {"store_id", "store_type", "store_size"}
        assert dim_store["store_id"].is_unique

        # 2. Check dim_date
        assert not dim_date.empty
        assert "date_key" in dim_date.columns
        assert "full_date" in dim_date.columns
        assert "is_holiday_week" in dim_date.columns
        assert (dim_date["date_key"] >= 20100101).all()

        # 3. Check fact_sales_weekly
        assert not fact_sales.empty
        assert "weekly_sales" in fact_sales.columns
        assert "markdown_total" in fact_sales.columns
        assert "has_markdown" in fact_sales.columns
        assert "is_negative_sales" in fact_sales.columns
        assert fact_sales["markdown_total"].isna().sum() == 0, "Markdowns must not contain NaNs"

        neg_rows = fact_sales[fact_sales["weekly_sales"] < 0]
        if len(neg_rows) > 0:
            assert (neg_rows["is_negative_sales"] == 1).all()

        # 4. Check param_inventory
        assert not param_inv.empty
        assert set(param_inv.columns) == {
            "store_id", "dept_id", "unit_cost", "holding_rate_annual",
            "stockout_penalty_rate", "order_cost_fixed", "lead_time_p1",
            "lead_time_p2", "lead_time_p3"
        }
        lt_sum = param_inv["lead_time_p1"] + param_inv["lead_time_p2"] + param_inv["lead_time_p3"]
        assert np.allclose(lt_sum, 1.0)


def test_retry_decorator_recovers():
    """Test that retry_on_db_error retries on transient connection error and succeeds."""
    call_count = 0

    @retry_on_db_error(max_retries=3, initial_delay=0.01, backoff_factor=1.0)
    def flaky_db_call():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("Database error: communication link failure")
        return "SUCCESS"

    result = flaky_db_call()
    assert result == "SUCCESS"
    assert call_count == 3
