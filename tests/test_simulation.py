"""Unit tests for StockSense Phase 3: Monte Carlo Simulation Engine."""

import pytest
import numpy as np

from src.simulate_inventory import simulate_inventory_policy, compute_textbook_reorder_point


def test_zero_variance_hand_calculation():
    """Verify simulation with zero demand variance and fixed lead time matches hand calculation.

    Hand-Calculated Setup:
    - 13 weeks with constant demand = 100 units / week.
    - Zero variance: residual ratio = 1.0.
    - Fixed lead time: L = 1 week with 100% probability.
    - Starting inventory: I_0 = 200.
    - Policy: s = 100, S = 300.
    - Economics: unit_cost = $10, holding_rate = 20%/yr, order_cost = $50.

    Exact Analytical Progression:
    - Week 1: On-hand=100, IP=100 <= s -> Order Q=200 placed, arrives wk 2.
    - Week 2: Arrivals=200, On-hand=200, IP=200 > s -> No order.
    - Week 3: On-hand=100, IP=100 <= s -> Order Q=200 placed, arrives wk 3.
    ... alternating for 13 weeks.

    Expected Outputs:
    - 7 weeks with ending on-hand = 100, 6 weeks with ending on-hand = 200.
    - Total ending on-hand sum = 7*100 + 6*200 = 1,900.
    - Average on-hand = 1,900 / 13 = 146.1538 units.
    - Total orders placed = 7 orders -> Order Cost = 7 * $50 = $350.00.
    - Holding Cost = 1,900 * (10 * 0.20 / 52) = $73.0769.
    - Stockout Cost = $0.00 (Zero stockouts).
    - Expected Total Cost = $350.00 + $73.08 = $423.08.
    - Fill Rate = 100.0%, Stockout Prob = 0.0%.
    - P05 Cost = P95 Cost = Expected Total Cost (Zero Variance).
    """
    n_weeks = 13
    forecast_horizon = np.full(n_weeks, 100.0)
    residual_ratios = np.array([1.0])  # Zero variance

    out = simulate_inventory_policy(
        forecast_horizon=forecast_horizon,
        residual_ratios=residual_ratios,
        reorder_point_s=100,
        order_up_to_S=300,
        unit_cost=10.0,
        holding_rate_annual=0.20,
        stockout_penalty_rate=0.30,
        order_cost_fixed=50.0,
        lead_time_probs=(1.0, 0.0, 0.0),  # Fixed 1 week lead time
        n_runs=100,  # Any run count yields identical results
        seed=42
    )

    # 1. Verification of service metrics
    assert out["fill_rate"] == 1.0000, "Fill rate must be exactly 100%"
    assert out["stockout_prob"] == 0.0000, "Stockout probability must be exactly 0%"

    # 2. Verification of inventory levels
    expected_avg_on_hand = round(1900.0 / 13.0, 2)
    assert np.isclose(out["avg_on_hand"], expected_avg_on_hand, atol=0.01)

    # 3. Verification of costs
    expected_holding = round(1900.0 * (2.0 / 52.0), 2)  # $73.08
    expected_order = 350.00
    expected_stockout = 0.00
    expected_total = expected_holding + expected_order + expected_stockout  # $423.08

    assert np.isclose(out["holding_cost"], expected_holding, atol=0.05)
    assert np.isclose(out["order_cost"], expected_order, atol=0.01)
    assert np.isclose(out["stockout_cost"], expected_stockout, atol=0.01)
    assert np.isclose(out["total_cost"], expected_total, atol=0.05)

    # 4. Zero variance distribution: P05 == P95 == Mean
    assert np.isclose(out["p05_cost"], out["total_cost"], atol=0.05)
    assert np.isclose(out["p95_cost"], out["total_cost"], atol=0.05)


def test_textbook_reorder_point_formula():
    """Verify textbook reorder point calculation under known inputs."""
    mean_d = 1000.0
    std_d = 200.0
    # L_bar = 1.65, sigma_L^2 = 0.5275, service_level = 95% (z = 1.64485)
    s_calc = compute_textbook_reorder_point(
        mean_demand=mean_d,
        std_demand=std_d,
        lead_time_mean=1.65,
        lead_time_var=0.5275,
        service_level=0.95
    )
    # sigma_LT = sqrt(1.65 * 40000 + 1000000 * 0.5275) = sqrt(66000 + 527500) = sqrt(593500) = 770.3895
    # mu_LT = 1650
    # s = 1650 + 1.64485 * 770.3895 = 1650 + 1267.18 = 2917
    assert s_calc == 2917
