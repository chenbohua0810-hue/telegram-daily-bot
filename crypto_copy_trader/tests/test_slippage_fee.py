from __future__ import annotations

from signals.slippage_fee import CostEstimate, estimate_cost, should_reject


def test_small_order_fixed_slippage() -> None:
    estimate = estimate_cost(
        order_usdt=5000,
        symbol="ETH/USDT",
        orderbook_fetcher=lambda symbol: {"bids": [], "asks": [[100, 50]]},
        technical_confidence=0.8,
    )

    assert estimate.slippage_pct == 0.001


def test_medium_order_depth_estimation() -> None:
    estimate = estimate_cost(
        order_usdt=7500,
        symbol="ETH/USDT",
        orderbook_fetcher=lambda symbol: {"bids": [], "asks": [[100, 50], [101, 100]]},
        technical_confidence=0.8,
    )

    assert estimate.slippage_pct == 0.005


def test_bnb_discount_applies() -> None:
    estimate = estimate_cost(
        order_usdt=5000,
        symbol="ETH/USDT",
        orderbook_fetcher=lambda symbol: {"bids": [], "asks": [[100, 50]]},
        use_bnb_discount=True,
        technical_confidence=0.8,
    )

    assert estimate.fee_pct == 0.0015


def test_should_reject_when_cost_too_high() -> None:
    estimate = CostEstimate(
        slippage_pct=0.005,
        fee_pct=0.015,
        total_cost_pct=0.02,
        expected_profit_pct=0.05,
    )

    assert should_reject(estimate, max_cost_ratio=0.30) is True


def test_should_accept_when_cost_low() -> None:
    estimate = CostEstimate(
        slippage_pct=0.002,
        fee_pct=0.008,
        total_cost_pct=0.01,
        expected_profit_pct=0.05,
    )

    assert should_reject(estimate, max_cost_ratio=0.30) is False
