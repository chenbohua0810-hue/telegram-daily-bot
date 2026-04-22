from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from models.events import OnChainEvent
from models.signals import SentimentSignal, TechnicalSignal, WalletScore
from signals.ai_scorer import AIScore
from signals.llm_backend import LLMBackendError


class RecordingBackend:
    name = "recording"

    def __init__(self, responses: list[list[dict]] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, object]] = []

    async def score_one(self, prompt: str, *, max_tokens: int) -> dict:
        raise NotImplementedError

    async def score_batch(self, prompts: list[str], *, max_tokens: int) -> list[dict]:
        self.calls.append({"prompts": prompts, "max_tokens": max_tokens})
        if self._responses:
            return self._responses.pop(0)
        return []


def build_event(*, tx_hash: str = "tx-1", symbol: str = "ETH", amount_usd: str = "2000") -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc123",
        tx_hash=tx_hash,
        block_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol=symbol,
        amount_token=Decimal("1"),
        amount_usd=Decimal(amount_usd),
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


@pytest.mark.asyncio
async def test_batch_scorer_flushes_when_reaching_max_batch_size() -> None:
    from signals.batch_scorer import BatchScorer

    backend = RecordingBackend(
        responses=[
            [
                {"index": 1, "confidence_score": 80, "reasoning": "a", "recommendation": "execute"},
                {"index": 2, "confidence_score": 40, "reasoning": "b", "recommendation": "skip"},
            ]
        ]
    )
    scorer = BatchScorer(backend=backend, window_seconds=60, max_batch_size=2)

    first_future = await scorer.submit(
        event=build_event(tx_hash="tx-1"),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
    )
    second_future = await scorer.submit(
        event=build_event(tx_hash="tx-2", symbol="SOL"),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
    )

    first_result = await first_future
    second_result = await second_future

    assert len(backend.calls) == 1
    assert first_result == AIScore(confidence_score=80, reasoning="a", recommendation="execute")
    assert second_result == AIScore(confidence_score=40, reasoning="b", recommendation="skip")


@pytest.mark.asyncio
async def test_batch_scorer_flushes_on_window_timeout() -> None:
    from signals.batch_scorer import BatchScorer

    backend = RecordingBackend(
        responses=[
            [{"index": 1, "confidence_score": 75, "reasoning": "timeout", "recommendation": "execute"}]
        ]
    )
    scorer = BatchScorer(backend=backend, window_seconds=0, max_batch_size=5)

    future = await scorer.submit(
        event=build_event(tx_hash="tx-timeout"),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
    )

    result = await future

    assert len(backend.calls) == 1
    assert result == AIScore(confidence_score=75, reasoning="timeout", recommendation="execute")


@pytest.mark.asyncio
async def test_batch_scorer_resolves_futures_by_response_index() -> None:
    from signals.batch_scorer import BatchScorer

    backend = RecordingBackend(
        responses=[
            [
                {"index": 1, "confidence_score": 10, "reasoning": "first", "recommendation": "skip"},
                {"index": 2, "confidence_score": 90, "reasoning": "second", "recommendation": "execute"},
                {"index": 3, "confidence_score": 55, "reasoning": "third", "recommendation": "skip"},
            ]
        ]
    )
    scorer = BatchScorer(backend=backend, window_seconds=60, max_batch_size=3)

    futures = [
        await scorer.submit(
            event=build_event(tx_hash=f"tx-{index}"),
            wallet=build_wallet(),
            technical=build_technical(),
            sentiment=build_sentiment(),
        )
        for index in range(3)
    ]

    results = await asyncio.gather(*futures)

    assert [result.confidence_score for result in results] == [10, 90, 55]
    assert [result.reasoning for result in results] == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_batch_scorer_wrong_length_response_raises_and_sets_future_errors() -> None:
    from signals.batch_scorer import BatchScorer

    backend = RecordingBackend(
        responses=[
            [{"index": 1, "confidence_score": 80, "reasoning": "only-one", "recommendation": "execute"}]
        ]
    )
    scorer = BatchScorer(backend=backend, window_seconds=60, max_batch_size=2)

    first_future = await scorer.submit(
        event=build_event(tx_hash="tx-1"),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
    )
    second_future = await scorer.submit(
        event=build_event(tx_hash="tx-2"),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
    )

    with pytest.raises(LLMBackendError):
        await asyncio.gather(first_future, second_future)

    assert first_future.done()
    assert second_future.done()
    assert isinstance(first_future.exception(), LLMBackendError)
    assert isinstance(second_future.exception(), LLMBackendError)


@pytest.mark.asyncio
async def test_batch_scorer_splits_batches_when_prompt_token_estimate_overflows() -> None:
    from signals.batch_scorer import BatchScorer

    backend = RecordingBackend(
        responses=[
            [{"index": 1, "confidence_score": 61, "reasoning": "left", "recommendation": "execute"}],
            [{"index": 1, "confidence_score": 62, "reasoning": "right", "recommendation": "skip"}],
        ]
    )
    scorer = BatchScorer(backend=backend, window_seconds=60, max_batch_size=3)

    first_future = await scorer.submit(
        event=build_event(tx_hash="tx-overflow-1", symbol="LONGA", amount_usd="999999"),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
    )
    second_future = await scorer.submit(
        event=build_event(tx_hash="tx-overflow-2", symbol="LONGB", amount_usd="999998"),
        wallet=build_wallet(),
        technical=build_technical(),
        sentiment=build_sentiment(),
    )

    estimate_calls = iter([6001, 100, 100])
    scorer._estimate_input_tokens = lambda prompt: next(estimate_calls)  # type: ignore[method-assign]

    await scorer.flush()
    results = await asyncio.gather(first_future, second_future)

    assert len(backend.calls) == 2
    assert [result.confidence_score for result in results] == [61, 62]
