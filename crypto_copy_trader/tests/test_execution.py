from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from models.portfolio import Portfolio, Position
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
