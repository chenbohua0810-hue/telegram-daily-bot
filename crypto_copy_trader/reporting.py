from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from execution import ExecutionResult
from models import DecisionSnapshot, OnChainEvent, Position, TradeDecision
from storage import EventLog, TradesRepo, get_connection


# ---------------------------------------------------------------------------
# performance_tracker
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# telegram_notifier
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)
MARKDOWN_V2_SPECIALS = "_*[]()~`>#+-=|{}.!"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, *, bot=None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = bot

    async def notify_trade_fill(self, decision, result) -> None:
        text = "\n".join(
            [
                "*🟢 Copy Trade Filled*",
                f"Symbol: `{self._escape(decision.symbol)}`",
                f"Action: `{self._escape(decision.action)}`",
                f"Size: `${decision.quantity_usdt:.2f}`",
                f"Price: `${result.avg_price}`",
                f"Wallet: `{self._escape(decision.source_wallet[:8])}...`",
                f"Confidence: `{decision.confidence}`",
                f"Reason: {self._escape(decision.reasoning)}",
            ]
        )
        await self._send(text)

    async def notify_trade_skip(self, event, reason: str) -> None:
        text = f"*Skip* `{self._escape(event.token_symbol)}` {self._escape(reason)}"
        await self._send(text)

    async def notify_risk_alert(self, message: str) -> None:
        await self._send(f"*Risk Alert* {self._escape(message)}")

    async def notify_daily_summary(
        self,
        date: str,
        total_trades: int,
        win_rate: float,
        pnl_pct: float,
    ) -> None:
        text = (
            f"*Daily Summary* `{self._escape(date)}`\n"
            f"Trades: `{total_trades}`\n"
            f"Win Rate: `{win_rate:.2%}`\n"
            f"PnL: `{pnl_pct:.2%}`"
        )
        await self._send(text)

    async def _send(self, text: str) -> None:
        if self.bot is None:
            return
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="MarkdownV2",
            )
        except Exception:
            _logger.error("Telegram notification failed", exc_info=True)

    def _escape(self, value: str) -> str:
        escaped = value
        for char in MARKDOWN_V2_SPECIALS:
            escaped = escaped.replace(char, f"\\{char}")
        return escaped

    async def initialize(self) -> None:
        if self.bot is None:
            return
        try:
            await self.bot.initialize()
        except Exception:
            _logger.warning("Telegram bot initialize failed", exc_info=True)

    async def aclose(self) -> None:
        if self.bot is None:
            return
        shutdown = getattr(self.bot, "shutdown", None)
        if shutdown is None:
            return
        try:
            await shutdown()
        except Exception:
            _logger.warning("Telegram bot shutdown failed", exc_info=True)


# ---------------------------------------------------------------------------
# trade_logger
# ---------------------------------------------------------------------------


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

    def log_skip(self, event: OnChainEvent, reason: str, snapshot: DecisionSnapshot) -> None:
        self.trades_repo.record_snapshot(snapshot)


# ---------------------------------------------------------------------------
# runtime_health
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeHealthReport:
    lookback_hours: int
    event_count: int
    wallet_history_count: int
    snapshot_action_counts: dict[str, int]
    skip_reason_counts: dict[str, int]
    paper_trade_count: int
    avg_estimated_slippage_pct: float | None
    avg_realized_slippage_pct: float | None
    backend_fallback_rate: float
    batch_flush_latency_ms: float
    ws_reconnect_count: dict[str, int]


def build_runtime_health_report(
    *,
    addresses_db_path: str,
    trades_db_path: str,
    events_log_path: str,
    lookback_hours: int = 24,
    fallback_backend: Any | None = None,
    batch_scorer: Any | None = None,
    websocket_monitors: dict[str, Any] | None = None,
) -> RuntimeHealthReport:
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    trades_repo = TradesRepo(trades_db_path)

    return RuntimeHealthReport(
        lookback_hours=lookback_hours,
        event_count=_count_recent_events(events_log_path, since),
        wallet_history_count=_count_wallet_history(addresses_db_path, since),
        snapshot_action_counts=_snapshot_action_counts(trades_repo, since),
        skip_reason_counts=trades_repo.skip_reason_counts(since=since),
        paper_trade_count=_paper_trade_count(trades_repo, lookback_hours),
        avg_estimated_slippage_pct=_average_trade_metric(trades_repo, lookback_hours, "estimated_slippage_pct"),
        avg_realized_slippage_pct=_average_trade_metric(trades_repo, lookback_hours, "realized_slippage_pct"),
        backend_fallback_rate=_backend_fallback_rate(fallback_backend),
        batch_flush_latency_ms=_batch_flush_latency_ms(batch_scorer),
        ws_reconnect_count=_ws_reconnect_count(websocket_monitors),
    )


def format_runtime_health_report(report: RuntimeHealthReport) -> str:
    return "\n".join(
        (
            f"lookback_hours: {report.lookback_hours}",
            f"event_count: {report.event_count}",
            f"wallet_history_count: {report.wallet_history_count}",
            f"snapshot_action_counts: {json.dumps(report.snapshot_action_counts, sort_keys=True)}",
            f"skip_reason_counts: {json.dumps(report.skip_reason_counts, sort_keys=True)}",
            f"paper_trade_count: {report.paper_trade_count}",
            f"avg_estimated_slippage_pct: {_format_optional_float(report.avg_estimated_slippage_pct)}",
            f"avg_realized_slippage_pct: {_format_optional_float(report.avg_realized_slippage_pct)}",
            f"backend_fallback_rate: {_format_optional_float(report.backend_fallback_rate)}",
            f"batch_flush_latency_ms: {_format_optional_float(report.batch_flush_latency_ms)}",
            f"ws_reconnect_count: {json.dumps(report.ws_reconnect_count, sort_keys=True)}",
        )
    )


def _count_recent_events(events_log_path: str, since: datetime) -> int:
    event_log = EventLog(events_log_path)
    return sum(1 for _ in event_log.iter_events(since=since))


def _count_wallet_history(addresses_db_path: str, since: datetime) -> int:
    db = get_connection(addresses_db_path)

    try:
        row = db.execute(
            "SELECT COUNT(*) AS count FROM wallet_history WHERE evaluated_at >= ?",
            (since.isoformat(),),
        ).fetchone()
    finally:
        db.close()

    return 0 if row is None else int(row["count"])


def _snapshot_action_counts(trades_repo: TradesRepo, since: datetime) -> dict[str, int]:
    snapshots = trades_repo.get_snapshots(since=since, limit=10000)
    counts: dict[str, int] = {}

    for snapshot in snapshots:
        counts[snapshot.final_action] = counts.get(snapshot.final_action, 0) + 1

    return dict(sorted(counts.items()))


def _paper_trade_count(trades_repo: TradesRepo, lookback_hours: int) -> int:
    trades = [trade for trade in trades_repo.recent_trades(hours=lookback_hours) if trade["status"] == "paper"]
    return len(trades)


def _average_trade_metric(
    trades_repo: TradesRepo,
    lookback_hours: int,
    metric_name: str,
) -> float | None:
    values = [
        float(trade[metric_name])
        for trade in trades_repo.recent_trades(hours=lookback_hours)
        if trade["status"] in ("paper", "filled") and trade[metric_name] is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)


def _backend_fallback_rate(fallback_backend: Any | None) -> float:
    return 0.0 if fallback_backend is None else float(getattr(fallback_backend, "fallback_rate", 0.0))


def _batch_flush_latency_ms(batch_scorer: Any | None) -> float:
    return 0.0 if batch_scorer is None else float(getattr(batch_scorer, "batch_flush_latency_ms", 0.0))


def _ws_reconnect_count(websocket_monitors: dict[str, Any] | None) -> dict[str, int]:
    if websocket_monitors is None:
        return {}
    return {
        chain: int(getattr(monitor, "ws_reconnect_count", 0))
        for chain, monitor in websocket_monitors.items()
    }


def _format_optional_float(value: float | None) -> str:
    return "null" if value is None else f"{value:.10f}".rstrip("0").rstrip(".")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize runtime verification artifacts.")
    parser.add_argument("--addresses-db", default="data/addresses.db")
    parser.add_argument("--trades-db", default="data/trades.db")
    parser.add_argument("--events-log", default="data/events.jsonl")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = build_runtime_health_report(
        addresses_db_path=args.addresses_db,
        trades_db_path=args.trades_db,
        events_log_path=args.events_log,
        lookback_hours=args.hours,
    )
    output = json.dumps(asdict(report), sort_keys=True) if args.as_json else format_runtime_health_report(report)
    print(output)


if __name__ == "__main__":
    main()
