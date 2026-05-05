from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from kronos_trading_bot.domain import DataQualityReport

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


def validate_candles(
    candles: Iterable[dict[str, Any]],
    *,
    now: datetime,
    max_delay: timedelta,
    symbol: str | None = None,
) -> DataQualityReport:
    rows = list(candles)
    errors: list[str] = []
    if not rows:
        return DataQualityReport(symbol, False, ["empty_candles"], 0, None)

    if any(not REQUIRED_COLUMNS.issubset(row.keys()) for row in rows):
        errors.append("missing_required_columns")

    timestamps = [row.get("timestamp") for row in rows if "timestamp" in row]
    if timestamps != sorted(timestamps):
        errors.append("timestamps_not_sorted")
    if len(set(timestamps)) != len(timestamps):
        errors.append("duplicated_timestamps")
    for previous, current in zip(timestamps, timestamps[1:], strict=False):
        if current - previous != timedelta(hours=1):
            errors.append("non_1h_interval")
            break

    for row in rows:
        if not REQUIRED_COLUMNS.issubset(row.keys()):
            continue
        open_, high, low, close, volume = (
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row["volume"],
        )
        if min(open_, high, low, close, volume) < 0:
            errors.append("negative_ohlcv")
        if high < max(open_, close, low):
            errors.append("invalid_high")
        if low > min(open_, close, high):
            errors.append("invalid_low")

    latest = timestamps[-1] if timestamps else None
    if latest is not None and now - latest > max_delay:
        errors.append("stale_data")

    return DataQualityReport(symbol, not errors, sorted(set(errors)), len(rows), latest)
