from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

Chain = Literal["eth", "sol", "bsc"]
TransactionType = Literal["swap_in", "swap_out"]


@dataclass(frozen=True)
class OnChainEvent:
    chain: Chain
    wallet: str
    tx_hash: str
    block_time: datetime
    tx_type: TransactionType
    token_symbol: str
    amount_token: Decimal
    amount_usd: Decimal
    raw: dict[str, Any]
    token_address: str
    is_mev_suspect: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "wallet": self.wallet,
            "tx_hash": self.tx_hash,
            "block_time": self.block_time.isoformat(),
            "tx_type": self.tx_type,
            "token_symbol": self.token_symbol,
            "token_address": self.token_address,
            "amount_token": str(self.amount_token),
            "amount_usd": str(self.amount_usd),
            "raw": self.raw,
            "is_mev_suspect": self.is_mev_suspect,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OnChainEvent":
        return cls(
            chain=payload["chain"],
            wallet=payload["wallet"],
            tx_hash=payload["tx_hash"],
            block_time=datetime.fromisoformat(payload["block_time"]),
            tx_type=payload["tx_type"],
            token_symbol=payload["token_symbol"],
            amount_token=Decimal(payload["amount_token"]),
            amount_usd=Decimal(payload["amount_usd"]),
            raw=payload["raw"],
            token_address=payload["token_address"],
            is_mev_suspect=bool(payload.get("is_mev_suspect", False)),
        )


# ---------------------------------------------------------------------------
# portfolio
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal
    avg_entry_price: Decimal
    entry_time: datetime
    source_wallet: str
    peak_price: Decimal | None = None


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


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------

TrendSignal = Literal["bullish", "bearish", "neutral"]
VolatilitySignal = Literal["low", "medium", "high"]
StatArbSignal = Literal["mean_revert", "breakout", "neutral"]
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
    binance_listable_pnl_180d: float = 0.0

    def __post_init__(self) -> None:
        _validate_choice(self.chain, "chain", CHAIN_VALUES)
        _validate_choice(self.trust_level, "trust_level", TRUST_VALUES)
        _validate_choice(self.status, "status", STATUS_VALUES)
        _validate_ratio(self.win_rate, "win_rate")
        _validate_ratio(self.max_drawdown, "max_drawdown")
        _validate_ratio(self.recent_win_rate, "recent_win_rate")
        _validate_non_negative(self.trade_count, "trade_count")
        _validate_non_negative(self.funds_usd, "funds_usd")
        _validate_non_negative(self.binance_listable_pnl_180d, "binance_listable_pnl_180d")


# ---------------------------------------------------------------------------
# decision
# ---------------------------------------------------------------------------

Action = Literal["buy", "sell", "hold", "skip"]
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+/USDT$")
MAX_REASONING_LENGTH = 200


@dataclass(frozen=True)
class TradeDecision:
    action: Action
    symbol: str
    quantity_usdt: float
    confidence: int
    reasoning: str
    source_wallet: str

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be between 0 and 100")

        if self.quantity_usdt < 0:
            raise ValueError("quantity_usdt must be non-negative")

        if not self.reasoning.strip():
            raise ValueError("reasoning must not be empty")

        if len(self.reasoning) > MAX_REASONING_LENGTH:
            raise ValueError("reasoning must not exceed 200 characters")

        if not SYMBOL_PATTERN.match(self.symbol):
            raise ValueError("symbol must match the format BASE/USDT")


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

AIRecommendation = Literal["execute", "skip"]
FinalAction = Literal["buy", "sell", "hold", "skip"]


@dataclass(frozen=True)
class RiskSnapshotView:
    passed: bool
    multiplier: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CostSnapshotView:
    slippage_pct: float
    fee_pct: float
    total_cost_pct: float
    expected_profit_pct: float


@dataclass(frozen=True)
class DecisionSnapshot:
    event_tx_hash: str
    source_wallet: str
    symbol: str
    recorded_at: datetime
    technical: TechnicalSignal | None
    technical_indicators: TechnicalIndicators | None
    sentiment: SentimentSignal | None
    sentiment_counts: SentimentCounts | None
    ai_confidence: int | None
    ai_reasoning: str | None
    ai_recommendation: AIRecommendation | None
    risk: RiskSnapshotView | None
    cost: CostSnapshotView | None
    btc_price_usdt: float | None
    btc_24h_volatility_pct: float | None
    final_action: FinalAction
    skip_reason: str | None
    trade_id: int | None

    def __post_init__(self) -> None:
        if self.final_action == "skip":
            if not self.skip_reason:
                raise ValueError("skip snapshots require skip_reason")
            if self.trade_id is not None:
                raise ValueError("skip snapshots must not have trade_id")
            return

        if self.final_action in {"buy", "sell"} and self.skip_reason is not None:
            raise ValueError("executed snapshots must not have skip_reason")


class DecisionSnapshotBuilder:
    def __init__(self, event: OnChainEvent, symbol: str, recorded_at: datetime) -> None:
        self._event = event
        self._symbol = symbol
        self._recorded_at = recorded_at
        self._technical: TechnicalSignal | None = None
        self._technical_indicators: TechnicalIndicators | None = None
        self._sentiment: SentimentSignal | None = None
        self._sentiment_counts: SentimentCounts | None = None
        self._ai_confidence: int | None = None
        self._ai_reasoning: str | None = None
        self._ai_recommendation: AIRecommendation | None = None
        self._risk: RiskSnapshotView | None = None
        self._cost: CostSnapshotView | None = None
        self._btc_price_usdt: float | None = None
        self._btc_24h_volatility_pct: float | None = None
        self._completed = False

    def _ensure_active(self) -> None:
        if self._completed:
            raise RuntimeError("builder already finalized")

    def with_technical(
        self,
        sig: TechnicalSignal,
        ind: TechnicalIndicators,
    ) -> "DecisionSnapshotBuilder":
        self._ensure_active()
        self._technical = sig
        self._technical_indicators = ind
        return self

    def with_sentiment(
        self,
        sig: SentimentSignal,
        counts: SentimentCounts,
    ) -> "DecisionSnapshotBuilder":
        self._ensure_active()
        self._sentiment = sig
        self._sentiment_counts = counts
        return self

    def with_ai(self, score: Any) -> "DecisionSnapshotBuilder":
        self._ensure_active()
        self._ai_confidence = score.confidence
        self._ai_reasoning = score.reasoning
        self._ai_recommendation = score.recommendation
        return self

    def with_risk(self, result: Any) -> "DecisionSnapshotBuilder":
        self._ensure_active()
        multiplier = getattr(result, "multiplier", None)
        if multiplier is None:
            multiplier = getattr(result, "size_multiplier")
        self._risk = RiskSnapshotView(
            passed=result.passed,
            multiplier=multiplier,
            reasons=tuple(result.reasons),
        )
        return self

    def with_cost(self, estimate: Any) -> "DecisionSnapshotBuilder":
        self._ensure_active()
        self._cost = CostSnapshotView(
            slippage_pct=estimate.slippage_pct,
            fee_pct=estimate.fee_pct,
            total_cost_pct=estimate.total_cost_pct,
            expected_profit_pct=estimate.expected_profit_pct,
        )
        return self

    def with_market_regime(
        self,
        btc_price: float,
        btc_vol_pct: float,
    ) -> "DecisionSnapshotBuilder":
        self._ensure_active()
        self._btc_price_usdt = btc_price
        self._btc_24h_volatility_pct = btc_vol_pct
        return self

    def skip(self, reason: str) -> DecisionSnapshot:
        self._ensure_active()
        if not reason.strip():
            raise ValueError("skip reason must not be empty")

        self._completed = True
        return self._build(final_action="skip", skip_reason=reason, trade_id=None)

    def execute(self, action: Literal["buy", "sell"]) -> DecisionSnapshot:
        self._ensure_active()
        self._completed = True
        return self._build(final_action=action, skip_reason=None, trade_id=None)

    def _build(
        self,
        final_action: FinalAction,
        skip_reason: str | None,
        trade_id: int | None,
    ) -> DecisionSnapshot:
        return DecisionSnapshot(
            event_tx_hash=self._event.tx_hash,
            source_wallet=self._event.wallet,
            symbol=self._symbol,
            recorded_at=self._recorded_at,
            technical=self._technical,
            technical_indicators=self._technical_indicators,
            sentiment=self._sentiment,
            sentiment_counts=self._sentiment_counts,
            ai_confidence=self._ai_confidence,
            ai_reasoning=self._ai_reasoning,
            ai_recommendation=self._ai_recommendation,
            risk=self._risk,
            cost=self._cost,
            btc_price_usdt=self._btc_price_usdt,
            btc_24h_volatility_pct=self._btc_24h_volatility_pct,
            final_action=final_action,
            skip_reason=skip_reason,
            trade_id=trade_id,
        )
