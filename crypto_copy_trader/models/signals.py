from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TrendSignal = Literal["bullish", "bearish", "neutral"]
VolatilitySignal = Literal["low", "medium", "high"]
StatArbSignal = Literal["mean_revert", "breakout", "neutral"]
Chain = Literal["eth", "sol", "bsc"]
TrustLevel = Literal["high", "medium", "low"]
WalletStatus = Literal["active", "watch", "retired"]
TREND_VALUES = {"bullish", "bearish", "neutral"}
VOLATILITY_VALUES = {"low", "medium", "high"}
STAT_ARB_VALUES = {"mean_revert", "breakout", "neutral"}
CHAIN_VALUES = {"eth", "sol", "bsc"}
TRUST_VALUES = {"high", "medium", "low"}
STATUS_VALUES = {"active", "watch", "retired"}


def _validate_ratio(value: float, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")


def _validate_non_negative(value: float | int, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _validate_choice(value: str, field_name: str, valid_values: set[str]) -> None:
    if value not in valid_values:
        raise ValueError(f"{field_name} must be one of {sorted(valid_values)}")


def classify_trust_level(
    win_rate: float,
    trade_count: int,
    max_drawdown: float,
) -> TrustLevel:
    _validate_ratio(win_rate, "win_rate")
    _validate_ratio(max_drawdown, "max_drawdown")
    _validate_non_negative(trade_count, "trade_count")

    if win_rate >= 0.65 and trade_count >= 50 and max_drawdown <= 0.25:
        return "high"

    if 0.55 <= win_rate < 0.65 and 20 <= trade_count < 50 and 0.25 <= max_drawdown <= 0.40:
        return "medium"

    return "low"


@dataclass(frozen=True)
class TechnicalSignal:
    trend: TrendSignal
    momentum: TrendSignal
    volatility: VolatilitySignal
    stat_arb: StatArbSignal
    confidence: float

    def __post_init__(self) -> None:
        _validate_choice(self.trend, "trend", TREND_VALUES)
        _validate_choice(self.momentum, "momentum", TREND_VALUES)
        _validate_choice(self.volatility, "volatility", VOLATILITY_VALUES)
        _validate_choice(self.stat_arb, "stat_arb", STAT_ARB_VALUES)
        _validate_ratio(self.confidence, "confidence")


@dataclass(frozen=True)
class TechnicalIndicators:
    ema8: float
    ema21: float
    rsi: float
    macd_hist: float
    atr: float
    atr_pct: float
    bb_zscore: float
    close_price: float


@dataclass(frozen=True)
class SentimentSignal:
    signal: TrendSignal
    score: float
    source_count: int

    def __post_init__(self) -> None:
        _validate_choice(self.signal, "signal", TREND_VALUES)
        _validate_ratio(self.score, "score")
        _validate_non_negative(self.source_count, "source_count")


@dataclass(frozen=True)
class SentimentCounts:
    positive: int
    negative: int
    neutral: int
    mention_delta: float

    def __post_init__(self) -> None:
        _validate_non_negative(self.positive, "positive")
        _validate_non_negative(self.negative, "negative")
        _validate_non_negative(self.neutral, "neutral")


@dataclass(frozen=True)
class WalletScore:
    address: str
    chain: Chain
    win_rate: float
    trade_count: int
    max_drawdown: float
    funds_usd: float
    recent_win_rate: float
    trust_level: TrustLevel
    status: WalletStatus

    def __post_init__(self) -> None:
        _validate_choice(self.chain, "chain", CHAIN_VALUES)
        _validate_choice(self.trust_level, "trust_level", TRUST_VALUES)
        _validate_choice(self.status, "status", STATUS_VALUES)
        _validate_ratio(self.win_rate, "win_rate")
        _validate_ratio(self.max_drawdown, "max_drawdown")
        _validate_ratio(self.recent_win_rate, "recent_win_rate")
        _validate_non_negative(self.trade_count, "trade_count")
        _validate_non_negative(self.funds_usd, "funds_usd")
