from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from freezegun import freeze_time

from models.events import OnChainEvent
from models.signals import WalletScore
from models.snapshot import DecisionSnapshotBuilder
from storage.addresses_repo import AddressesRepo
from storage.event_log import EventLog
from storage.trades_repo import TradesRepo
from verification.runtime_health import build_runtime_health_report


def build_wallet_score(*, address: str = "0xabc123") -> WalletScore:
    return WalletScore(
        address=address,
        chain="eth",
        win_rate=0.72,
        trade_count=64,
        max_drawdown=0.18,
        funds_usd=125000.0,
        recent_win_rate=0.7,
        trust_level="high",
        status="active",
    )


def build_event(*, tx_hash: str = "0xtxhash") -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc123",
        tx_hash=tx_hash,
        block_time=datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol="ETH",
        amount_token=Decimal("1.5"),
        amount_usd=Decimal("3000"),
        raw={"hash": tx_hash},
    )


def test_build_runtime_health_report_returns_zeroed_values_when_no_runtime_data(tmp_path) -> None:
    addresses_db_path = str(tmp_path / "addresses.db")
    trades_db_path = str(tmp_path / "trades.db")
    AddressesRepo(addresses_db_path)
    TradesRepo(trades_db_path)
    report = build_runtime_health_report(
        addresses_db_path=addresses_db_path,
        trades_db_path=trades_db_path,
        events_log_path=str(tmp_path / "events.jsonl"),
        lookback_hours=24,
    )

    assert report.event_count == 0
    assert report.wallet_history_count == 0
    assert report.snapshot_action_counts == {}
    assert report.skip_reason_counts == {}
    assert report.paper_trade_count == 0
    assert report.avg_estimated_slippage_pct is None
    assert report.avg_realized_slippage_pct is None
    assert report.backend_fallback_rate == 0.0
    assert report.batch_flush_latency_ms == 0.0
    assert report.ws_reconnect_count == {}


def test_build_runtime_health_report_summarizes_runtime_artifacts(tmp_path) -> None:
    addresses_db_path = str(tmp_path / "addresses.db")
    trades_db_path = str(tmp_path / "trades.db")
    addresses_repo = AddressesRepo(addresses_db_path)
    trades_repo = TradesRepo(trades_db_path)
    event_log = EventLog(str(tmp_path / "events.jsonl"))
    wallet_score = build_wallet_score()
    event = build_event()
    addresses_repo.upsert_wallet(wallet_score)
    addresses_repo.append_history(
        wallet_score.address,
        wallet_score,
        decision="keep",
        reasoning="stable",
        evaluated_at=datetime(2026, 4, 22, 11, 0, tzinfo=timezone.utc),
    )
    event_log.append(event)

    with freeze_time("2026-04-22T12:30:00+00:00"):
        trade_id = trades_repo.record_trade(
            symbol="ETH/USDT",
            action="buy",
            quantity=Decimal("0.5"),
            price=Decimal("3000"),
            fee_usdt=Decimal("1.2"),
            source_wallet=wallet_score.address,
            confidence=85,
            reasoning="copied",
            status="paper",
            paper_trading=True,
            estimated_slippage_pct=0.0015,
            realized_slippage_pct=0.0025,
        )

        snapshot_id = trades_repo.record_snapshot(
            DecisionSnapshotBuilder(
                event=event,
                symbol="ETH/USDT",
                recorded_at=datetime(2026, 4, 22, 12, 30, tzinfo=timezone.utc),
            ).execute("buy")
        )
        trades_repo.link_snapshot_to_trade(snapshot_id, trade_id)
        trades_repo.record_snapshot(
            DecisionSnapshotBuilder(
                event=build_event(tx_hash="0xskip"),
                symbol="BTC/USDT",
                recorded_at=datetime(2026, 4, 22, 12, 31, tzinfo=timezone.utc),
            ).skip("below_min_trade_usd")
        )

        report = build_runtime_health_report(
            addresses_db_path=addresses_db_path,
            trades_db_path=trades_db_path,
            events_log_path=str(tmp_path / "events.jsonl"),
            lookback_hours=24,
            fallback_backend=SimpleNamespace(fallback_rate=0.25),
            batch_scorer=SimpleNamespace(batch_flush_latency_ms=18.5),
            websocket_monitors={
                "eth": SimpleNamespace(ws_reconnect_count=2),
                "sol": SimpleNamespace(ws_reconnect_count=1),
            },
        )

    assert report.event_count == 1
    assert report.wallet_history_count == 1
    assert report.snapshot_action_counts == {"buy": 1, "skip": 1}
    assert report.skip_reason_counts == {"below_min_trade_usd": 1}
    assert report.paper_trade_count == 1
    assert report.avg_estimated_slippage_pct == 0.0015
    assert report.avg_realized_slippage_pct == 0.0025
    assert report.backend_fallback_rate == 0.25
    assert report.batch_flush_latency_ms == 18.5
    assert report.ws_reconnect_count == {"eth": 2, "sol": 1}
