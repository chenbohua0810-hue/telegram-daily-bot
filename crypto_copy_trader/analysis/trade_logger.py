from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from execution.binance_executor import ExecutionResult
from models.decision import TradeDecision
from models.portfolio import Position
from models.snapshot import DecisionSnapshot


class TradeLogger:
    def __init__(self, trades_repo) -> None:
        self.trades_repo = trades_repo

    def log_fill(
        self,
        decision: TradeDecision,
        result: ExecutionResult,
        snapshot: DecisionSnapshot,
    ) -> int:
        trade_id = self.trades_repo.record_trade(
            symbol=decision.symbol,
            action=decision.action,
            quantity=result.filled_quantity,
            price=result.avg_price,
            fee_usdt=result.fee_usdt,
            source_wallet=decision.source_wallet,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            status="paper" if result.binance_order_id is None and result.success else "filled",
            paper_trading=result.binance_order_id is None,
            binance_order_id=result.binance_order_id,
            pre_trade_mid_price=result.pre_trade_mid_price,
            estimated_slippage_pct=result.estimated_slippage_pct,
            realized_slippage_pct=result.realized_slippage_pct,
            estimated_fee_pct=result.estimated_fee_pct,
            realized_fee_pct=result.realized_fee_pct,
        )
        linked_snapshot = replace(snapshot, trade_id=trade_id)
        self.trades_repo.record_snapshot(linked_snapshot)

        if decision.action == "buy":
            self.trades_repo.upsert_position(
                Position(
                    symbol=decision.symbol,
                    quantity=result.filled_quantity,
                    avg_entry_price=result.avg_price,
                    entry_time=datetime.now(timezone.utc),
                    source_wallet=decision.source_wallet,
                )
            )
        elif decision.action == "sell":
            self.trades_repo.remove_position(decision.symbol)

        return trade_id

    def log_skip(self, event, reason: str, snapshot: DecisionSnapshot) -> None:
        self.trades_repo.record_snapshot(snapshot)
