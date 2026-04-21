from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from models.events import OnChainEvent
from models.signals import SentimentSignal, TechnicalSignal, WalletScore
from signals.ai_scorer import AIScorerError, score_signal


def build_event() -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc123",
        tx_hash="0xtx",
        block_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol="ETH",
        amount_token=Decimal("1"),
        amount_usd=Decimal("2000"),
        raw={"block_number": 100},
    )


def build_wallet() -> WalletScore:
    return WalletScore(
        address="0xabc123",
        chain="eth",
        win_rate=0.7,
        trade_count=50,
        max_drawdown=0.2,
        funds_usd=100000.0,
        recent_win_rate=0.72,
        trust_level="high",
        status="active",
    )


def build_technical() -> TechnicalSignal:
    return TechnicalSignal(
        trend="bullish",
        momentum="bullish",
        volatility="medium",
        stat_arb="breakout",
        confidence=0.8,
    )


def build_sentiment() -> SentimentSignal:
    return SentimentSignal(signal="bullish", score=0.7, source_count=10)


def build_client(*responses: str) -> SimpleNamespace:
    async def create(**kwargs):
        payload = responses_list.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(text=payload)])

    responses_list = list(responses)
    return SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=create)))


@pytest.mark.asyncio
async def test_ai_scorer_happy_path() -> None:
    client = build_client('{"confidence_score":75,"reasoning":"趨勢與情緒一致","recommendation":"execute"}')

    result = await score_signal(
        event=build_event(),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
        anthropic_client=client,
        model="claude-test",
    )

    assert result.confidence_score == 75
    assert result.recommendation == "execute"


@pytest.mark.asyncio
async def test_ai_scorer_invalid_json_retries() -> None:
    client = build_client(
        "not json",
        '{"confidence_score":65,"reasoning":"第二次成功","recommendation":"execute"}',
    )

    result = await score_signal(
        event=build_event(),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
        anthropic_client=client,
        model="claude-test",
    )

    assert result.confidence_score == 65
    assert client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_ai_scorer_all_fails_raises() -> None:
    client = build_client("not json", "still not json")

    with pytest.raises(AIScorerError):
        await score_signal(
            event=build_event(),
            wallet=build_wallet(),
            technical=build_technical(),
            sentiment=build_sentiment(),
            anthropic_client=client,
            model="claude-test",
        )


@pytest.mark.asyncio
async def test_ai_scorer_low_confidence_forces_skip() -> None:
    client = build_client('{"confidence_score":59,"reasoning":"信心不足","recommendation":"execute"}')

    result = await score_signal(
        event=build_event(),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
        anthropic_client=client,
        model="claude-test",
    )

    assert result.confidence_score == 59
    assert result.recommendation == "execute"


@pytest.mark.asyncio
async def test_ai_scorer_strips_markdown_fence() -> None:
    client = build_client(
        '```json\n{"confidence_score":72,"reasoning":"可執行","recommendation":"execute"}\n```'
    )

    result = await score_signal(
        event=build_event(),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
        anthropic_client=client,
        model="claude-test",
    )

    assert result.confidence_score == 72
