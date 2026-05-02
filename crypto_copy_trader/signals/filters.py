from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
import logging

import httpx
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange, BollingerBands

from models import OnChainEvent, SentimentCounts, SentimentSignal, TechnicalIndicators, TechnicalSignal, WalletScore
from signals.symbol_mapper import map_to_binance


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# quant_filter
# ---------------------------------------------------------------------------


def quant_filter(
    event: OnChainEvent,
    wallet: WalletScore,
    binance_symbols: set[str],
    min_trade_usd: float,
    dedup_window_seconds: int = 600,
    recent_events: list[OnChainEvent] | None = None,
) -> tuple[bool, str]:
    if float(event.amount_usd) < min_trade_usd:
        return False, "below_min_trade_usd"

    binance_symbol = map_to_binance(event.chain, event.token_address, event.token_symbol)
    if binance_symbol not in binance_symbols:
        return False, "not_on_binance"

    if wallet.status != "active":
        return False, "wallet_inactive"

    if recent_events is None:
        return True, "ok"

    for recent_event in recent_events:
        same_wallet = recent_event.wallet == event.wallet
        same_token = recent_event.token_symbol == event.token_symbol
        within_window = abs((event.block_time - recent_event.block_time).total_seconds()) <= dedup_window_seconds

        if same_wallet and same_token and within_window:
            return False, "duplicate_recent"

    return True, "ok"


# ---------------------------------------------------------------------------
# technicals
# ---------------------------------------------------------------------------


def compute_technicals(
    ohlcv: pd.DataFrame,
) -> tuple[TechnicalSignal, TechnicalIndicators]:
    if len(ohlcv) < 20:
        nan = float("nan")
        return (
            TechnicalSignal(
                trend="neutral",
                momentum="neutral",
                volatility="medium",
                stat_arb="neutral",
                confidence=0.0,
            ),
            TechnicalIndicators(
                ema8=nan,
                ema21=nan,
                rsi=nan,
                macd_hist=nan,
                atr=nan,
                atr_pct=nan,
                bb_zscore=nan,
                close_price=nan,
            ),
        )

    close = ohlcv["close"]
    ema8 = close.ewm(span=8, adjust=False).mean().iloc[-1]
    ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
    rsi = RSIIndicator(close, window=14).rsi().iloc[-1]
    macd_hist = MACD(close, window_slow=26, window_fast=12, window_sign=9).macd_diff().iloc[-1]
    atr = AverageTrueRange(ohlcv["high"], ohlcv["low"], close, window=14).average_true_range().iloc[-1]
    close_price = close.iloc[-1]
    atr_pct = atr / close_price if close_price else 0.0
    bands = BollingerBands(close, window=20, window_dev=2)
    middle = bands.bollinger_mavg().iloc[-1]
    std = close.rolling(window=20).std().iloc[-1]
    bb_zscore = 0.0 if not std or math.isnan(std) else (close_price - middle) / std

    trend = _classify_trend(ema8, ema21)
    momentum = _classify_momentum(rsi, macd_hist)
    volatility = _classify_volatility(atr_pct)
    stat_arb = _classify_stat_arb(bb_zscore)
    confidence = _compute_confidence(trend, momentum, volatility)

    return (
        TechnicalSignal(
            trend=trend,
            momentum=momentum,
            volatility=volatility,
            stat_arb=stat_arb,
            confidence=confidence,
        ),
        TechnicalIndicators(
            ema8=float(ema8),
            ema21=float(ema21),
            rsi=float(rsi),
            macd_hist=float(macd_hist),
            atr=float(atr),
            atr_pct=float(atr_pct),
            bb_zscore=float(bb_zscore),
            close_price=float(close_price),
        ),
    )


def ohlcv_to_volatility(indicators: TechnicalIndicators) -> float:
    if math.isnan(indicators.atr_pct):
        return 0.05
    return indicators.atr_pct


def _classify_trend(ema8: float, ema21: float) -> str:
    if ema8 > ema21 * 1.002:
        return "bullish"
    if ema8 < ema21 * 0.998:
        return "bearish"
    return "neutral"


def _classify_momentum(rsi: float, macd_hist: float) -> str:
    if rsi > 60 and macd_hist > 0:
        return "bullish"
    if rsi < 40 and macd_hist < 0:
        return "bearish"
    return "neutral"


def _classify_volatility(atr_pct: float) -> str:
    if atr_pct < 0.01:
        return "low"
    if atr_pct <= 0.03:
        return "medium"
    return "high"


def _classify_stat_arb(bb_zscore: float) -> str:
    if bb_zscore > 2:
        return "breakout"
    if bb_zscore < -2:
        return "mean_revert"
    return "neutral"


def _compute_confidence(trend: str, momentum: str, volatility: str) -> float:
    signal_weight = {"bullish": 1.0, "bearish": 1.0, "neutral": 0.3}
    volatility_weight = {"low": 1.0, "medium": 1.0, "high": 0.5}
    return round(
        (signal_weight[trend] + signal_weight[momentum] + volatility_weight[volatility]) / 3,
        2,
    )


# ---------------------------------------------------------------------------
# sentiment
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# slippage_fee
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostEstimate:
    slippage_pct: float
    fee_pct: float
    total_cost_pct: float
    expected_profit_pct: float


def estimate_cost(
    *,
    order_usdt: float,
    symbol: str,
    orderbook_fetcher: Callable[[str], dict],
    use_bnb_discount: bool = True,
    technical_confidence: float,
) -> CostEstimate:
    orderbook = orderbook_fetcher(symbol)
    asks = orderbook.get("asks", [])
    slippage_pct = _estimate_slippage(order_usdt, asks)

    if order_usdt >= 100000:
        slippage_pct += 0.001

    fee_pct = 0.0015 if use_bnb_discount else 0.002
    expected_profit_pct = 0.05 * technical_confidence

    return CostEstimate(
        slippage_pct=round(slippage_pct, 4),
        fee_pct=fee_pct,
        total_cost_pct=round(slippage_pct + fee_pct, 4),
        expected_profit_pct=round(expected_profit_pct, 4),
    )


def should_reject(estimate: CostEstimate, max_cost_ratio: float = 0.30) -> bool:
    return estimate.total_cost_pct > estimate.expected_profit_pct * max_cost_ratio


def _estimate_slippage(order_usdt: float, asks: list[list[float]]) -> float:
    if order_usdt < 7500:
        return 0.001

    if not asks:
        return 0.0

    remaining = order_usdt
    touched_prices: list[float] = []

    for ask_price, ask_quantity in asks:
        level_notional = ask_price * ask_quantity
        touched_prices.append(float(ask_price))
        remaining -= level_notional
        if remaining <= 0:
            break

    best_ask = float(asks[0][0])
    average_price = sum(touched_prices) / len(touched_prices)
    return max(0.0, (average_price - best_ask) / best_ask)
