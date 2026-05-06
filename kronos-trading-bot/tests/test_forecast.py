from datetime import UTC, datetime

from kronos_trading_bot.forecast import ForecastResult, run_forecast


class FakeForecaster:
    model_name = "Kronos-small"
    tokenizer_name = "Kronos-Tokenizer-base"

    def __init__(self):
        self.calls = []

    def predict(self, candles, pred_len):
        self.calls.append((candles, pred_len))
        return [{"timestamp": datetime(2026, 1, 1, 1, tzinfo=UTC), "close": 101.0}]


def test_run_forecast_returns_predictions_and_metadata():
    # Arrange
    candles = [{"timestamp": datetime(2026, 1, 1, tzinfo=UTC), "close": 100.0}]
    forecaster = FakeForecaster()

    # Act
    result = run_forecast(forecaster, candles, pred_len=1)

    # Assert
    assert isinstance(result, ForecastResult)
    assert result.model_name == "Kronos-small"
    assert result.tokenizer_name == "Kronos-Tokenizer-base"
    assert result.pred_len == 1
    assert result.predictions[0]["close"] == 101.0
    assert forecaster.calls == [(candles, 1)]
