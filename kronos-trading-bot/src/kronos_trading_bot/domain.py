from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SignalAction(StrEnum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"


class TradeSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class DataQualityReport:
    symbol: str | None
    passed: bool
    errors: list[str]
    candle_count: int
    latest_timestamp: datetime | None


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: SignalAction
    predicted_return: float
    confidence_score: float
    model_used: str
    reason_code: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason_code: str
    adjusted_notional_usdt: float | None = None


@dataclass(frozen=True)
class PaperPosition:
    symbol: str
    quantity: float
    average_entry_price: float


@dataclass(frozen=True)
class PaperFill:
    symbol: str
    side: TradeSide
    quantity: float
    fill_price: float
    notional_usdt: float
    fee_usdt: float
    realized_pnl_usdt: float = 0.0
