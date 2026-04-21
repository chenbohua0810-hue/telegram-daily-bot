from __future__ import annotations

from models.events import OnChainEvent
from models.signals import WalletScore


def quant_filter(
    event: OnChainEvent,
    wallet: WalletScore,
    binance_symbols: set[str],
    min_trade_usd: float,
    dedup_window_seconds: int = 600,
    recent_events: list[OnChainEvent] | None = None,
) -> tuple[bool, str]:
    if float(event.amount_usd) < min_trade_usd:
        return False, "below_min_trade_usd"

    if f"{event.token_symbol}/USDT" not in binance_symbols:
        return False, "not_on_binance"

    if wallet.status != "active":
        return False, "wallet_inactive"

    if recent_events is None:
        return True, "ok"

    for recent_event in recent_events:
        same_wallet = recent_event.wallet == event.wallet
        same_token = recent_event.token_symbol == event.token_symbol
        within_window = abs((event.block_time - recent_event.block_time).total_seconds()) <= dedup_window_seconds

        if same_wallet and same_token and within_window:
            return False, "duplicate_recent"

    return True, "ok"
