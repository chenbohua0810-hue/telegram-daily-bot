from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from kronos_trading_bot.domain import PaperFill, PaperPosition, TradeSide


@dataclass(frozen=True)
class PaperPortfolio:
    cash_usdt: float
    positions: Mapping[str, PaperPosition] = field(default_factory=dict)
    fills: tuple[PaperFill, ...] = ()
    fees_paid_usdt: float = 0.0
    realized_pnl_usdt: float = 0.0

    @classmethod
    def initial(cls, cash_usdt: float) -> PaperPortfolio:
        return cls(cash_usdt=cash_usdt, positions=MappingProxyType({}))


def simulate_buy(
    portfolio: PaperPortfolio,
    *,
    symbol: str,
    notional_usdt: float,
    market_price: float,
    fee_rate: float,
    slippage_bps: float,
) -> tuple[PaperPortfolio, PaperFill]:
    fill_price = market_price * (1 + slippage_bps / 10_000)
    quantity = notional_usdt / fill_price
    fee_usdt = notional_usdt * fee_rate

    existing = portfolio.positions.get(symbol)
    if existing is None:
        updated_quantity = quantity
        average_entry_price = fill_price
    else:
        updated_quantity = existing.quantity + quantity
        average_entry_price = (
            (existing.quantity * existing.average_entry_price)
            + (quantity * fill_price)
        ) / updated_quantity

    position = PaperPosition(
        symbol=symbol,
        quantity=updated_quantity,
        average_entry_price=average_entry_price,
    )
    fill = PaperFill(
        symbol=symbol,
        side=TradeSide.BUY,
        quantity=quantity,
        fill_price=fill_price,
        notional_usdt=notional_usdt,
        fee_usdt=fee_usdt,
    )
    positions = dict(portfolio.positions)
    positions[symbol] = position

    updated = PaperPortfolio(
        cash_usdt=portfolio.cash_usdt - notional_usdt - fee_usdt,
        positions=MappingProxyType(positions),
        fills=(*portfolio.fills, fill),
        fees_paid_usdt=portfolio.fees_paid_usdt + fee_usdt,
        realized_pnl_usdt=portfolio.realized_pnl_usdt,
    )
    return updated, fill


def simulate_sell_to_close(
    portfolio: PaperPortfolio,
    *,
    symbol: str,
    market_price: float,
    fee_rate: float,
    slippage_bps: float,
) -> tuple[PaperPortfolio, PaperFill]:
    position = portfolio.positions.get(symbol)
    if position is None:
        raise ValueError(f"No open paper position for symbol: {symbol}")

    fill_price = market_price * (1 - slippage_bps / 10_000)
    notional_usdt = position.quantity * fill_price
    fee_usdt = notional_usdt * fee_rate
    cost_basis_usdt = position.quantity * position.average_entry_price
    realized_pnl = notional_usdt - fee_usdt - cost_basis_usdt

    fill = PaperFill(
        symbol=symbol,
        side=TradeSide.SELL,
        quantity=position.quantity,
        fill_price=fill_price,
        notional_usdt=notional_usdt,
        fee_usdt=fee_usdt,
        realized_pnl_usdt=realized_pnl,
    )
    positions = dict(portfolio.positions)
    positions.pop(symbol)

    updated = PaperPortfolio(
        cash_usdt=portfolio.cash_usdt + notional_usdt - fee_usdt,
        positions=MappingProxyType(positions),
        fills=(*portfolio.fills, fill),
        fees_paid_usdt=portfolio.fees_paid_usdt + fee_usdt,
        realized_pnl_usdt=portfolio.realized_pnl_usdt + realized_pnl,
    )
    return updated, fill


def unrealized_pnl_usdt(
    portfolio: PaperPortfolio,
    *,
    symbol: str,
    current_price: float,
) -> float:
    position = portfolio.positions.get(symbol)
    if position is None:
        return 0.0
    return position.quantity * (current_price - position.average_entry_price)
