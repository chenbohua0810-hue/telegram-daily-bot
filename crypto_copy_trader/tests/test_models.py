from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from models.decision import TradeDecision
from models.signals import (
    SentimentSignal,
    TechnicalSignal,
    WalletScore,
    classify_trust_level,
)


def test_decision_valid_buy() -> None:
    decision = TradeDecision(
        action="buy",
        symbol="BTC/USDT",
        quantity_usdt=1000.0,
        confidence=75,
        reasoning="Momentum and wallet conviction support a follow trade.",
        source_wallet="0xabc123",
    )

    assert decision.action == "buy"
    assert decision.symbol == "BTC/USDT"


def test_decision_confidence_out_of_range() -> None:
    with pytest.raises(ValueError):
        TradeDecision(
            action="buy",
            symbol="BTC/USDT",
            quantity_usdt=1000.0,
            confidence=101,
            reasoning="Confidence cannot exceed the valid range.",
            source_wallet="0xabc123",
        )


def test_decision_negative_quantity() -> None:
    with pytest.raises(ValueError):
        TradeDecision(
            action="buy",
            symbol="BTC/USDT",
            quantity_usdt=-1.0,
            confidence=50,
            reasoning="Quantity must be non-negative.",
            source_wallet="0xabc123",
        )


def test_decision_invalid_symbol() -> None:
    with pytest.raises(ValueError):
        TradeDecision(
            action="buy",
            symbol="btc-usdt",
            quantity_usdt=1000.0,
            confidence=50,
            reasoning="Symbol must match the expected trading pair format.",
            source_wallet="0xabc123",
        )


def test_decision_is_frozen() -> None:
    decision = TradeDecision(
        action="buy",
        symbol="BTC/USDT",
        quantity_usdt=1000.0,
        confidence=75,
        reasoning="The decision object should be immutable once created.",
        source_wallet="0xabc123",
    )

    with pytest.raises(FrozenInstanceError):
        decision.action = "sell"


def test_technical_signal_confidence_out_of_range() -> None:
    with pytest.raises(ValueError):
        TechnicalSignal(
            trend="bullish",
            momentum="bullish",
            volatility="medium",
            stat_arb="breakout",
            confidence=1.1,
        )


def test_sentiment_signal_negative_source_count() -> None:
    with pytest.raises(ValueError):
        SentimentSignal(
            signal="neutral",
            score=0.5,
            source_count=-1,
        )


def test_wallet_score_invalid_chain() -> None:
    with pytest.raises(ValueError):
        WalletScore(
            address="0xabc123",
            chain="btc",
            win_rate=0.7,
            trade_count=60,
            max_drawdown=0.2,
            funds_usd=150000.0,
            recent_win_rate=0.72,
            trust_level="high",
            status="active",
        )


def test_classify_trust_high() -> None:
    assert classify_trust_level(0.70, 60, 0.20) == "high"


def test_classify_trust_medium() -> None:
    assert classify_trust_level(0.60, 30, 0.35) == "medium"


def test_classify_trust_low() -> None:
    assert classify_trust_level(0.50, 10, 0.30) == "low"


def test_classify_trust_boundary_high_min() -> None:
    assert classify_trust_level(0.65, 50, 0.25) == "high"
