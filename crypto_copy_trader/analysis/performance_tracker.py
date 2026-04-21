from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


class PerformanceTracker:
    def __init__(self, trades_repo) -> None:
        self.trades_repo = trades_repo

    def update_daily_pnl(self, current_equity: Decimal) -> None:
        date = datetime.now(timezone.utc).date().isoformat()
        existing = self.trades_repo.get_daily_pnl(date)
        if existing is None:
            self.trades_repo.set_daily_pnl(
                date=date,
                realized_pnl_usdt=Decimal("0"),
                unrealized_pnl_usdt=Decimal("0"),
                starting_equity_usdt=current_equity,
            )
            return

        starting_equity = Decimal(str(existing["starting_equity_usdt"]))
        realized = Decimal(str(current_equity - starting_equity))
        self.trades_repo.set_daily_pnl(
            date=date,
            realized_pnl_usdt=realized,
            unrealized_pnl_usdt=Decimal("0"),
            starting_equity_usdt=starting_equity,
        )

    def wallet_performance(self, address: str, days: int = 30) -> dict:
        trades = [
            trade
            for trade in self.trades_repo.recent_trades(hours=days * 24)
            if trade["source_wallet"] == address
        ]
        if not trades:
            return {
                "trades": 0,
                "win_rate": 0.0,
                "avg_roi": 0.0,
                "max_drawdown": 0.0,
                "pnl_usdt": 0.0,
            }

        rois = [self._trade_roi(trade) for trade in trades]
        wins = [roi for roi in rois if roi > 0]
        pnl_usdt = sum((Decimal(str(trade["quantity_usdt"])) * Decimal(str(roi))) for trade, roi in zip(trades, rois))
        return {
            "trades": len(trades),
            "win_rate": round(len(wins) / len(trades), 4),
            "avg_roi": round(sum(rois) / len(rois), 4),
            "max_drawdown": round(min(rois), 4),
            "pnl_usdt": float(pnl_usdt),
        }

    def daily_pnl_pct(self, date: str | None = None) -> float:
        target_date = date or datetime.now(timezone.utc).date().isoformat()
        daily = self.trades_repo.get_daily_pnl(target_date)
        if daily is None:
            return 0.0

        starting_equity = float(daily["starting_equity_usdt"])
        if starting_equity == 0:
            return 0.0

        pnl = float(daily["realized_pnl_usdt"]) + float(daily["unrealized_pnl_usdt"])
        return round(pnl / starting_equity, 4)

    @staticmethod
    def _trade_roi(trade: dict) -> float:
        mid_price = float(trade.get("pre_trade_mid_price") or trade.get("price") or 0.0)
        if mid_price == 0:
            return 0.0
        return (float(trade["price"]) - mid_price) / mid_price
