from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from models.events import OnChainEvent
from models.signals import (
    SentimentCounts,
    SentimentSignal,
    TechnicalIndicators,
    TechnicalSignal,
)


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
        self._risk = RiskSnapshotView(
            passed=result.passed,
            multiplier=result.multiplier,
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
