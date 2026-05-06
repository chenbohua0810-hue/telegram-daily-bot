from __future__ import annotations

import csv
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

CANDLE_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")
BINANCE_PUBLIC_BASE_URL = "https://api.binance.com"
BINANCE_KLINES_PATH = "/api/v3/klines"


def parse_binance_kline(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "timestamp": datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
    }


def write_candles_csv(path: Path, candles: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDLE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "timestamp": candle["timestamp"].isoformat(),
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                    "volume": candle["volume"],
                }
            )


class BinancePublicClient:
    def __init__(
        self,
        *,
        base_url: str = BINANCE_PUBLIC_BASE_URL,
        timeout: float = 10.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retries = retries
        self._backoff_seconds = backoff_seconds
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep

    def fetch_klines(
        self,
        symbol: str,
        *,
        interval: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        url = f"{self._base_url}{BINANCE_KLINES_PATH}"
        params = {"symbol": symbol, "interval": interval, "limit": limit}

        for attempt in range(self._retries + 1):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("Expected Binance kline response to be a list")
                return [parse_binance_kline(row) for row in payload]
            except requests.RequestException as exc:
                if attempt >= self._retries:
                    raise RuntimeError("Failed to fetch Binance public klines") from exc
                delay = self._backoff_seconds * (2**attempt)
                if delay > 0:
                    self._sleep(delay)

        raise RuntimeError("Failed to fetch Binance public klines")
