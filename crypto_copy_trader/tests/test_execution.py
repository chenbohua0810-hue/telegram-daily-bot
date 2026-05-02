from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

import ccxt

from execution import BinanceExecutor, ExecutionResult, NetworkError
from models import Portfolio, Position
from models import TradeDecision, WalletScore
from execution import compute_position_size
from execution import check_risk


def build_portfolio(
    *,
    cash_usdt: str = "1000",
    total_value_usdt: str = "10000",
    positions: dict[str, Position] | None = None,
) -> Portfolio:
    return Portfolio(
        cash_usdt=Decimal(cash_usdt),
        positions={} if positions is None else positions,
        total_value_usdt=Decimal(total_value_usdt),
        daily_pnl_pct=0.0,
    )


def build_position(symbol: str) -> Position:
    return Position(
        symbol=symbol,
        quantity=Decimal("1"),
        avg_entry_price=Decimal("100"),
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        source_wallet="0xabc123",
    )


def build_wallet_score(
    *,
    trust_level: str = "high",
    recent_win_rate: float = 0.70,
    max_drawdown: float = 0.18,
) -> WalletScore:
    return WalletScore(
        address="0xabc123",
        chain="eth",
        win_rate=0.70,
        trade_count=60,
        max_drawdown=max_drawdown,
        funds_usd=100000.0,
        recent_win_rate=recent_win_rate,
        trust_level=trust_level,
        status="active",
    )


def test_normal_vol_full_base() -> None:
    size = compute_position_size(
        portfolio=build_portfolio(cash_usdt="5000", total_value_usdt="10000"),
        asset_volatility=0.02,
    )

    assert size == Decimal("1000")


def test_high_vol_reduces_position() -> None:
    size = compute_position_size(
        portfolio=build_portfolio(cash_usdt="5000", total_value_usdt="10000"),
        asset_volatility=0.08,
    )

    assert size == Decimal("250")


def test_low_vol_clamps_to_cash() -> None:
    size = compute_position_size(
        portfolio=build_portfolio(cash_usdt="500", total_value_usdt="10000"),
        asset_volatility=0.005,
    )

    assert size == Decimal("500")


def test_zero_vol_safe_default() -> None:
    size = compute_position_size(
        portfolio=build_portfolio(cash_usdt="5000", total_value_usdt="10000"),
        asset_volatility=0.0,
    )

    assert size == Decimal("4000")


def test_high_trust_wallet_gets_6pct_base() -> None:
    size = compute_position_size(
        portfolio=build_portfolio(cash_usdt="5000", total_value_usdt="10000"),
        asset_volatility=0.02,
        wallet=build_wallet_score(),
    )

    assert size == Decimal("600.0")


def test_low_trust_capped_at_1pct() -> None:
    size = compute_position_size(
        portfolio=build_portfolio(cash_usdt="5000", total_value_usdt="10000"),
        asset_volatility=0.02,
        wallet=build_wallet_score(trust_level="low"),
    )

    assert size == Decimal("100.0")


def test_volatility_adjustment_capped() -> None:
    size = compute_position_size(
        portfolio=build_portfolio(cash_usdt="5000", total_value_usdt="10000"),
        asset_volatility=0.001,
        wallet=build_wallet_score(),
    )

    assert size == Decimal("900.00")


def test_risk_ok_empty_portfolio() -> None:
    result = check_risk(
        new_symbol="ETH/USDT",
        new_size_usdt=Decimal("1000"),
        portfolio=build_portfolio(),
        correlation_provider=lambda new_symbol, existing_symbols: {},
        daily_pnl_pct=0.0,
    )

    assert result.passed is True
    assert result.size_multiplier == 1.0


def test_risk_max_concurrent_blocks() -> None:
    positions = {f"COIN{index}/USDT": build_position(f"COIN{index}/USDT") for index in range(10)}

    result = check_risk(
        new_symbol="ETH/USDT",
        new_size_usdt=Decimal("1000"),
        portfolio=build_portfolio(positions=positions),
        correlation_provider=lambda new_symbol, existing_symbols: {},
        daily_pnl_pct=0.0,
    )

    assert result.passed is False
    assert result.reasons == ["max_concurrent_reached"]


def test_risk_daily_circuit_blocks() -> None:
    result = check_risk(
        new_symbol="ETH/USDT",
        new_size_usdt=Decimal("1000"),
        portfolio=build_portfolio(),
        correlation_provider=lambda new_symbol, existing_symbols: {},
        daily_pnl_pct=-0.06,
    )

    assert result.passed is False
    assert result.reasons == ["daily_loss_circuit"]


def test_risk_high_correlation_halves() -> None:
    positions = {"BTC/USDT": build_position("BTC/USDT")}

    result = check_risk(
        new_symbol="ETH/USDT",
        new_size_usdt=Decimal("1000"),
        portfolio=build_portfolio(positions=positions),
        correlation_provider=lambda new_symbol, existing_symbols: {"BTC/USDT": 0.85},
        daily_pnl_pct=0.0,
    )

    assert result.passed is True
    assert result.size_multiplier == 0.5
    assert result.reasons == ["high_correlation:BTC/USDT:0.85"]


def test_risk_multiple_reasons_all_listed() -> None:
    positions = {f"COIN{index}/USDT": build_position(f"COIN{index}/USDT") for index in range(10)}

    result = check_risk(
        new_symbol="ETH/USDT",
        new_size_usdt=Decimal("1000"),
        portfolio=build_portfolio(positions=positions),
        correlation_provider=lambda new_symbol, existing_symbols: {},
        daily_pnl_pct=-0.06,
    )

    assert result.passed is False
    assert result.reasons == ["max_concurrent_reached", "daily_loss_circuit"]


def build_decision(*, action: str = "buy", quantity_usdt: float = 1000.0) -> TradeDecision:
    return TradeDecision(
        action=action,
        symbol="BTC/USDT",
        quantity_usdt=quantity_usdt,
        confidence=80,
        reasoning="Execution test decision.",
        source_wallet="0xabc123",
    )


def build_exchange() -> SimpleNamespace:
    return SimpleNamespace(
        load_markets=AsyncMock(return_value={"BTC/USDT": {}, "ETH/BTC": {}}),
        fetch_ticker=AsyncMock(return_value={"last": 50000}),
        fetch_ohlcv=AsyncMock(
            return_value=[[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]]
        ),
        fetch_order_book=AsyncMock(return_value={"bids": [[49999, 1]], "asks": [[50001, 1]]}),
        fetch_balance=AsyncMock(return_value={"free": {"USDT": 2000}}),
        create_market_buy_order=AsyncMock(
            return_value={"id": "buy-1", "average": 50000, "fee": {"cost": 0.75}}
        ),
        create_market_sell_order=AsyncMock(
            return_value={"id": "sell-1", "average": 50000, "fee": {"cost": 0.75}}
        ),
        create_order=AsyncMock(side_effect=AttributeError("create_order unavailable")),
        fetch_order=AsyncMock(return_value={"id": "limit-1", "filled": 0, "average": 50025, "fee": {"cost": 0}}),
        cancel_order=AsyncMock(return_value={"id": "limit-1"}),
    )


async def _build_executor(
    *,
    paper_trading: bool,
    exchange: SimpleNamespace | None = None,
    trades_repo: object | None = None,
) -> BinanceExecutor:
    executor = BinanceExecutor(
        api_key="key",
        api_secret="secret",
        paper_trading=paper_trading,
        exchange=exchange or build_exchange(),
        trades_repo=trades_repo or SimpleNamespace(record_trade=AsyncMock()),
    )
    await executor.load_markets()
    return executor


@pytest.mark.asyncio
async def test_paper_trading_simulates_fill() -> None:
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=True, trades_repo=trades_repo)

    result = await executor.execute(build_decision())

    assert result.success is True
    assert result.filled_quantity == Decimal("0.02")
    assert result.avg_price == Decimal("50000")
    assert result.pre_trade_mid_price == Decimal("50000")
    assert result.realized_slippage_pct == 0.0
    assert trades_repo.record_trade.await_args.kwargs["status"] == "paper"


@pytest.mark.asyncio
async def test_live_trading_calls_create_order() -> None:
    exchange = build_exchange()
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=False, exchange=exchange, trades_repo=trades_repo)

    await executor.execute(build_decision())

    exchange.create_market_buy_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_exit_uses_market_sell_for_position_fraction() -> None:
    exchange = build_exchange()
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=False, exchange=exchange, trades_repo=trades_repo)
    position = Position(
        symbol="BTC/USDT",
        quantity=Decimal("0.2"),
        avg_entry_price=Decimal("50000"),
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        source_wallet="0xabc123",
    )

    result = await executor.execute_exit(
        "BTC/USDT",
        Decimal("0.5"),
        position=position,
        source_wallet="0xabc123",
        reason="mirror_wallet_0xabc123",
    )

    assert result.success is True
    assert result.filled_quantity == Decimal("0.10000000")
    exchange.create_market_sell_order.assert_awaited_once_with("BTC/USDT", 0.1)
    assert trades_repo.record_trade.await_args.kwargs["action"] == "sell"
    assert trades_repo.record_trade.await_args.kwargs["reasoning"] == "mirror_wallet_0xabc123"


@pytest.mark.asyncio
async def test_live_trading_computes_realized_slippage() -> None:
    exchange = build_exchange()
    exchange.fetch_ticker = AsyncMock(return_value={"last": 100})
    exchange.fetch_order_book = AsyncMock(return_value={"bids": [[99.95, 10]], "asks": [[100.05, 10]]})
    exchange.create_market_buy_order = AsyncMock(
        return_value={"id": "buy-1", "average": 100.5, "fee": {"cost": 1}}
    )
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=False, exchange=exchange, trades_repo=trades_repo)

    result = await executor.execute(build_decision(quantity_usdt=1000.0))

    assert result.realized_slippage_pct == 0.005


@pytest.mark.asyncio
async def test_sell_slippage_sign_correct() -> None:
    exchange = build_exchange()
    exchange.fetch_ticker = AsyncMock(return_value={"last": 100})
    exchange.fetch_order_book = AsyncMock(return_value={"bids": [[99.95, 10]], "asks": [[100.05, 10]]})
    exchange.create_market_sell_order = AsyncMock(
        return_value={"id": "sell-1", "average": 99.5, "fee": {"cost": 1}}
    )
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=False, exchange=exchange, trades_repo=trades_repo)

    result = await executor.execute(build_decision(action="sell", quantity_usdt=1000.0))

    assert result.realized_slippage_pct == 0.005


@pytest.mark.asyncio
async def test_record_trade_receives_all_slippage_fields() -> None:
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=True, trades_repo=trades_repo)

    await executor.execute(
        build_decision(),
        estimated_slippage_pct=0.003,
        estimated_fee_pct=0.0015,
    )

    kwargs = trades_repo.record_trade.await_args.kwargs
    assert kwargs["pre_trade_mid_price"] is not None
    assert kwargs["estimated_slippage_pct"] is not None
    assert kwargs["realized_slippage_pct"] is not None
    assert kwargs["estimated_fee_pct"] is not None
    assert kwargs["realized_fee_pct"] is not None


@pytest.mark.asyncio
async def test_execute_retries_on_network_error() -> None:
    exchange = build_exchange()
    exchange.create_market_buy_order = AsyncMock(
        side_effect=[
            NetworkError("temporary"),
            {"id": "buy-1", "average": 50000, "fee": {"cost": 0.75}},
        ]
    )
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=False, exchange=exchange, trades_repo=trades_repo)

    result = await executor.execute(build_decision())

    assert result.success is True
    assert exchange.create_market_buy_order.await_count == 2


@pytest.mark.asyncio
async def test_execute_final_fail_records_status_failed() -> None:
    exchange = build_exchange()
    exchange.create_market_buy_order = AsyncMock(side_effect=[NetworkError("a"), NetworkError("b")])
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=False, exchange=exchange, trades_repo=trades_repo)

    result = await executor.execute(build_decision())

    assert result.success is False
    assert trades_repo.record_trade.await_args.kwargs["status"] == "failed"
    assert trades_repo.record_trade.await_args.kwargs["pre_trade_mid_price"] is None
    assert trades_repo.record_trade.await_args.kwargs["realized_slippage_pct"] is None


@pytest.mark.asyncio
async def test_execute_retries_on_ccxt_network_error() -> None:
    exchange = build_exchange()
    exchange.create_market_buy_order = AsyncMock(
        side_effect=[
            ccxt.NetworkError("ccxt network blip"),
            {"id": "buy-2", "average": 50000, "fee": {"cost": 0.75}},
        ]
    )
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=False, exchange=exchange, trades_repo=trades_repo)

    result = await executor.execute(build_decision())

    assert result.success is True
    assert exchange.create_market_buy_order.await_count == 2


@pytest.mark.asyncio
async def test_execute_retries_on_ccxt_request_timeout() -> None:
    exchange = build_exchange()
    exchange.create_market_buy_order = AsyncMock(
        side_effect=[
            ccxt.RequestTimeout("timeout"),
            {"id": "buy-3", "average": 50000, "fee": {"cost": 0.75}},
        ]
    )
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=False, exchange=exchange, trades_repo=trades_repo)

    result = await executor.execute(build_decision())

    assert result.success is True
    assert exchange.create_market_buy_order.await_count == 2


@pytest.mark.asyncio
async def test_load_markets_filters_usdt_pairs() -> None:
    executor = await _build_executor(paper_trading=True)

    symbols = await executor.load_markets()

    assert symbols == {"BTC/USDT"}


@pytest.mark.asyncio
async def test_quantizes_btc_quantity_using_lot_size() -> None:
    exchange = build_exchange()
    exchange.load_markets = AsyncMock(
        return_value={
            "BTC/USDT": {
                "info": {
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
                    ]
                }
            }
        }
    )
    exchange.fetch_ticker = AsyncMock(return_value={"last": 50000})
    trades_repo = SimpleNamespace(record_trade=AsyncMock(return_value=1), get_positions=AsyncMock(return_value=[]))
    executor = await _build_executor(paper_trading=False, exchange=exchange, trades_repo=trades_repo)
    await executor.load_markets()

    result = await executor.execute(build_decision(quantity_usdt=1000.43))

    assert result.success is True
    exchange.create_market_buy_order.assert_awaited_once_with("BTC/USDT", 0.02000)


@pytest.mark.asyncio
async def test_quantizes_shib_tiny_unit_without_dropping_notional() -> None:
    exchange = build_exchange()
    exchange.load_markets = AsyncMock(
        return_value={
            "SHIB/USDT": {
                "info": {
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": "1"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.00000001"},
                        {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                    ]
                }
            }
        }
    )
    exchange.fetch_ticker = AsyncMock(return_value={"last": "0.00001234"})
    exchange.fetch_order_book = AsyncMock(return_value={"bids": [["0.00001233", 1]], "asks": [["0.00001235", 1]]})
    exchange.create_market_buy_order = AsyncMock(return_value={"id": "buy-shib", "average": "0.00001234", "fee": {"cost": 0.01}})
    decision = TradeDecision(
        action="buy",
        symbol="SHIB/USDT",
        quantity_usdt=25.0,
        confidence=80,
        reasoning="Execution test decision.",
        source_wallet="0xabc123",
    )
    executor = await _build_executor(paper_trading=False, exchange=exchange)
    await executor.load_markets()

    result = await executor.execute(decision)

    assert result.success is True
    exchange.create_market_buy_order.assert_awaited_once_with("SHIB/USDT", 2025931.0)


@pytest.mark.asyncio
async def test_quantize_rejects_pepe_below_min_notional() -> None:
    exchange = build_exchange()
    exchange.load_markets = AsyncMock(
        return_value={
            "PEPE/USDT": {
                "info": {
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": "1"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.00000001"},
                        {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
                    ]
                }
            }
        }
    )
    exchange.fetch_ticker = AsyncMock(return_value={"last": "0.000001"})
    exchange.fetch_order_book = AsyncMock(return_value={"bids": [["0.00000099", 1]], "asks": [["0.00000101", 1]]})
    decision = TradeDecision(
        action="buy",
        symbol="PEPE/USDT",
        quantity_usdt=5.0,
        confidence=80,
        reasoning="Execution test decision.",
        source_wallet="0xabc123",
    )
    executor = await _build_executor(paper_trading=False, exchange=exchange)
    await executor.load_markets()

    result = await executor.execute(decision)

    assert result.success is False
    assert result.error == "min_notional_not_met"
    exchange.create_market_buy_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_maker_first_then_market_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("execution.asyncio.sleep", AsyncMock())
    exchange = build_exchange()
    exchange.create_order = AsyncMock(return_value={"id": "limit-1", "filled": 0, "average": 50025, "fee": {"cost": 0}})
    exchange.fetch_order = AsyncMock(return_value={"id": "limit-1", "filled": "0", "average": 50025, "fee": {"cost": 0}})
    executor = await _build_executor(paper_trading=False, exchange=exchange)

    result = await executor.execute(build_decision())

    assert result.success is True
    exchange.create_order.assert_awaited_once()
    assert exchange.create_order.await_args.args[:4] == ("BTC/USDT", "limit", "buy", 0.02)
    assert exchange.create_order.await_args.args[5] == {"postOnly": True}
    exchange.cancel_order.assert_awaited_once_with("limit-1", "BTC/USDT")
    exchange.create_market_buy_order.assert_awaited_once_with("BTC/USDT", 0.02)


@pytest.mark.asyncio
async def test_post_only_rejection_falls_back_to_market(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("execution.asyncio.sleep", AsyncMock())
    exchange = build_exchange()
    exchange.create_order = AsyncMock(side_effect=ccxt.InvalidOrder("post only rejected"))
    executor = await _build_executor(paper_trading=False, exchange=exchange)

    result = await executor.execute(build_decision())

    assert result.success is True
    exchange.create_market_buy_order.assert_awaited_once_with("BTC/USDT", 0.02)


@pytest.mark.asyncio
async def test_wide_spread_skips_entry() -> None:
    exchange = build_exchange()
    exchange.fetch_order_book = AsyncMock(return_value={"bids": [[90, 1]], "asks": [[110, 1]]})
    executor = await _build_executor(paper_trading=False, exchange=exchange)

    result = await executor.execute(build_decision())

    assert result.success is False
    assert result.error == "wide_spread"
    exchange.create_order.assert_not_awaited()
    exchange.create_market_buy_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_exit_always_uses_market(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("execution.asyncio.sleep", AsyncMock())
    exchange = build_exchange()
    executor = await _build_executor(paper_trading=False, exchange=exchange)
    position = Position(
        symbol="BTC/USDT",
        quantity=Decimal("0.2"),
        avg_entry_price=Decimal("50000"),
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        source_wallet="0xabc123",
    )

    result = await executor.execute_exit("BTC/USDT", Decimal("0.5"), position=position)

    assert result.success is True
    exchange.create_order.assert_not_awaited()
    exchange.create_market_sell_order.assert_awaited_once_with("BTC/USDT", 0.1)


@pytest.mark.asyncio
async def test_quantize_fails_closed_when_symbol_filters_missing() -> None:
    exchange = build_exchange()
    exchange.load_markets = AsyncMock(return_value={"BTC/USDT": {}})
    decision = TradeDecision(
        action="buy",
        symbol="UNKNOWN/USDT",
        quantity_usdt=1000.0,
        confidence=80,
        reasoning="Execution test decision.",
        source_wallet="0xabc123",
    )
    executor = await _build_executor(paper_trading=False, exchange=exchange)

    result = await executor.execute(decision)

    assert result.success is False
    assert result.error == "min_notional_not_met"
    exchange.create_market_buy_order.assert_not_awaited()
