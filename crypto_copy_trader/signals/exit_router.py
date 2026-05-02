from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from models import OnChainEvent, Position
from signals.symbol_mapper import map_to_binance

FULL_EXIT_THRESHOLD = Decimal("0.30")
PARTIAL_EXIT_FRACTION = Decimal("0.5")
FULL_EXIT_FRACTION = Decimal("1")


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    symbol: str | None
    fraction: Decimal
    reason: str


def should_mirror_exit(event: OnChainEvent, position: Position) -> ExitDecision:
    symbol = map_to_binance(event.chain, event.token_address, event.token_symbol)
    if event.tx_type != "swap_out":
        return _skip(symbol, "not_swap_out")

    if symbol is None:
        return _skip(None, "not_on_binance")

    if _normalize_wallet(event.chain, event.wallet) != _normalize_wallet(event.chain, position.source_wallet):
        return _skip(symbol, "source_wallet_mismatch")

    if position.symbol != symbol:
        return _skip(symbol, "symbol_mismatch")

    sell_fraction = _extract_sell_fraction(event)
    exit_fraction = FULL_EXIT_FRACTION if sell_fraction >= FULL_EXIT_THRESHOLD else PARTIAL_EXIT_FRACTION
    return ExitDecision(
        should_exit=True,
        symbol=symbol,
        fraction=exit_fraction,
        reason=f"mirror_wallet_{event.wallet}",
    )


def _skip(symbol: str | None, reason: str) -> ExitDecision:
    return ExitDecision(
        should_exit=False,
        symbol=symbol,
        fraction=Decimal("0"),
        reason=reason,
    )


def _extract_sell_fraction(event: OnChainEvent) -> Decimal:
    for key in ("rolling_sold_fraction", "wallet_sell_fraction", "sell_fraction", "sold_fraction_of_holdings"):
        value = event.raw.get(key)
        if value is not None:
            return _to_decimal(value, field_name=key)

    for key in ("wallet_token_balance_before", "pre_balance_token", "balance_before_token"):
        value = event.raw.get(key)
        if value is None:
            continue

        balance_before = _to_decimal(value, field_name=key)
        if balance_before <= 0:
            return Decimal("0")
        return event.amount_token / balance_before

    return Decimal("0")


def _normalize_wallet(chain: str, wallet: str) -> str:
    normalized = wallet.strip()
    if chain.lower().strip() in {"eth", "bsc"}:
        return normalized.lower()
    return normalized


def _to_decimal(value: object, *, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error
