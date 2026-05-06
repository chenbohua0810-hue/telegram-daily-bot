from datetime import UTC, datetime

from kronos_trading_bot.domain import SignalAction
from kronos_trading_bot.signals import build_signal


def test_emits_buy_when_predicted_return_exceeds_entry_threshold():
    # Arrange / Act
    signal = build_signal(
        "BTC/USDT",
        latest_close=100.0,
        predicted_close=103.0,
        entry_threshold=0.02,
        exit_threshold=-0.01,
        model_name="Kronos-small",
    )

    # Assert
    assert signal.action == SignalAction.BUY
    assert signal.reason_code == "predicted_return_above_entry_threshold"
    assert signal.predicted_return == 0.03


def test_emits_hold_for_weak_predicted_return():
    # Arrange / Act
    signal = build_signal(
        "ETH/USDT",
        latest_close=100.0,
        predicted_close=100.5,
        entry_threshold=0.02,
        exit_threshold=-0.01,
        model_name="Kronos-small",
    )

    # Assert
    assert signal.action == SignalAction.HOLD
    assert signal.reason_code == "predicted_return_weak"


def test_emits_sell_to_close_when_predicted_return_crosses_exit_threshold():
    # Arrange / Act
    signal = build_signal(
        "BTC/USDT",
        latest_close=100.0,
        predicted_close=98.0,
        entry_threshold=0.02,
        exit_threshold=-0.01,
        model_name="Kronos-small",
    )

    # Assert
    assert signal.action == SignalAction.SELL_TO_CLOSE
    assert signal.reason_code == "predicted_return_below_exit_threshold"
    assert signal.predicted_return == -0.02


def test_signal_preserves_forecast_metadata():
    # Arrange
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)

    # Act
    signal = build_signal(
        "ETH/USDT",
        latest_close=100.0,
        predicted_close=103.0,
        entry_threshold=0.02,
        exit_threshold=-0.01,
        model_name="Kronos-small",
        confidence_score=0.75,
        timestamp=timestamp,
    )

    # Assert
    assert signal.symbol == "ETH/USDT"
    assert signal.timestamp == timestamp
    assert signal.confidence_score == 0.75
    assert signal.model_used == "Kronos-small"
