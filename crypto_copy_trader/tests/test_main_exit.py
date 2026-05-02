from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from main import PipelineDeps, process_event
from models import OnChainEvent, Portfolio, Position


PEPE_ETH_ADDRESS = "0x6982508145454ce325ddbe47a25d4ec3d2311933"


class FakeExitExecutor:
    def __init__(self) -> None:
        self.fetch_price = AsyncMock(return_value=Decimal("62000"))
        self.execute_exit = AsyncMock(return_value=SimpleNamespace(success=True))
        self.execute = AsyncMock()
        self.exit_started = asyncio.Event()
        self.release_exit = asyncio.Event()

    async def blocking_execute_exit(self, *args, **kwargs):
        self.exit_started.set()
        await self.release_exit.wait()
        return SimpleNamespace(success=True)


def build_event(*, tx_hash: str = "tx-exit", amount_token: str = "300", block_time: datetime | None = None) -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc123",
        tx_hash=tx_hash,
        block_time=block_time or datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
        tx_type="swap_out",
        token_symbol="PEPE",
        amount_token=Decimal(amount_token),
        amount_usd=Decimal("5000"),
        raw={"wallet_token_balance_before": "1000"},
        token_address=PEPE_ETH_ADDRESS,
    )


def build_position() -> Position:
    return Position(
        symbol="PEPE/USDT",
        quantity=Decimal("1000000"),
        avg_entry_price=Decimal("0.000001"),
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        source_wallet="0xabc123",
    )


def build_portfolio(*, positions: dict[str, Position] | None = None) -> Portfolio:
    return Portfolio(
        cash_usdt=Decimal("1000"),
        positions={} if positions is None else positions,
        total_value_usdt=Decimal("2000"),
        daily_pnl_pct=0.0,
    )


def build_deps(executor: FakeExitExecutor, trades_repo: object | None = None) -> PipelineDeps:
    return PipelineDeps(
        settings=SimpleNamespace(),
        addresses_repo=SimpleNamespace(),
        trades_repo=trades_repo or SimpleNamespace(),
        executor=executor,
        anthropic=SimpleNamespace(),
        claude_backend=SimpleNamespace(),
        batch_scorer=SimpleNamespace(),
        notifier=SimpleNamespace(notify_trade_fill=AsyncMock(), notify_risk_alert=AsyncMock()),
        trade_logger=SimpleNamespace(log_fill=Mock(), log_skip=Mock()),
        http=SimpleNamespace(),
        binance_symbols={"PEPE/USDT"},
        recent_events_cache=[],
        btc_24h_vol_pct=0.0,
        correlation_provider=lambda new_symbol, existing_symbols: {},
    )


@pytest.mark.asyncio
async def test_exit_skips_when_no_matching_position() -> None:
    executor = FakeExitExecutor()
    deps = build_deps(executor)

    await process_event(build_event(), build_portfolio(), 0.0, deps)

    executor.execute_exit.assert_not_awaited()
    deps.trade_logger.log_skip.assert_called_once()
    assert deps.trade_logger.log_skip.call_args.args[1] == "exit:no_matching_position"


@pytest.mark.asyncio
async def test_exit_lock_prevents_concurrent_buy(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = FakeExitExecutor()
    executor.execute_exit = AsyncMock(side_effect=executor.blocking_execute_exit)
    deps = build_deps(executor)
    portfolio = build_portfolio(positions={"PEPE/USDT": build_position()})

    exit_task = asyncio.create_task(process_event(build_event(tx_hash="tx-exit-1"), portfolio, 0.0, deps))
    await executor.exit_started.wait()

    second_task = asyncio.create_task(process_event(build_event(tx_hash="tx-exit-2"), portfolio, 0.0, deps))
    await asyncio.sleep(0)

    assert executor.execute_exit.await_count == 1

    executor.release_exit.set()
    await asyncio.gather(exit_task, second_task)

    assert executor.execute_exit.await_count == 2


@pytest.mark.asyncio
async def test_stale_portfolio_does_not_execute_duplicate_exit() -> None:
    executor = FakeExitExecutor()
    position = build_position()
    trades_repo = SimpleNamespace(get_positions=Mock(side_effect=[[position], []]))
    deps = build_deps(executor, trades_repo=trades_repo)
    portfolio = build_portfolio(positions={"PEPE/USDT": position})

    await process_event(build_event(tx_hash="tx-exit-1"), portfolio, 0.0, deps)
    await process_event(build_event(tx_hash="tx-exit-2"), portfolio, 0.0, deps)

    executor.execute_exit.assert_awaited_once()
    assert deps.trade_logger.log_skip.call_args.args[1] == "exit:no_matching_position"


@pytest.mark.asyncio
async def test_exit_uses_30_minute_rolling_sell_window() -> None:
    executor = FakeExitExecutor()
    deps = build_deps(executor)
    portfolio = build_portfolio(positions={"PEPE/USDT": build_position()})
    start_time = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    await process_event(
        build_event(tx_hash="tx-exit-1", amount_token="100", block_time=start_time),
        portfolio,
        0.0,
        deps,
    )
    await process_event(
        build_event(tx_hash="tx-exit-2", amount_token="200", block_time=start_time + timedelta(minutes=5)),
        portfolio,
        0.0,
        deps,
    )

    assert executor.execute_exit.await_args_list[0].args[1] == Decimal("0.5")
    assert executor.execute_exit.await_args_list[1].args[1] == Decimal("1")


@pytest.mark.asyncio
async def test_failed_exit_sends_failed_alert_not_success_exit() -> None:
    executor = FakeExitExecutor()
    executor.execute_exit = AsyncMock(return_value=SimpleNamespace(success=False, error="min_notional_not_met"))
    deps = build_deps(executor)
    portfolio = build_portfolio(positions={"PEPE/USDT": build_position()})

    await process_event(build_event(), portfolio, 0.0, deps)

    deps.notifier.notify_risk_alert.assert_awaited_once()
    message = deps.notifier.notify_risk_alert.await_args.args[0]
    assert message.startswith("[EXIT_FAILED]")
    assert "[EXIT]" not in message


@pytest.mark.asyncio
async def test_exit_rechecks_repo_position_inside_symbol_lock() -> None:
    executor = FakeExitExecutor()
    position = build_position()
    trades_repo = SimpleNamespace(get_positions=Mock(return_value=[position]))
    deps = build_deps(executor, trades_repo=trades_repo)
    portfolio = build_portfolio()

    await process_event(build_event(), portfolio, 0.0, deps)

    executor.execute_exit.assert_awaited_once()
