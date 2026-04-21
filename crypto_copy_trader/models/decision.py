from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


Action = Literal["buy", "sell", "hold", "skip"]
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+/USDT$")
MAX_REASONING_LENGTH = 200


@dataclass(frozen=True)
class TradeDecision:
    action: Action
    symbol: str
    quantity_usdt: float
    confidence: int
    reasoning: str
    source_wallet: str

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be between 0 and 100")

        if self.quantity_usdt < 0:
            raise ValueError("quantity_usdt must be non-negative")

        if not self.reasoning.strip():
            raise ValueError("reasoning must not be empty")

        if len(self.reasoning) > MAX_REASONING_LENGTH:
            raise ValueError("reasoning must not exceed 200 characters")

        if not SYMBOL_PATTERN.match(self.symbol):
            raise ValueError("symbol must match the format BASE/USDT")
