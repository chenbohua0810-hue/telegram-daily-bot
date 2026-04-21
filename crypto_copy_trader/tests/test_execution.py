from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from execution.binance_executor import BinanceExecutor, ExecutionResult, NetworkError
from models.portfolio import Portfolio, Position
from models.decision import TradeDecision
from execution.position_sizer import compute_position_size
from execution.risk_guard import check_risk


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
async def test_live_trading_computes_realized_slippage() -> None:
    exchange = build_exchange()
    exchange.fetch_ticker = AsyncMock(return_value={"last": 100})
    exchange.fetch_order_book = AsyncMock(return_value={"bids": [[99.5, 10]], "asks": [[100.5, 10]]})
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
    exchange.fetch_order_book = AsyncMock(return_value={"bids": [[99.5, 10]], "asks": [[100.5, 10]]})
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
async def test_load_markets_filters_usdt_pairs() -> None:
    executor = await _build_executor(paper_trading=True)

    symbols = await executor.load_markets()

    assert symbols == {"BTC/USDT"}
