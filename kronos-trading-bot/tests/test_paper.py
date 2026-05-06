import pytest

from kronos_trading_bot.paper import (
    PaperPortfolio,
    simulate_buy,
    simulate_sell_to_close,
    unrealized_pnl_usdt,
)


def test_simulated_buy_updates_cash_position_fee_and_slippage():
    # Arrange
    portfolio = PaperPortfolio.initial(cash_usdt=10000)

    # Act
    updated, fill = simulate_buy(
        portfolio,
        symbol="BTC/USDT",
        notional_usdt=1000,
        market_price=100,
        fee_rate=0.001,
        slippage_bps=10,
    )

    # Assert
    assert fill.symbol == "BTC/USDT"
    assert fill.side == "BUY"
    assert fill.fill_price == 100.1
    assert fill.notional_usdt == 1000
    assert fill.fee_usdt == 1.0
    assert updated.cash_usdt == 8999.0
    assert updated.fees_paid_usdt == 1.0
    assert updated.realized_pnl_usdt == 0.0
    assert updated.positions["BTC/USDT"].quantity == 1000 / 100.1
    assert updated.positions["BTC/USDT"].average_entry_price == 100.1
    assert updated.fills == (fill,)


def test_simulated_buy_does_not_mutate_input_and_averages_entry_price():
    # Arrange
    initial = PaperPortfolio.initial(cash_usdt=10000)
    first, first_fill = simulate_buy(
        initial,
        symbol="BTC/USDT",
        notional_usdt=1000,
        market_price=100,
        fee_rate=0.001,
        slippage_bps=0,
    )

    # Act
    second, second_fill = simulate_buy(
        first,
        symbol="BTC/USDT",
        notional_usdt=1100,
        market_price=110,
        fee_rate=0.001,
        slippage_bps=0,
    )

    # Assert
    assert initial.cash_usdt == 10000
    assert initial.positions == {}
    assert first.cash_usdt == 8999.0
    assert first.positions["BTC/USDT"].quantity == 10
    assert first.fills == (first_fill,)
    assert second.fills == (first_fill, second_fill)
    assert second.positions["BTC/USDT"].quantity == 20
    assert second.positions["BTC/USDT"].average_entry_price == 105.0


def test_unrealized_pnl_uses_current_market_price():
    # Arrange
    portfolio, _fill = simulate_buy(
        PaperPortfolio.initial(cash_usdt=10000),
        symbol="BTC/USDT",
        notional_usdt=1000,
        market_price=100,
        fee_rate=0.001,
        slippage_bps=0,
    )

    # Act
    pnl = unrealized_pnl_usdt(portfolio, symbol="BTC/USDT", current_price=105)

    # Assert
    assert pnl == 50.0


def test_sell_to_close_realizes_pnl_removes_position_and_appends_fill():
    # Arrange
    portfolio, buy_fill = simulate_buy(
        PaperPortfolio.initial(cash_usdt=10000),
        symbol="BTC/USDT",
        notional_usdt=1000,
        market_price=100,
        fee_rate=0.001,
        slippage_bps=0,
    )

    # Act
    updated, sell_fill = simulate_sell_to_close(
        portfolio,
        symbol="BTC/USDT",
        market_price=110,
        fee_rate=0.001,
        slippage_bps=10,
    )

    # Assert
    assert sell_fill.side == "SELL"
    assert sell_fill.fill_price == pytest.approx(109.89)
    assert sell_fill.quantity == 10
    assert sell_fill.notional_usdt == pytest.approx(1098.9)
    assert sell_fill.fee_usdt == pytest.approx(1.0989)
    assert sell_fill.realized_pnl_usdt == pytest.approx(97.8011)
    assert updated.cash_usdt == pytest.approx(10096.8011)
    assert updated.realized_pnl_usdt == pytest.approx(97.8011)
    assert updated.fees_paid_usdt == pytest.approx(2.0989)
    assert "BTC/USDT" not in updated.positions
    assert updated.fills == (buy_fill, sell_fill)
