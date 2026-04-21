from __future__ import annotations

import sqlite3

import pytest

from storage.db import get_connection, init_addresses_db, init_trades_db


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
