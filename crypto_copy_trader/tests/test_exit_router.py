from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from models import OnChainEvent, Position
from signals.exit_router import should_mirror_exit


PEPE_ETH_ADDRESS = "0x6982508145454ce325ddbe47a25d4ec3d2311933"


def build_event(*, amount_token: str, raw: dict | None = None) -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc123",
        tx_hash="tx-exit",
        block_time=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
        tx_type="swap_out",
        token_symbol="PEPE",
        amount_token=Decimal(amount_token),
        amount_usd=Decimal("5000"),
        raw={} if raw is None else raw,
        token_address=PEPE_ETH_ADDRESS,
    )


def build_position(*, source_wallet: str = "0xabc123") -> Position:
    return Position(
        symbol="PEPE/USDT",
        quantity=Decimal("1000000"),
        avg_entry_price=Decimal("0.000001"),
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        source_wallet=source_wallet,
    )


def test_exit_full_when_wallet_sells_30pct() -> None:
    event = build_event(
        amount_token="300",
        raw={"wallet_token_balance_before": "1000"},
    )

    decision = should_mirror_exit(event, build_position())

    assert decision.should_exit is True
    assert decision.symbol == "PEPE/USDT"
    assert decision.fraction == Decimal("1")
    assert decision.reason == "mirror_wallet_0xabc123"


def test_exit_partial_when_wallet_sells_under_30pct() -> None:
    event = build_event(
        amount_token="100",
        raw={"wallet_token_balance_before": "1000"},
    )

    decision = should_mirror_exit(event, build_position())

    assert decision.should_exit is True
    assert decision.symbol == "PEPE/USDT"
    assert decision.fraction == Decimal("0.5")
    assert decision.reason == "mirror_wallet_0xabc123"


def test_exit_skips_when_no_matching_position() -> None:
    event = build_event(
        amount_token="300",
        raw={"wallet_token_balance_before": "1000"},
    )

    decision = should_mirror_exit(event, build_position(source_wallet="0xother"))

    assert decision.should_exit is False
    assert decision.reason == "source_wallet_mismatch"


def test_exit_matches_evm_wallet_case_insensitively() -> None:
    event = build_event(
        amount_token="300",
        raw={"wallet_token_balance_before": "1000"},
    )

    decision = should_mirror_exit(event, build_position(source_wallet="0xAbC123"))

    assert decision.should_exit is True
    assert decision.fraction == Decimal("1")


def test_rolling_fraction_overrides_current_event_fraction() -> None:
    event = build_event(
        amount_token="100",
        raw={"wallet_sell_fraction": "0.10", "rolling_sold_fraction": "0.30"},
    )

    decision = should_mirror_exit(event, build_position())

    assert decision.should_exit is True
    assert decision.fraction == Decimal("1")
