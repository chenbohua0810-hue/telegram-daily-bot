from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from models.signals import WalletScore
from storage.db import get_connection, init_addresses_db


WalletDecision = Literal["keep", "watch", "retire"]
WalletStatus = Literal["active", "watch", "retired"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AddressesRepo:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        init_addresses_db(self._db_path)

    def upsert_wallet(self, score: WalletScore) -> None:
        timestamp = _utc_now().isoformat()
        existing = self._get_wallet_timestamps(score.address)
        added_at = existing["added_at"] if existing is not None else timestamp

        connection = get_connection(self._db_path)

        try:
            connection.execute(
                """
                INSERT INTO wallets (
                    address, chain, win_rate, trade_count, max_drawdown,
                    funds_usd, recent_win_rate, trust_level, status,
                    added_at, last_evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    chain = excluded.chain,
                    win_rate = excluded.win_rate,
                    trade_count = excluded.trade_count,
                    max_drawdown = excluded.max_drawdown,
                    funds_usd = excluded.funds_usd,
                    recent_win_rate = excluded.recent_win_rate,
                    trust_level = excluded.trust_level,
                    status = excluded.status,
                    last_evaluated_at = excluded.last_evaluated_at
                """,
                (
                    score.address,
                    score.chain,
                    score.win_rate,
                    score.trade_count,
                    score.max_drawdown,
                    score.funds_usd,
                    score.recent_win_rate,
                    score.trust_level,
                    score.status,
                    added_at,
                    timestamp,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def get_wallet(self, address: str) -> WalletScore | None:
        connection = get_connection(self._db_path)

        try:
            row = connection.execute(
                "SELECT * FROM wallets WHERE address = ?",
                (address,),
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            return None

        return self._row_to_wallet_score(row)

    def list_active(self, chain: str | None = None) -> list[WalletScore]:
        query = "SELECT * FROM wallets WHERE status = 'active'"
        params: tuple[str, ...] = ()

        if chain is not None:
            query += " AND chain = ?"
            params = (chain,)

        query += " ORDER BY address ASC"

        connection = get_connection(self._db_path)

        try:
            rows = connection.execute(query, params).fetchall()
        finally:
            connection.close()

        return [self._row_to_wallet_score(row) for row in rows]

    def set_status(self, address: str, status: WalletStatus) -> None:
        connection = get_connection(self._db_path)

        try:
            connection.execute(
                "UPDATE wallets SET status = ?, last_evaluated_at = ? WHERE address = ?",
                (status, _utc_now().isoformat(), address),
            )
            connection.commit()
        finally:
            connection.close()

    def append_history(
        self,
        address: str,
        score: WalletScore,
        decision: WalletDecision,
        reasoning: str,
        evaluated_at: datetime | None = None,
    ) -> None:
        history_time = (evaluated_at or _utc_now()).isoformat()
        connection = get_connection(self._db_path)

        try:
            connection.execute(
                """
                INSERT INTO wallet_history (
                    address, evaluated_at, win_rate, max_drawdown,
                    trust_level, decision, reasoning
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    address,
                    history_time,
                    score.win_rate,
                    score.max_drawdown,
                    score.trust_level,
                    decision,
                    reasoning,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def get_history(self, address: str, limit: int = 10) -> list[dict]:
        connection = get_connection(self._db_path)

        try:
            rows = connection.execute(
                """
                SELECT address, evaluated_at, win_rate, max_drawdown,
                       trust_level, decision, reasoning
                FROM wallet_history
                WHERE address = ?
                ORDER BY evaluated_at DESC
                LIMIT ?
                """,
                (address, limit),
            ).fetchall()
        finally:
            connection.close()

        return [dict(row) for row in rows]

    def _get_wallet_timestamps(self, address: str) -> dict | None:
        connection = get_connection(self._db_path)

        try:
            row = connection.execute(
                "SELECT added_at, last_evaluated_at FROM wallets WHERE address = ?",
                (address,),
            ).fetchone()
        finally:
            connection.close()

        return None if row is None else dict(row)

    @staticmethod
    def _row_to_wallet_score(row: dict) -> WalletScore:
        return WalletScore(
            address=row["address"],
            chain=row["chain"],
            win_rate=row["win_rate"],
            trade_count=row["trade_count"],
            max_drawdown=row["max_drawdown"],
            funds_usd=row["funds_usd"],
            recent_win_rate=row["recent_win_rate"],
            trust_level=row["trust_level"],
            status=row["status"],
        )
