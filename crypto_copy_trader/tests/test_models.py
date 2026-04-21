from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from models.decision import TradeDecision


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
