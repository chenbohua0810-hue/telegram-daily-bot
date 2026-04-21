from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import math

import httpx

from models.signals import SentimentCounts, SentimentSignal


logger = logging.getLogger(__name__)


def combine_scores(news_score: float, mention_score: float) -> float:
    return round(0.7 * news_score + 0.3 * mention_score, 4)


def sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value))


async def compute_sentiment(
    token_symbol: str,
    client: httpx.AsyncClient,
    api_key: str,
    hours_back: int = 24,
) -> tuple[SentimentSignal, SentimentCounts]:
    try:
        response = await client.get(
            "https://cryptopanic.com/api/v1/posts/",
            params={
                "auth_token": api_key,
                "currencies": token_symbol,
                "filter": "rising",
            },
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("Falling back to neutral sentiment after CryptoPanic error")
        return _neutral_response()

    posts = response.json().get("results", [])
    if not posts:
        return _neutral_response()

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(hours=hours_back)
    previous_cutoff = now - timedelta(hours=hours_back * 2)
    recent_posts = [
        post for post in posts if _parse_time(post["published_at"]) >= recent_cutoff
    ]
    previous_posts = [
        post
        for post in posts
        if previous_cutoff <= _parse_time(post["published_at"]) < recent_cutoff
    ]

    positive, negative, neutral = _count_sentiment(recent_posts)
    source_count = positive + negative + neutral

    if source_count == 0:
        return _neutral_response()

    previous_count = len(previous_posts)
    mention_delta = (source_count - previous_count) / max(1, previous_count)
    news_score = ((positive - negative) / max(1, source_count) + 1) / 2
    mention_score = sigmoid(mention_delta)
    score = combine_scores(news_score, mention_score)

    if score > 0.6:
        signal_value = "bullish"
    elif score < 0.4:
        signal_value = "bearish"
    else:
        signal_value = "neutral"

    return (
        SentimentSignal(
            signal=signal_value,
            score=score,
            source_count=source_count,
        ),
        SentimentCounts(
            positive=positive,
            negative=negative,
            neutral=neutral,
            mention_delta=mention_delta,
        ),
    )


def _count_sentiment(posts: list[dict]) -> tuple[int, int, int]:
    positive = 0
    negative = 0
    neutral = 0

    for post in posts:
        votes = post.get("votes", {})
        if votes.get("positive", 0) > votes.get("negative", 0):
            positive += 1
        elif votes.get("positive", 0) < votes.get("negative", 0):
            negative += 1
        else:
            neutral += 1

    return positive, negative, neutral


def _neutral_response() -> tuple[SentimentSignal, SentimentCounts]:
    return (
        SentimentSignal(signal="neutral", score=0.5, source_count=0),
        SentimentCounts(positive=0, negative=0, neutral=0, mention_delta=0.0),
    )


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)
