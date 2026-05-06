from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LiveOrderResult:
    accepted: bool
    reason_code: str
    order_id: str | None = None
    rejected_order: dict[str, Any] | None = None


class LiveExecutorDisabled:
    def submit_order(self, order: dict[str, Any]) -> LiveOrderResult:
        return LiveOrderResult(
            accepted=False,
            reason_code="live_trading_not_implemented",
            order_id=None,
            rejected_order=None,
        )
