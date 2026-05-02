from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from execution import position_stop_check
from models import Position


def build_position(
    *,
    avg_entry_price: str = "100",
    entry_age: timedelta = timedelta(hours=1),
    peak_price: str | None = None,
) -> Position:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    return Position(
        symbol="ETH/USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal(avg_entry_price),
        entry_time=now - entry_age,
        source_wallet="0xabc123",
        peak_price=None if peak_price is None else Decimal(peak_price),
    )


def test_stop_loss_triggers_at_minus_8pct() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    action = position_stop_check(
        build_position(),
        Decimal("92"),
        btc_24h_change=0.0,
        now=now,
    )

    assert action is not None
    assert action.fraction == Decimal("1")
    assert action.reason == "stop_loss_-8pct"


def test_trailing_stop_triggers_after_peak_then_drawdown() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    action = position_stop_check(
        build_position(peak_price="150"),
        Decimal("105"),
        btc_24h_change=0.0,
        now=now,
    )

    assert action is not None
    assert action.reason == "trailing_stop"


def test_time_stop_triggers_after_48h_flat() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    action = position_stop_check(
        build_position(entry_age=timedelta(hours=49)),
        Decimal("101"),
        btc_24h_change=0.0,
        now=now,
    )

    assert action is not None
    assert action.reason == "time_stop_no_progress"


def test_market_regime_tightens_stop_when_btc_crashes() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    action = position_stop_check(
        build_position(),
        Decimal("95"),
        btc_24h_change=-0.11,
        now=now,
    )

    assert action is not None
    assert action.reason == "stop_loss_-5pct_market_regime"


def test_max_hold_period_triggers_after_7_days() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    action = position_stop_check(
        build_position(entry_age=timedelta(days=8)),
        Decimal("150"),
        btc_24h_change=0.0,
        now=now,
    )

    assert action is not None
    assert action.reason == "max_hold_period"
