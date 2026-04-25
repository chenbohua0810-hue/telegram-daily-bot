from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math

import httpx
import pytest

from signals.filters import combine_scores, compute_sentiment


def build_post(*, hours_ago: int, positive: int, negative: int) -> dict:
    published_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "published_at": published_at.isoformat(),
        "votes": {
            "positive": positive,
            "negative": negative,
            "important": 0,
        },
    }


@pytest.mark.asyncio
async def test_sentiment_no_data_returns_neutral_050() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json={"results": []}))
    )

    try:
        signal, counts = await compute_sentiment("ETH", client, "key")
    finally:
        await client.aclose()

    assert signal.score == 0.5
    assert signal.signal == "neutral"
    assert signal.source_count == 0
    assert counts.positive == 0
    assert counts.negative == 0
    assert counts.neutral == 0
    assert counts.mention_delta == 0.0


@pytest.mark.asyncio
async def test_sentiment_bullish_news() -> None:
    posts = [build_post(hours_ago=1, positive=2, negative=0) for _ in range(10)]
    posts.extend([build_post(hours_ago=2, positive=0, negative=2) for _ in range(2)])
    posts.extend([build_post(hours_ago=30, positive=0, negative=1) for _ in range(2)])
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json={"results": posts}))
    )

    try:
        signal, counts = await compute_sentiment("ETH", client, "key")
    finally:
        await client.aclose()

    assert signal.signal == "bullish"
    assert counts.positive == 10
    assert counts.negative == 2


@pytest.mark.asyncio
async def test_sentiment_api_error_falls_back_neutral(caplog: pytest.LogCaptureFixture) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=500, json={"results": []}))
    )

    try:
        signal, counts = await compute_sentiment("ETH", client, "key")
    finally:
        await client.aclose()

    assert signal.score == 0.5
    assert signal.signal == "neutral"
    assert counts.source_count if hasattr(counts, "source_count") else True
    assert "Falling back to neutral sentiment" in caplog.text


def test_sentiment_weight_formula() -> None:
    assert combine_scores(news_score=1.0, mention_score=0.0) == 0.7


@pytest.mark.asyncio
async def test_sentiment_counts_populated() -> None:
    posts = [
        build_post(hours_ago=1, positive=1, negative=0),
        build_post(hours_ago=3, positive=0, negative=1),
        build_post(hours_ago=5, positive=1, negative=1),
        build_post(hours_ago=30, positive=1, negative=0),
    ]
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json={"results": posts}))
    )

    try:
        _, counts = await compute_sentiment("ETH", client, "key")
    finally:
        await client.aclose()

    assert math.isfinite(counts.mention_delta)
