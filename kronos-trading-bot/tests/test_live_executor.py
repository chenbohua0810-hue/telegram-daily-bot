import inspect

import kronos_trading_bot.live_executor as live_executor
from kronos_trading_bot.live_executor import LiveExecutorDisabled


def test_live_executor_rejects_every_order_attempt():
    # Arrange
    executor = LiveExecutorDisabled()

    # Act
    result = executor.submit_order({"symbol": "BTC/USDT", "side": "BUY"})

    # Assert
    assert result.accepted is False
    assert result.reason_code == "live_trading_not_implemented"
    assert result.order_id is None


def test_live_executor_rejects_secret_bearing_order_without_echoing_secrets():
    # Arrange
    executor = LiveExecutorDisabled()
    order = {
        "symbol": "ETH/USDT",
        "side": "BUY",
        "api_key": "[REDACTED]",
        "token": "[REDACTED]",
        "private_key": "[REDACTED]",
    }

    # Act
    result = executor.submit_order(order)

    # Assert
    assert result.accepted is False
    assert result.reason_code == "live_trading_not_implemented"
    assert result.rejected_order is None


def test_live_executor_has_no_exchange_sdk_or_private_endpoint_surface():
    # Arrange
    source = inspect.getsource(live_executor).lower()

    # Act
    forbidden_fragments = [
        "binance.client",
        "ccxt",
        "create_order",
        "private",
        "/api/v3/order",
        "api_key",
        "secret",
        "token",
        "password",
    ]

    # Assert
    assert all(fragment not in source for fragment in forbidden_fragments)


def test_live_executor_always_rejects_multiple_order_shapes():
    # Arrange
    executor = LiveExecutorDisabled()
    orders = [
        {},
        {"symbol": "BTC/USDT", "side": "SELL"},
        {"symbol": "ETH/USDT", "side": "BUY", "quantity": 1.0},
    ]

    # Act
    results = [executor.submit_order(order) for order in orders]

    # Assert
    assert all(result.accepted is False for result in results)
    assert {result.reason_code for result in results} == {"live_trading_not_implemented"}
