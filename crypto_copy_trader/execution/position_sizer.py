from __future__ import annotations

from decimal import Decimal

from models.portfolio import Portfolio


def compute_position_size(
    *,
    portfolio: Portfolio,
    asset_volatility: float,
    target_daily_vol: float = 0.02,
    max_position_pct: float = 0.10,
) -> Decimal:
    base = float(portfolio.total_value_usdt) * max_position_pct
    volatility_floor = max(asset_volatility, 0.005)
    vol_adj = target_daily_vol / volatility_floor
    raw = base * vol_adj
    return Decimal(str(min(raw, float(portfolio.cash_usdt))))
