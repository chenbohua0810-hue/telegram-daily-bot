from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from storage.db import get_connection
from storage.event_log import EventLog
from storage.trades_repo import TradesRepo


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
        if trade["status"] == "paper" and trade[metric_name] is not None
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
