from datetime import UTC, datetime

import pytest
import requests

from kronos_trading_bot.data_ingestion import (
    BinancePublicClient,
    parse_binance_kline,
    write_candles_csv,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class RecordingSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, "kwargs": kwargs})
        return FakeResponse(self.payload)


class FlakySession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise requests.Timeout("temporary timeout")
        return FakeResponse(self.payload)


class FailingSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        raise requests.ConnectionError("network unavailable")


def _public_kline_payload():
    return [[1767225600000, "100.0", "110.0", "90.0", "105.0", "12.5"]]


def test_parse_binance_kline_maps_public_fields():
    # Arrange
    row = [1767225600000, "100.0", "110.0", "90.0", "105.0", "12.5"]

    # Act
    candle = parse_binance_kline(row)

    # Assert
    assert candle["timestamp"] == datetime(2026, 1, 1, tzinfo=UTC)
    assert candle["open"] == 100.0
    assert candle["high"] == 110.0
    assert candle["low"] == 90.0
    assert candle["close"] == 105.0
    assert candle["volume"] == 12.5


def test_write_candles_csv_creates_reproducible_file(tmp_path):
    # Arrange
    candles = [
        {
            "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 10.0,
        }
    ]
    path = tmp_path / "BTCUSDT_1h.csv"

    # Act
    write_candles_csv(path, candles)

    # Assert
    assert path.read_text(encoding="utf-8").splitlines() == [
        "timestamp,open,high,low,close,volume",
        "2026-01-01T00:00:00+00:00,1.0,2.0,0.5,1.5,10.0",
    ]


def test_fetch_klines_uses_public_endpoint_without_credentials():
    # Arrange
    session = RecordingSession(_public_kline_payload())
    client = BinancePublicClient(session=session, timeout=7.5, retries=0)

    # Act
    candles = client.fetch_klines("BTCUSDT", interval="1h", limit=1)

    # Assert
    assert candles == [
        {
            "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 105.0,
            "volume": 12.5,
        }
    ]
    assert session.calls == [
        {
            "url": "https://api.binance.com/api/v3/klines",
            "kwargs": {
                "params": {"symbol": "BTCUSDT", "interval": "1h", "limit": 1},
                "timeout": 7.5,
            },
        }
    ]
    assert "headers" not in session.calls[0]["kwargs"]
    assert "apiKey" not in session.calls[0]["kwargs"]["params"]


def test_fetch_klines_retries_transient_request_errors():
    # Arrange
    session = FlakySession(_public_kline_payload())
    sleeps = []
    client = BinancePublicClient(
        session=session,
        timeout=1.0,
        retries=1,
        backoff_seconds=0.25,
        sleep=sleeps.append,
    )

    # Act
    candles = client.fetch_klines("BTCUSDT", interval="1h", limit=1)

    # Assert
    assert len(candles) == 1
    assert session.calls == 2
    assert sleeps == [0.25]


def test_fetch_klines_raises_after_retries_are_exhausted():
    # Arrange
    session = FailingSession()
    client = BinancePublicClient(
        session=session,
        timeout=1.0,
        retries=1,
        backoff_seconds=0.0,
        sleep=lambda seconds: None,
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="Failed to fetch Binance public klines"):
        client.fetch_klines("BTCUSDT", interval="1h", limit=1)
    assert session.calls == 2
