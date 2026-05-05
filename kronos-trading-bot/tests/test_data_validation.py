from datetime import UTC, datetime, timedelta

from kronos_trading_bot.data_validation import validate_candles


def _valid_candles():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {
            "timestamp": start,
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 105.0,
            "volume": 10.0,
        },
        {
            "timestamp": start + timedelta(hours=1),
            "open": 105.0,
            "high": 115.0,
            "low": 100.0,
            "close": 112.0,
            "volume": 12.0,
        },
    ]


def test_accepts_valid_1h_ohlcv_data():
    # Arrange
    candles = _valid_candles()
    now = candles[-1]["timestamp"] + timedelta(minutes=30)

    # Act
    report = validate_candles(candles, now=now, max_delay=timedelta(hours=2))

    # Assert
    assert report.passed is True
    assert report.errors == []


def test_rejects_missing_required_columns():
    # Arrange
    candles = _valid_candles()
    del candles[0]["volume"]

    # Act
    report = validate_candles(
        candles,
        now=candles[-1]["timestamp"],
        max_delay=timedelta(hours=2),
    )

    # Assert
    assert report.passed is False
    assert "missing_required_columns" in report.errors


def test_rejects_duplicated_timestamps():
    # Arrange
    candles = _valid_candles()
    candles[1]["timestamp"] = candles[0]["timestamp"]

    # Act
    report = validate_candles(
        candles,
        now=candles[-1]["timestamp"] + timedelta(minutes=30),
        max_delay=timedelta(hours=2),
    )

    # Assert
    assert report.passed is False
    assert "duplicated_timestamps" in report.errors


def test_rejects_stale_data():
    # Arrange
    candles = _valid_candles()
    now = candles[-1]["timestamp"] + timedelta(hours=3)

    # Act
    report = validate_candles(candles, now=now, max_delay=timedelta(hours=2))

    # Assert
    assert report.passed is False
    assert "stale_data" in report.errors


def test_rejects_invalid_high_relationship():
    # Arrange
    candles = _valid_candles()
    candles[0]["high"] = 99.0

    # Act
    report = validate_candles(
        candles,
        now=candles[-1]["timestamp"] + timedelta(minutes=30),
        max_delay=timedelta(hours=2),
    )

    # Assert
    assert report.passed is False
    assert "invalid_high" in report.errors


def test_rejects_invalid_low_relationship():
    # Arrange
    candles = _valid_candles()
    candles[0]["low"] = 106.0

    # Act
    report = validate_candles(
        candles,
        now=candles[-1]["timestamp"] + timedelta(minutes=30),
        max_delay=timedelta(hours=2),
    )

    # Assert
    assert report.passed is False
    assert "invalid_low" in report.errors


def test_rejects_negative_ohlcv_values():
    # Arrange
    candles = _valid_candles()
    candles[0]["volume"] = -1.0

    # Act
    report = validate_candles(
        candles,
        now=candles[-1]["timestamp"] + timedelta(minutes=30),
        max_delay=timedelta(hours=2),
    )

    # Assert
    assert report.passed is False
    assert "negative_ohlcv" in report.errors


def test_rejects_non_1h_interval():
    # Arrange
    candles = _valid_candles()
    candles[1]["timestamp"] = candles[0]["timestamp"] + timedelta(hours=2)

    # Act
    report = validate_candles(
        candles,
        now=candles[-1]["timestamp"] + timedelta(minutes=30),
        max_delay=timedelta(hours=2),
    )

    # Assert
    assert report.passed is False
    assert "non_1h_interval" in report.errors
