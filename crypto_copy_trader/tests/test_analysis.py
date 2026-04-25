from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from reporting import TradeLogger
from reporting import PerformanceTracker
from reporting import TelegramNotifier
from execution import ExecutionResult
from models import TradeDecision
from models import OnChainEvent
from models import DecisionSnapshotBuilder


def build_event() -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc123",
        tx_hash="0xtx",
        block_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol="ETH",
        amount_token=Decimal("1"),
        amount_usd=Decimal("2000"),
        raw={"block_number": 100},
    )


def build_decision(action: str = "buy") -> TradeDecision:
    return TradeDecision(
        action=action,
        symbol="ETH/USDT",
        quantity_usdt=1000.0,
        confidence=80,
        reasoning="analysis test",
        source_wallet="0xabc123",
    )


def build_snapshot(action: str = "buy"):
    builder = DecisionSnapshotBuilder(
        event=build_event(),
        symbol="ETH/USDT",
        recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
    )
    if action == "skip":
        return builder.skip("below_min_trade_usd")
    return builder.execute(action)


def build_result() -> ExecutionResult:
    return ExecutionResult(
        success=True,
        filled_quantity=Decimal("0.5"),
        avg_price=Decimal("2000"),
        fee_usdt=Decimal("0.75"),
        pre_trade_mid_price=Decimal("1999"),
        estimated_slippage_pct=0.001,
        realized_slippage_pct=0.0005,
        estimated_fee_pct=0.0015,
        realized_fee_pct=0.00075,
        binance_order_id="order-1",
        error=None,
    )


def test_log_fill_buy_creates_position_and_snapshot() -> None:
    repo = Mock()
    repo.record_trade.return_value = 42
    logger = TradeLogger(repo)

    trade_id = logger.log_fill(build_decision("buy"), build_result(), build_snapshot("buy"))

    assert trade_id == 42
    assert repo.record_trade.called
    assert repo.record_snapshot.called
    assert repo.upsert_position.called
    snapshot = repo.record_snapshot.call_args.args[0]
    assert snapshot.trade_id == 42


def test_log_fill_sell_removes_position_if_zero() -> None:
    repo = Mock()
    repo.record_trade.return_value = 7
    logger = TradeLogger(repo)

    trade_id = logger.log_fill(build_decision("sell"), build_result(), build_snapshot("sell"))

    assert trade_id == 7
    assert repo.remove_position.called
    snapshot = repo.record_snapshot.call_args.args[0]
    assert snapshot.final_action == "sell"


def test_log_skip_writes_snapshot_not_trade() -> None:
    repo = Mock()
    logger = TradeLogger(repo)

    logger.log_skip(build_event(), "below_min_trade_usd", build_snapshot("skip"))

    repo.record_snapshot.assert_called_once()
    repo.record_trade.assert_not_called()


def test_log_skip_snapshot_has_skip_reason() -> None:
    repo = Mock()
    logger = TradeLogger(repo)

    logger.log_skip(build_event(), "below_min_trade_usd", build_snapshot("skip"))

    snapshot = repo.record_snapshot.call_args.args[0]
    assert snapshot.final_action == "skip"
    assert snapshot.skip_reason
    assert snapshot.trade_id is None


def test_update_daily_pnl_first_call_sets_starting_equity() -> None:
    repo = Mock()
    repo.get_daily_pnl.return_value = None
    tracker = PerformanceTracker(repo)

    tracker.update_daily_pnl(Decimal("10000"))

    kwargs = repo.set_daily_pnl.call_args.kwargs
    assert kwargs["starting_equity_usdt"] == Decimal("10000")
    assert kwargs["realized_pnl_usdt"] == Decimal("0")
    assert kwargs["unrealized_pnl_usdt"] == Decimal("0")


def test_daily_pnl_pct_computes_correctly() -> None:
    repo = Mock()
    repo.get_daily_pnl.return_value = {
        "date": "2026-04-21",
        "realized_pnl_usdt": 300.0,
        "unrealized_pnl_usdt": -100.0,
        "starting_equity_usdt": 10000.0,
    }
    tracker = PerformanceTracker(repo)

    assert tracker.daily_pnl_pct("2026-04-21") == 0.02


def test_wallet_performance_calculates_winrate() -> None:
    repo = Mock()
    repo.recent_trades.return_value = [
        {"source_wallet": "0xabc123", "quantity_usdt": 100.0, "fee_usdt": 1.0, "action": "buy", "status": "filled", "realized_slippage_pct": 0.0, "price": 110.0, "pre_trade_mid_price": 100.0},
        {"source_wallet": "0xabc123", "quantity_usdt": 100.0, "fee_usdt": 1.0, "action": "buy", "status": "filled", "realized_slippage_pct": 0.0, "price": 108.0, "pre_trade_mid_price": 100.0},
        {"source_wallet": "0xabc123", "quantity_usdt": 100.0, "fee_usdt": 1.0, "action": "buy", "status": "filled", "realized_slippage_pct": 0.0, "price": 105.0, "pre_trade_mid_price": 100.0},
        {"source_wallet": "0xabc123", "quantity_usdt": 100.0, "fee_usdt": 1.0, "action": "buy", "status": "filled", "realized_slippage_pct": 0.0, "price": 95.0, "pre_trade_mid_price": 100.0},
        {"source_wallet": "0xabc123", "quantity_usdt": 100.0, "fee_usdt": 1.0, "action": "buy", "status": "filled", "realized_slippage_pct": 0.0, "price": 90.0, "pre_trade_mid_price": 100.0},
    ]
    tracker = PerformanceTracker(repo)

    performance = tracker.wallet_performance("0xabc123")

    assert performance["trades"] == 5
    assert performance["win_rate"] == 0.6


def test_wallet_performance_empty_returns_zero() -> None:
    repo = Mock()
    repo.recent_trades.return_value = []
    tracker = PerformanceTracker(repo)

    performance = tracker.wallet_performance("0xabc123")

    assert performance == {
        "trades": 0,
        "win_rate": 0.0,
        "avg_roi": 0.0,
        "max_drawdown": 0.0,
        "pnl_usdt": 0.0,
    }


@pytest.mark.asyncio
async def test_notify_trade_fill_sends_message() -> None:
    bot = Mock()
    bot.send_message = AsyncMock()
    notifier = TelegramNotifier("token", "chat", bot=bot)

    await notifier.notify_trade_fill(build_decision("buy"), build_result())

    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_skip_sends_short_message() -> None:
    bot = Mock()
    bot.send_message = AsyncMock()
    notifier = TelegramNotifier("token", "chat", bot=bot)

    await notifier.notify_trade_skip(build_event(), "below_min_trade_usd")

    text = bot.send_message.await_args.kwargs["text"]
    assert "below" in text
    assert "ETH" in text


@pytest.mark.asyncio
async def test_telegram_api_error_swallowed(caplog: pytest.LogCaptureFixture) -> None:
    bot = Mock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("boom"))
    notifier = TelegramNotifier("token", "chat", bot=bot)

    await notifier.notify_trade_skip(build_event(), "below_min_trade_usd")

    assert "Telegram notification failed" in caplog.text


@pytest.mark.asyncio
async def test_markdown_escape_special_chars() -> None:
    bot = Mock()
    bot.send_message = AsyncMock()
    notifier = TelegramNotifier("token", "chat", bot=bot)

    await notifier.notify_trade_skip(build_event(), "reason_with_*_chars")

    text = bot.send_message.await_args.kwargs["text"]
    assert "\\_" in text
    assert "\\*" in text
