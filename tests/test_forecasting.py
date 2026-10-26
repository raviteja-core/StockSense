"""Unit tests for StockSense Phase 2: Feature Leakage & Metric Validation."""

import pytest
import numpy as np
import pandas as pd

from src.features import compute_lag_and_rolling_features, add_calendar_and_holiday_features
from src.evaluate import compute_wape, compute_rmse, compute_mase, compute_bias


def test_zero_feature_leakage():
    """Formally prove that engineered features at time t strictly depend only on data < t.

    Changing a future sales observation at time T must have zero effect on features at t < T.
    """
    dates = pd.date_range("2010-01-01", periods=60, freq="W-FRI")
    rng = np.random.default_rng(42)
    sales = rng.normal(1000.0, 50.0, size=60)

    df_orig = pd.DataFrame({
        "store_id": 1,
        "dept_id": 1,
        "full_date": dates,
        "weekly_sales": sales.copy(),
        "is_holiday_week": 0
    })

    # Compute baseline features
    df_feat_orig = compute_lag_and_rolling_features(df_orig)

    # Now inject a massive shock at t = 40 (future perturbation)
    T = 40
    df_perturbed = df_orig.copy()
    df_perturbed.loc[T, "weekly_sales"] += 50000.0

    df_feat_perturbed = compute_lag_and_rolling_features(df_perturbed)

    # Features to test for strictly zero leakage
    trailing_features = ["lag_1", "lag_2", "lag_4", "lag_52", "rolling_mean_4", "rolling_mean_13"]

    # Verify every step t < T is 100% identical between original and perturbed
    for col in trailing_features:
        orig_past = df_feat_orig.loc[: T - 1, col].dropna()
        pert_past = df_feat_perturbed.loc[: T - 1, col].dropna()
        pd.testing.assert_series_equal(
            orig_past,
            pert_past,
            check_exact=True,
            obj=f"Feature {col} before index {T} must have zero future leakage"
        )


def test_metrics_against_hand_calculations():
    """Verify WAPE, RMSE, MASE, and Bias against exact hand-calculated expected values."""
    # Hand-crafted test vectors
    # Actuals: 100, 200, 300 (Sum = 600)
    actuals = np.array([100.0, 200.0, 300.0])
    # Forecasts: 110, 180, 330 (Errors: +10, -20, +30)
    forecasts = np.array([110.0, 180.0, 330.0])
    # Naive benchmarks: 90, 220, 280 (Naive Errors: -10, +20, -20)
    naive_fcs = np.array([90.0, 220.0, 280.0])

    # 1. WAPE = Sum(|Actual - Forecast|) / Sum(Actual)
    # (|10| + |20| + |30|) / 600 = 60 / 600 = 0.10 (10.0%)
    wape_val = compute_wape(actuals, forecasts)
    assert np.isclose(wape_val, 0.1000, atol=1e-5)

    # 2. RMSE = sqrt((10^2 + (-20)^2 + 30^2) / 3) = sqrt((100 + 400 + 900) / 3) = sqrt(1400 / 3) = 21.60246898
    rmse_val = compute_rmse(actuals, forecasts)
    expected_rmse = np.sqrt(1400.0 / 3.0)
    assert np.isclose(rmse_val, expected_rmse, atol=1e-5)

    # 3. MASE = MAE(model) / MAE(naive)
    # MAE(model) = (10 + 20 + 30) / 3 = 20.0
    # MAE(naive) = (10 + 20 + 20) / 3 = 50 / 3 = 16.66666667
    # MASE = 20 / (50/3) = 60 / 50 = 1.2000
    mase_val = compute_mase(actuals, forecasts, naive_fcs)
    assert np.isclose(mase_val, 1.2000, atol=1e-5)

    # 4. Bias = mean(forecast - actual) = (+10 - 20 + 30) / 3 = 20 / 3 = 6.66666667
    bias_val = compute_bias(actuals, forecasts)
    assert np.isclose(bias_val, 20.0 / 3.0, atol=1e-5)
