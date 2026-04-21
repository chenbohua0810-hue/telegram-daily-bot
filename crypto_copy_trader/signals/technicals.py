from __future__ import annotations

import math

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange, BollingerBands

from models.signals import TechnicalIndicators, TechnicalSignal


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
