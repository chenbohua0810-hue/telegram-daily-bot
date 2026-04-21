from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from models.events import OnChainEvent
from models.signals import WalletScore
from signals.quant_filter import quant_filter


def build_event(
    *,
    wallet: str = "0xabc123",
    token_symbol: str = "ETH",
    amount_usd: Decimal = Decimal("12000"),
    block_time: datetime | None = None,
) -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet=wallet,
        tx_hash="0xtx",
        block_time=block_time or datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol=token_symbol,
        amount_token=Decimal("1"),
        amount_usd=amount_usd,
        raw={"block_number": 100},
    )


def build_wallet(*, status: str = "active") -> WalletScore:
    return WalletScore(
        address="0xabc123",
        chain="eth",
        win_rate=0.7,
        trade_count=50,
        max_drawdown=0.2,
        funds_usd=100000.0,
        recent_win_rate=0.72,
        trust_level="high",
        status=status,
    )


def test_qf_passes_normal_event() -> None:
    passed, reason = quant_filter(
        event=build_event(),
        wallet=build_wallet(),
        binance_symbols={"ETH/USDT"},
        min_trade_usd=10000,
    )

    assert (passed, reason) == (True, "ok")


def test_qf_rejects_small_amount() -> None:
    passed, reason = quant_filter(
        event=build_event(amount_usd=Decimal("5000")),
        wallet=build_wallet(),
        binance_symbols={"ETH/USDT"},
        min_trade_usd=10000,
    )

    assert (passed, reason) == (False, "below_min_trade_usd")


def test_qf_rejects_unlisted_token() -> None:
    passed, reason = quant_filter(
        event=build_event(token_symbol="FAKE"),
        wallet=build_wallet(),
        binance_symbols={"ETH/USDT"},
        min_trade_usd=10000,
    )

    assert (passed, reason) == (False, "not_on_binance")


def test_qf_rejects_retired_wallet() -> None:
    passed, reason = quant_filter(
        event=build_event(),
        wallet=build_wallet(status="retired"),
        binance_symbols={"ETH/USDT"},
        min_trade_usd=10000,
    )

    assert (passed, reason) == (False, "wallet_inactive")


def test_qf_dedup_within_window() -> None:
    event_time = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    recent_event = build_event(
        block_time=event_time - timedelta(minutes=5),
    )

    passed, reason = quant_filter(
        event=build_event(block_time=event_time),
        wallet=build_wallet(),
        binance_symbols={"ETH/USDT"},
        min_trade_usd=10000,
        recent_events=[recent_event],
    )

    assert (passed, reason) == (False, "duplicate_recent")
