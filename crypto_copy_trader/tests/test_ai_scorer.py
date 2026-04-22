from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from models.events import OnChainEvent
from models.signals import SentimentSignal, TechnicalSignal, WalletScore
from signals.ai_scorer import AIScorerError, score_signal
from signals.llm_backend import LLMBackendError


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


class _MockBackend:
    """Minimal LLMBackend stand-in for score_signal tests."""

    name = "mock"

    def __init__(self, response: dict | Exception) -> None:
        self._response = response

    async def score_one(self, prompt: str, *, max_tokens: int) -> dict:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def score_batch(self, prompts: list[str], *, max_tokens: int) -> list[dict]:
        return [await self.score_one(p, max_tokens=max_tokens) for p in prompts]


@pytest.mark.asyncio
async def test_ai_scorer_happy_path() -> None:
    backend = _MockBackend({"confidence_score": 75, "reasoning": "趨勢與情緒一致", "recommendation": "execute"})

    result = await score_signal(
        event=build_event(),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
        backend=backend,
    )

    assert result.confidence_score == 75
    assert result.recommendation == "execute"


@pytest.mark.asyncio
async def test_ai_scorer_backend_error_raises_scorer_error() -> None:
    backend = _MockBackend(LLMBackendError("all attempts failed"))

    with pytest.raises(AIScorerError):
        await score_signal(
            event=build_event(),
            wallet=build_wallet(),
            technical=build_technical(),
            sentiment=build_sentiment(),
            backend=backend,
        )


@pytest.mark.asyncio
async def test_ai_scorer_low_confidence_returned_unchanged() -> None:
    backend = _MockBackend({"confidence_score": 59, "reasoning": "信心不足", "recommendation": "execute"})

    result = await score_signal(
        event=build_event(),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
        backend=backend,
    )

    assert result.confidence_score == 59
    assert result.recommendation == "execute"


@pytest.mark.asyncio
async def test_ai_scorer_skip_recommendation_preserved() -> None:
    backend = _MockBackend({"confidence_score": 80, "reasoning": "不利", "recommendation": "skip"})

    result = await score_signal(
        event=build_event(),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
        backend=backend,
    )

    assert result.recommendation == "skip"
