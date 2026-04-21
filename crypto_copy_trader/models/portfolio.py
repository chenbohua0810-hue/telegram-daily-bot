from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal
    avg_entry_price: Decimal
    entry_time: datetime
    source_wallet: str


@dataclass(frozen=True)
class Portfolio:
    cash_usdt: Decimal
    positions: dict[str, Position]
    total_value_usdt: Decimal
    daily_pnl_pct: float

    def validate(self) -> None:
        if not isinstance(self.positions, dict):
            raise ValueError("positions must be a dictionary")

        if self.total_value_usdt < self.cash_usdt:
            raise ValueError("total_value_usdt must be greater than or equal to cash_usdt")
