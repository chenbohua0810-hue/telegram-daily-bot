from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class CostEstimate:
    slippage_pct: float
    fee_pct: float
    total_cost_pct: float
    expected_profit_pct: float


def estimate_cost(
    *,
    order_usdt: float,
    symbol: str,
    orderbook_fetcher: Callable[[str], dict],
    use_bnb_discount: bool = True,
    technical_confidence: float,
) -> CostEstimate:
    orderbook = orderbook_fetcher(symbol)
    asks = orderbook.get("asks", [])
    slippage_pct = _estimate_slippage(order_usdt, asks)

    if order_usdt >= 100000:
        slippage_pct += 0.001

    fee_pct = 0.0015 if use_bnb_discount else 0.002
    expected_profit_pct = 0.05 * technical_confidence

    return CostEstimate(
        slippage_pct=round(slippage_pct, 4),
        fee_pct=fee_pct,
        total_cost_pct=round(slippage_pct + fee_pct, 4),
        expected_profit_pct=round(expected_profit_pct, 4),
    )


def should_reject(estimate: CostEstimate, max_cost_ratio: float = 0.30) -> bool:
    return estimate.total_cost_pct > estimate.expected_profit_pct * max_cost_ratio


def _estimate_slippage(order_usdt: float, asks: list[list[float]]) -> float:
    if order_usdt < 7500:
        return 0.001

    if not asks:
        return 0.0

    remaining = order_usdt
    touched_prices: list[float] = []

    for ask_price, ask_quantity in asks:
        level_notional = ask_price * ask_quantity
        touched_prices.append(float(ask_price))
        remaining -= level_notional
        if remaining <= 0:
            break

    best_ask = float(asks[0][0])
    average_price = sum(touched_prices) / len(touched_prices)
    return max(0.0, (average_price - best_ask) / best_ask)
