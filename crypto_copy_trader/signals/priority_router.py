from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from models.events import OnChainEvent
from models.signals import WalletScore


@dataclass(frozen=True)
class PriorityDecision:
    level: Literal["P0", "P1", "P2", "P3"]
    reason: str


def assign_priority(
    event: OnChainEvent,
    wallet: WalletScore,
    *,
    known_tokens: set[str],
    quant_passed: bool,
    high_value_usd: float,
    p1_min_usd: float,
    p1_min_win_rate: float,
) -> PriorityDecision:
    if not quant_passed:
        return PriorityDecision(level="P3", reason="quant_filter_failed")

    amount = float(event.amount_usd)

    if amount >= high_value_usd:
        return PriorityDecision(level="P0", reason="high_value_usd")

    if event.token_symbol not in known_tokens:
        return PriorityDecision(level="P0", reason="unknown_token")

    if (
        wallet.trust_level == "high"
        and wallet.recent_win_rate >= p1_min_win_rate
        and amount >= p1_min_usd
    ):
        return PriorityDecision(level="P1", reason="high_trust_direct_copy")

    return PriorityDecision(level="P2", reason="batch_scorer")
