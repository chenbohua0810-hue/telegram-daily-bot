from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from models.signals import WalletScore
from storage.addresses_repo import AddressesRepo
from storage.db import get_connection, init_addresses_db, init_trades_db


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
