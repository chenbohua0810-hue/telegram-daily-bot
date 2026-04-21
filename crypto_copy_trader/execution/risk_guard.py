from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from models.portfolio import Portfolio


@dataclass(frozen=True)
class RiskCheckResult:
    passed: bool
    size_multiplier: float
    reasons: list[str]


def check_risk(
    *,
    new_symbol: str,
    new_size_usdt: Decimal,
    portfolio: Portfolio,
    correlation_provider: Callable[[str, list[str]], dict[str, float]],
    daily_pnl_pct: float,
    max_concurrent: int = 10,
    correlation_threshold: float = 0.8,
    daily_loss_circuit: float = -0.05,
) -> RiskCheckResult:
    reasons: list[str] = []
    size_multiplier = 1.0

    if len(portfolio.positions) >= max_concurrent:
        reasons.append("max_concurrent_reached")

    if daily_pnl_pct <= daily_loss_circuit:
        reasons.append("daily_loss_circuit")

    if reasons:
        return RiskCheckResult(passed=False, size_multiplier=0.0, reasons=reasons)

    correlations = correlation_provider(new_symbol, list(portfolio.positions))
    for symbol, correlation in correlations.items():
        if correlation > correlation_threshold:
            size_multiplier = 0.5
            reasons.append(f"high_correlation:{symbol}:{correlation:.2f}")

    return RiskCheckResult(passed=True, size_multiplier=size_multiplier, reasons=reasons)
