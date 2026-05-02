from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from models import OnChainEvent
from models import (
    SentimentCounts,
    SentimentSignal,
    TechnicalIndicators,
    TechnicalSignal,
)
from models import DecisionSnapshotBuilder


def build_event() -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc123",
        tx_hash="0xtxhash",
        block_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol="WETH",
        amount_token=Decimal("1.5"),
        amount_usd=Decimal("3000"),
        raw={"hash": "0xtxhash"},
        token_address="",
    )


def build_technical_signal() -> TechnicalSignal:
    return TechnicalSignal(
        trend="bullish",
        momentum="bullish",
        volatility="medium",
        stat_arb="breakout",
        confidence=0.8,
    )


def build_technical_indicators() -> TechnicalIndicators:
    return TechnicalIndicators(
        ema8=101.0,
        ema21=99.0,
        rsi=56.0,
        macd_hist=1.2,
        atr=2.1,
        atr_pct=0.02,
        bb_zscore=1.1,
        close_price=102.0,
    )


def build_sentiment_signal() -> SentimentSignal:
    return SentimentSignal(
        signal="bullish",
        score=0.7,
        source_count=12,
    )


def build_sentiment_counts() -> SentimentCounts:
    return SentimentCounts(
        positive=8,
        negative=2,
        neutral=2,
        mention_delta=0.3,
    )


def test_snapshot_skip_requires_reason() -> None:
    builder = DecisionSnapshotBuilder(
        event=build_event(),
        symbol="ETH/USDT",
        recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
    )

    snapshot = builder.execute("buy")

    assert snapshot.skip_reason is None

    with pytest.raises(ValueError):
        DecisionSnapshotBuilder(
            event=build_event(),
            symbol="ETH/USDT",
            recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
        ).skip("")


def test_snapshot_frozen() -> None:
    snapshot = DecisionSnapshotBuilder(
        event=build_event(),
        symbol="ETH/USDT",
        recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
    ).skip("below_min_trade_usd")

    with pytest.raises(FrozenInstanceError):
        snapshot.final_action = "buy"


def test_builder_quant_filter_skip() -> None:
    snapshot = DecisionSnapshotBuilder(
        event=build_event(),
        symbol="ETH/USDT",
        recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
    ).skip("below_min_trade_usd")

    assert snapshot.technical is None
    assert snapshot.sentiment is None
    assert snapshot.ai_confidence is None
    assert snapshot.risk is None
    assert snapshot.cost is None
    assert snapshot.final_action == "skip"


def test_builder_risk_blocked_skip() -> None:
    risk_result = SimpleNamespace(passed=False, multiplier=0.0, reasons=("circuit_breaker",))
    ai_score = SimpleNamespace(
        confidence=72,
        reasoning="Wallet quality is good but risk blocked the trade.",
        recommendation="execute",
    )

    snapshot = (
        DecisionSnapshotBuilder(
            event=build_event(),
            symbol="ETH/USDT",
            recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
        )
        .with_technical(build_technical_signal(), build_technical_indicators())
        .with_sentiment(build_sentiment_signal(), build_sentiment_counts())
        .with_ai(ai_score)
        .with_risk(risk_result)
        .skip("risk_blocked:circuit_breaker")
    )

    assert snapshot.risk is not None
    assert snapshot.cost is None
    assert snapshot.final_action == "skip"


def test_builder_full_execute_path() -> None:
    ai_score = SimpleNamespace(
        confidence=81,
        reasoning="Technicals, sentiment, and wallet quality are aligned.",
        recommendation="execute",
    )
    risk_result = SimpleNamespace(passed=True, multiplier=1.0, reasons=("ok",))
    cost_estimate = SimpleNamespace(
        slippage_pct=0.002,
        fee_pct=0.001,
        total_cost_pct=0.003,
        expected_profit_pct=0.025,
    )

    snapshot = (
        DecisionSnapshotBuilder(
            event=build_event(),
            symbol="ETH/USDT",
            recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
        )
        .with_technical(build_technical_signal(), build_technical_indicators())
        .with_sentiment(build_sentiment_signal(), build_sentiment_counts())
        .with_ai(ai_score)
        .with_risk(risk_result)
        .with_cost(cost_estimate)
        .with_market_regime(62000.0, 0.045)
        .execute("buy")
    )

    assert snapshot.technical is not None
    assert snapshot.sentiment is not None
    assert snapshot.ai_confidence == 81
    assert snapshot.risk is not None
    assert snapshot.cost is not None
    assert snapshot.btc_price_usdt == 62000.0
    assert snapshot.final_action == "buy"


def test_builder_reuse_raises() -> None:
    builder = DecisionSnapshotBuilder(
        event=build_event(),
        symbol="ETH/USDT",
        recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
    )
    builder.skip("below_min_trade_usd")

    with pytest.raises(RuntimeError):
        builder.execute("buy")
