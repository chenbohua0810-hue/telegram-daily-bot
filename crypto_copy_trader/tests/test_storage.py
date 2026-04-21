from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from freezegun import freeze_time

from models.events import OnChainEvent
from models.portfolio import Position
from models.signals import WalletScore
from models.snapshot import DecisionSnapshotBuilder
from storage.addresses_repo import AddressesRepo
from storage.db import get_connection, init_addresses_db, init_trades_db
from storage.trades_repo import TradesRepo


def build_wallet_score(
    *,
    address: str = "0xabc123",
    chain: str = "eth",
    win_rate: float = 0.7,
    trade_count: int = 50,
    max_drawdown: float = 0.2,
    funds_usd: float = 100000.0,
    recent_win_rate: float = 0.72,
    trust_level: str = "high",
    status: str = "active",
) -> WalletScore:
    return WalletScore(
        address=address,
        chain=chain,
        win_rate=win_rate,
        trade_count=trade_count,
        max_drawdown=max_drawdown,
        funds_usd=funds_usd,
        recent_win_rate=recent_win_rate,
        trust_level=trust_level,
        status=status,
    )


def build_event(
    *,
    wallet: str = "0xabc123",
    tx_hash: str = "0xtxhash",
    block_time: datetime | None = None,
) -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet=wallet,
        tx_hash=tx_hash,
        block_time=block_time or datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol="ETH",
        amount_token=Decimal("1.5"),
        amount_usd=Decimal("3000"),
        raw={"hash": tx_hash},
    )


def build_position(symbol: str = "ETH/USDT") -> Position:
    return Position(
        symbol=symbol,
        quantity=Decimal("1.25"),
        avg_entry_price=Decimal("2400"),
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        source_wallet="0xabc123",
    )


def build_skip_snapshot(
    *,
    symbol: str = "ETH/USDT",
    reason: str = "low_confidence",
) -> object:
    return DecisionSnapshotBuilder(
        event=build_event(),
        symbol=symbol,
        recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
    ).skip(reason)


def build_execute_snapshot(symbol: str = "ETH/USDT") -> object:
    ai_score = SimpleNamespace(
        confidence=81,
        reasoning="Aligned signal stack.",
        recommendation="execute",
    )
    risk_result = SimpleNamespace(passed=True, multiplier=0.8, reasons=("ok", "sized_down"))
    cost_estimate = SimpleNamespace(
        slippage_pct=0.002,
        fee_pct=0.001,
        total_cost_pct=0.003,
        expected_profit_pct=0.025,
    )

    return (
        DecisionSnapshotBuilder(
            event=build_event(),
            symbol=symbol,
            recorded_at=datetime(2026, 4, 21, 12, 1, tzinfo=timezone.utc),
        )
        .with_technical(
            sig=SimpleNamespace(
                trend="bullish",
                momentum="bullish",
                volatility="medium",
                stat_arb="breakout",
                confidence=0.8,
            ),
            ind=SimpleNamespace(
                ema8=101.0,
                ema21=99.0,
                rsi=56.0,
                macd_hist=1.2,
                atr=2.1,
                atr_pct=0.02,
                bb_zscore=1.1,
                close_price=102.0,
            ),
        )
        .with_sentiment(
            sig=SimpleNamespace(signal="bullish", score=0.7, source_count=12),
            counts=SimpleNamespace(positive=8, negative=2, neutral=2, mention_delta=0.3),
        )
        .with_ai(ai_score)
        .with_risk(risk_result)
        .with_cost(cost_estimate)
        .with_market_regime(62000.0, 0.045)
        .execute("buy")
    )


def test_db_init_idempotent(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    trades_path = tmp_path / "trades.db"

    init_addresses_db(str(db_path))
    init_addresses_db(str(db_path))
    init_trades_db(str(trades_path))
    init_trades_db(str(trades_path))


def test_db_foreign_keys_on(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"

    connection = get_connection(str(db_path))

    try:
        foreign_keys = connection.execute("PRAGMA foreign_keys;").fetchone()[0]
    finally:
        connection.close()

    assert foreign_keys == 1


def test_upsert_insert_then_update(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))

    repo.upsert_wallet(build_wallet_score())
    repo.upsert_wallet(build_wallet_score(win_rate=0.8, trade_count=80))

    connection = get_connection(str(db_path))

    try:
        row_count = connection.execute("SELECT COUNT(*) FROM wallets").fetchone()[0]
    finally:
        connection.close()

    wallet = repo.get_wallet("0xabc123")

    assert row_count == 1
    assert wallet is not None
    assert wallet.win_rate == 0.8
    assert wallet.trade_count == 80


def test_list_active_filters_retired(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))

    repo.upsert_wallet(build_wallet_score(address="0x1"))
    repo.upsert_wallet(build_wallet_score(address="0x2", chain="sol"))
    repo.upsert_wallet(build_wallet_score(address="0x3", chain="bsc"))
    repo.upsert_wallet(build_wallet_score(address="0x4", status="retired"))

    active_wallets = repo.list_active()

    assert len(active_wallets) == 3
    assert {wallet.address for wallet in active_wallets} == {"0x1", "0x2", "0x3"}


def test_list_active_by_chain(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))

    repo.upsert_wallet(build_wallet_score(address="0x1", chain="eth"))
    repo.upsert_wallet(build_wallet_score(address="0x2", chain="sol"))
    repo.upsert_wallet(build_wallet_score(address="0x3", chain="eth"))

    active_wallets = repo.list_active(chain="eth")

    assert {wallet.address for wallet in active_wallets} == {"0x1", "0x3"}


def test_append_history_orders_desc(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))
    score = build_wallet_score()
    repo.upsert_wallet(score)

    repo.append_history(
        "0xabc123",
        score,
        decision="keep",
        reasoning="first",
        evaluated_at=datetime(2026, 4, 21, 0, 0, tzinfo=timezone.utc),
    )
    repo.append_history(
        "0xabc123",
        score,
        decision="watch",
        reasoning="second",
        evaluated_at=datetime(2026, 4, 21, 1, 0, tzinfo=timezone.utc),
    )
    repo.append_history(
        "0xabc123",
        score,
        decision="retire",
        reasoning="third",
        evaluated_at=datetime(2026, 4, 21, 2, 0, tzinfo=timezone.utc),
    )

    history = repo.get_history("0xabc123", limit=10)

    assert [entry["reasoning"] for entry in history] == ["third", "second", "first"]


def test_db_wal_mode(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"

    connection = get_connection(str(db_path))

    try:
        journal_mode = connection.execute("PRAGMA journal_mode;").fetchone()[0]
    finally:
        connection.close()

    assert journal_mode == "wal"


def test_db_check_constraint_violation(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    init_addresses_db(str(db_path))

    connection = get_connection(str(db_path))

    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO wallets (
                    address, chain, win_rate, trade_count, max_drawdown,
                    funds_usd, recent_win_rate, trust_level, status,
                    added_at, last_evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "0xabc123",
                    "xrp",
                    0.7,
                    50,
                    0.2,
                    100000.0,
                    0.72,
                    "high",
                    "active",
                    "2026-04-21T00:00:00+00:00",
                    "2026-04-21T00:00:00+00:00",
                ),
            )
    finally:
        connection.close()


def test_record_and_query_trade(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    trade_id = repo.record_trade(
        symbol="ETH/USDT",
        action="buy",
        quantity=Decimal("1.5"),
        price=Decimal("2400"),
        fee_usdt=Decimal("3.6"),
        source_wallet="0xabc123",
        confidence=82,
        reasoning="Wallet and signal stack aligned.",
        status="filled",
        paper_trading=False,
    )

    trades = repo.recent_trades(24)

    assert trade_id > 0
    assert len(trades) == 1
    assert trades[0]["symbol"] == "ETH/USDT"
    assert trades[0]["quantity_usdt"] == pytest.approx(3600.0)


def test_record_trade_with_slippage_fields(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    repo.record_trade(
        symbol="ETH/USDT",
        action="buy",
        quantity=Decimal("1"),
        price=Decimal("100"),
        fee_usdt=Decimal("0.1"),
        source_wallet="0xabc123",
        confidence=75,
        reasoning="Testing slippage fields.",
        status="paper",
        paper_trading=True,
        pre_trade_mid_price=Decimal("100"),
        estimated_slippage_pct=0.001,
        realized_slippage_pct=0.002,
        estimated_fee_pct=0.001,
        realized_fee_pct=0.001,
    )

    trades = repo.recent_trades(24)

    assert trades[0]["pre_trade_mid_price"] == 100.0
    assert trades[0]["realized_slippage_pct"] == 0.002


def test_position_lifecycle(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    repo.upsert_position(build_position())

    positions = repo.get_positions()

    assert len(positions) == 1

    repo.remove_position("ETH/USDT")

    assert repo.get_positions() == []


def test_daily_pnl_upsert(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    repo.set_daily_pnl(
        "2026-04-21",
        realized_pnl_usdt=Decimal("10"),
        unrealized_pnl_usdt=Decimal("5"),
        starting_equity_usdt=Decimal("1000"),
    )
    repo.set_daily_pnl(
        "2026-04-21",
        realized_pnl_usdt=Decimal("20"),
        unrealized_pnl_usdt=Decimal("15"),
        starting_equity_usdt=Decimal("1100"),
    )

    daily_pnl = repo.get_daily_pnl("2026-04-21")

    assert daily_pnl is not None
    assert daily_pnl["realized_pnl_usdt"] == 20.0
    assert daily_pnl["starting_equity_usdt"] == 1100.0


def test_recent_trades_filters_by_hour(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    with freeze_time("2026-04-20 10:00:00+00:00"):
        repo.record_trade(
            symbol="ETH/USDT",
            action="buy",
            quantity=Decimal("1"),
            price=Decimal("100"),
            fee_usdt=Decimal("0.1"),
            source_wallet="0xabc123",
            confidence=75,
            reasoning="old trade",
            status="filled",
            paper_trading=False,
        )

    with freeze_time("2026-04-21 12:00:00+00:00"):
        repo.record_trade(
            symbol="BTC/USDT",
            action="buy",
            quantity=Decimal("0.1"),
            price=Decimal("60000"),
            fee_usdt=Decimal("6"),
            source_wallet="0xabc123",
            confidence=88,
            reasoning="recent trade",
            status="filled",
            paper_trading=False,
        )
        trades = repo.recent_trades(24)

    assert [trade["symbol"] for trade in trades] == ["BTC/USDT"]


def test_record_snapshot_skip_path(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    repo.record_snapshot(build_skip_snapshot())

    snapshots = repo.get_snapshots(final_action="skip")

    assert len(snapshots) == 1
    assert snapshots[0].technical is None
    assert snapshots[0].final_action == "skip"


def test_record_snapshot_execute_path(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    repo.record_snapshot(build_execute_snapshot())

    snapshots = repo.get_snapshots(final_action="buy")
    snapshot = snapshots[0]

    assert snapshot.technical is not None
    assert snapshot.technical.trend == "bullish"
    assert snapshot.sentiment is not None
    assert snapshot.sentiment_counts is not None
    assert snapshot.risk is not None
    assert snapshot.risk.reasons == ("ok", "sized_down")
    assert snapshot.cost is not None
    assert snapshot.cost.total_cost_pct == 0.003


def test_link_snapshot_to_trade(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    snapshot_id = repo.record_snapshot(build_execute_snapshot())
    trade_id = repo.record_trade(
        symbol="ETH/USDT",
        action="buy",
        quantity=Decimal("1"),
        price=Decimal("100"),
        fee_usdt=Decimal("0.1"),
        source_wallet="0xabc123",
        confidence=81,
        reasoning="Executed after snapshot.",
        status="filled",
        paper_trading=False,
    )

    repo.link_snapshot_to_trade(snapshot_id, trade_id)

    snapshots = repo.get_snapshots(final_action="buy")

    assert snapshots[0].trade_id == trade_id


def test_skip_reason_counts(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    repo.record_snapshot(build_skip_snapshot(reason="low_confidence"))
    repo.record_snapshot(build_skip_snapshot(reason="low_confidence", symbol="BTC/USDT"))
    repo.record_snapshot(build_skip_snapshot(reason="cost_too_high", symbol="SOL/USDT"))

    counts = repo.skip_reason_counts()

    assert counts == {"cost_too_high": 1, "low_confidence": 2}


def test_get_snapshots_filter_by_symbol(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "trades.db"
    repo = TradesRepo(str(db_path))

    repo.record_snapshot(build_skip_snapshot(symbol="ETH/USDT"))
    repo.record_snapshot(build_skip_snapshot(symbol="BTC/USDT"))
    repo.record_snapshot(build_skip_snapshot(symbol="SOL/USDT"))

    snapshots = repo.get_snapshots(symbol="BTC/USDT")

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "BTC/USDT"
