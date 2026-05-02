from __future__ import annotations

import math

import pandas as pd

from models import TechnicalIndicators
from signals.filters import compute_technicals, ohlcv_to_volatility


def build_ohlcv(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-04-01", periods=len(closes), freq="h", tz="UTC")
    rows = []
    for close in closes:
        rows.append(
            {
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows, index=index)


def test_insufficient_data_returns_neutral() -> None:
    signal, indicators = compute_technicals(build_ohlcv([100 + index for index in range(10)]))

    assert signal.trend == "neutral"
    assert signal.momentum == "neutral"
    assert signal.stat_arb == "neutral"
    assert signal.confidence == 0.0
    assert math.isnan(indicators.ema8)
    assert math.isnan(indicators.atr_pct)


def test_bullish_uptrend_signal() -> None:
    closes = [100 + index * 1.5 for index in range(200)]
    signal, indicators = compute_technicals(build_ohlcv(closes))

    assert signal.trend == "bullish"
    assert indicators.ema8 > indicators.ema21


def test_bearish_downtrend_signal() -> None:
    closes = [400 - index * 1.5 for index in range(200)]
    signal, _ = compute_technicals(build_ohlcv(closes))

    assert signal.trend == "bearish"


def test_high_volatility_flag() -> None:
    closes = [100 + ((-1) ** index) * 8 for index in range(200)]
    signal, indicators = compute_technicals(build_ohlcv(closes))

    assert signal.volatility == "high"
    assert indicators.atr_pct > 0.03


def test_mean_revert_signal() -> None:
    closes = [100.0] * 199 + [70.0]
    signal, indicators = compute_technicals(build_ohlcv(closes))

    assert signal.stat_arb == "mean_revert"
    assert indicators.bb_zscore < -2


def test_indicators_raw_values_populated() -> None:
    closes = [100 + index * 0.8 for index in range(200)]
    _, indicators = compute_technicals(build_ohlcv(closes))

    assert math.isfinite(indicators.ema8)
    assert math.isfinite(indicators.rsi)
    assert math.isfinite(indicators.macd_hist)
    assert math.isfinite(indicators.atr)
    assert math.isfinite(indicators.atr_pct)
    assert math.isfinite(indicators.bb_zscore)
    assert math.isfinite(indicators.close_price)


def test_ohlcv_to_volatility_nan_fallback() -> None:
    indicators = TechnicalIndicators(
        ema8=math.nan,
        ema21=math.nan,
        rsi=math.nan,
        macd_hist=math.nan,
        atr=math.nan,
        atr_pct=math.nan,
        bb_zscore=math.nan,
        close_price=math.nan,
    )

    assert ohlcv_to_volatility(indicators) == 0.05
