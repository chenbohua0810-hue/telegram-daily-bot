from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal


Chain = Literal["eth", "sol", "bsc"]
TransactionType = Literal["swap_in", "swap_out"]


@dataclass(frozen=True)
class OnChainEvent:
    chain: Chain
    wallet: str
    tx_hash: str
    block_time: datetime
    tx_type: TransactionType
    token_symbol: str
    amount_token: Decimal
    amount_usd: Decimal
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "wallet": self.wallet,
            "tx_hash": self.tx_hash,
            "block_time": self.block_time.isoformat(),
            "tx_type": self.tx_type,
            "token_symbol": self.token_symbol,
            "amount_token": str(self.amount_token),
            "amount_usd": str(self.amount_usd),
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OnChainEvent":
        return cls(
            chain=payload["chain"],
            wallet=payload["wallet"],
            tx_hash=payload["tx_hash"],
            block_time=datetime.fromisoformat(payload["block_time"]),
            tx_type=payload["tx_type"],
            token_symbol=payload["token_symbol"],
            amount_token=Decimal(payload["amount_token"]),
            amount_usd=Decimal(payload["amount_usd"]),
            raw=payload["raw"],
        )
