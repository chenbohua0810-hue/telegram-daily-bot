from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from models import (
    CostSnapshotView,
    DecisionSnapshot,
    OnChainEvent,
    Position,
    RiskSnapshotView,
    SentimentCounts,
    SentimentSignal,
    TechnicalIndicators,
    TechnicalSignal,
    WalletScore,
)


# ---------------------------------------------------------------------------
# db
# ---------------------------------------------------------------------------

ADDRESSES_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY,
    chain TEXT NOT NULL CHECK (chain IN ('eth','sol','bsc')),
    win_rate REAL NOT NULL,
    trade_count INTEGER NOT NULL,
    max_drawdown REAL NOT NULL,
    funds_usd REAL NOT NULL,
    recent_win_rate REAL NOT NULL,
    trust_level TEXT NOT NULL CHECK (trust_level IN ('high','medium','low')),
    status TEXT NOT NULL CHECK (status IN ('active','watch','retired')),
    added_at TEXT NOT NULL,
    last_evaluated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    win_rate REAL NOT NULL,
    max_drawdown REAL NOT NULL,
    trust_level TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('keep','watch','retire')),
    reasoning TEXT NOT NULL,
    FOREIGN KEY (address) REFERENCES wallets(address)
);

CREATE INDEX IF NOT EXISTS idx_wallet_history_address
ON wallet_history(address, evaluated_at);
"""

TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('buy','sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    quantity_usdt REAL NOT NULL,
    fee_usdt REAL NOT NULL,
    source_wallet TEXT NOT NULL,
    confidence INTEGER NOT NULL,
    reasoning TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('filled','failed','paper')),
    paper_trading INTEGER NOT NULL,
    executed_at TEXT NOT NULL,
    binance_order_id TEXT,
    pre_trade_mid_price REAL,
    estimated_slippage_pct REAL,
    realized_slippage_pct REAL,
    estimated_fee_pct REAL,
    realized_fee_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
ON trades(symbol, executed_at);

CREATE INDEX IF NOT EXISTS idx_trades_wallet
ON trades(source_wallet, executed_at);

CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    quantity REAL NOT NULL,
    avg_entry_price REAL NOT NULL,
    entry_time TEXT NOT NULL,
    source_wallet TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    date TEXT PRIMARY KEY,
    realized_pnl_usdt REAL NOT NULL,
    unrealized_pnl_usdt REAL NOT NULL,
    starting_equity_usdt REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_tx_hash TEXT NOT NULL,
    source_wallet TEXT NOT NULL,
    symbol TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    trend TEXT,
    momentum TEXT,
    volatility TEXT,
    stat_arb TEXT,
    technical_confidence REAL,
    ema8 REAL,
    ema21 REAL,
    rsi REAL,
    macd_hist REAL,
    atr REAL,
    atr_pct REAL,
    bb_zscore REAL,
    close_price REAL,
    sentiment_signal TEXT,
    sentiment_score REAL,
    sentiment_source_count INTEGER,
    sentiment_positive INTEGER,
    sentiment_negative INTEGER,
    sentiment_neutral_count INTEGER,
    mention_delta REAL,
    ai_confidence INTEGER,
    ai_reasoning TEXT,
    ai_recommendation TEXT,
    risk_passed INTEGER,
    risk_multiplier REAL,
    risk_reasons TEXT,
    est_slippage_pct REAL,
    est_fee_pct REAL,
    est_total_cost_pct REAL,
    est_expected_profit_pct REAL,
    btc_price_usdt REAL,
    btc_24h_volatility_pct REAL,
    final_action TEXT NOT NULL CHECK (final_action IN ('buy','sell','hold','skip')),
    skip_reason TEXT,
    trade_id INTEGER,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_time
ON decision_snapshots(symbol, recorded_at);

CREATE INDEX IF NOT EXISTS idx_snapshots_wallet_time
ON decision_snapshots(source_wallet, recorded_at);

CREATE INDEX IF NOT EXISTS idx_snapshots_action
ON decision_snapshots(final_action, recorded_at);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    return connection


def init_addresses_db(db_path: str) -> None:
    connection = get_connection(db_path)

    try:
        connection.executescript(ADDRESSES_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def init_trades_db(db_path: str) -> None:
    connection = get_connection(db_path)

    try:
        connection.executescript(TRADES_SCHEMA)
        connection.commit()
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# event_log
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


class EventLog:
    def __init__(self, path: str) -> None:
        self._path = path

    def append(self, event: OnChainEvent) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        payload = json.dumps(event.to_dict(), separators=(",", ":"))

        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(f"{payload}\n")
            handle.flush()
            os.fsync(handle.fileno())

    def iter_events(self, since: datetime | None = None) -> Iterator[OnChainEvent]:
        if not os.path.exists(self._path):
            return

        with open(self._path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                    event = OnChainEvent.from_dict(payload)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    logger.warning("Skipping malformed event log line")
                    continue

                if since is not None and event.block_time < since:
                    continue

                yield event


# ---------------------------------------------------------------------------
# addresses_repo
# ---------------------------------------------------------------------------

WalletDecision = Literal["keep", "watch", "retire"]
WalletStatusType = Literal["active", "watch", "retired"]


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

    def set_status(self, address: str, status: WalletStatusType) -> None:
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

    def list_evaluable_wallets(self) -> list[WalletScore]:
        connection = get_connection(self._db_path)
        try:
            rows = connection.execute(
                "SELECT * FROM wallets WHERE status IN ('active', 'watch') ORDER BY address ASC"
            ).fetchall()
        finally:
            connection.close()
        return [self._row_to_wallet_score(row) for row in rows]

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


# ---------------------------------------------------------------------------
# trades_repo
# ---------------------------------------------------------------------------

TradeAction = Literal["buy", "sell"]
TradeStatus = Literal["filled", "failed", "paper"]
SnapshotAction = Literal["buy", "sell", "hold", "skip"]


def _serialize_datetime(value: datetime) -> str:
    return value.isoformat()


def _serialize_decimal(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _parse_reasons(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part for part in value.split(",") if part)


class TradesRepo:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        init_trades_db(self._db_path)

    def record_trade(
        self,
        *,
        symbol: str,
        action: TradeAction,
        quantity: Decimal,
        price: Decimal,
        fee_usdt: Decimal,
        source_wallet: str,
        confidence: int,
        reasoning: str,
        status: TradeStatus,
        paper_trading: bool,
        binance_order_id: str | None = None,
        pre_trade_mid_price: Decimal | None = None,
        estimated_slippage_pct: float | None = None,
        realized_slippage_pct: float | None = None,
        estimated_fee_pct: float | None = None,
        realized_fee_pct: float | None = None,
    ) -> int:
        quantity_usdt = quantity * price
        executed_at = _serialize_datetime(_utc_now())
        connection = get_connection(self._db_path)

        try:
            cursor = connection.execute(
                """
                INSERT INTO trades (
                    symbol, action, quantity, price, quantity_usdt, fee_usdt,
                    source_wallet, confidence, reasoning, status, paper_trading,
                    executed_at, binance_order_id, pre_trade_mid_price,
                    estimated_slippage_pct, realized_slippage_pct,
                    estimated_fee_pct, realized_fee_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    action,
                    float(quantity),
                    float(price),
                    float(quantity_usdt),
                    float(fee_usdt),
                    source_wallet,
                    confidence,
                    reasoning,
                    status,
                    int(paper_trading),
                    executed_at,
                    binance_order_id,
                    _serialize_decimal(pre_trade_mid_price),
                    estimated_slippage_pct,
                    realized_slippage_pct,
                    estimated_fee_pct,
                    realized_fee_pct,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        return int(cursor.lastrowid)

    def upsert_position(self, pos: Position) -> None:
        connection = get_connection(self._db_path)

        try:
            connection.execute(
                """
                INSERT INTO positions (
                    symbol, quantity, avg_entry_price, entry_time, source_wallet
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    avg_entry_price = excluded.avg_entry_price,
                    entry_time = excluded.entry_time,
                    source_wallet = excluded.source_wallet
                """,
                (
                    pos.symbol,
                    float(pos.quantity),
                    float(pos.avg_entry_price),
                    _serialize_datetime(pos.entry_time),
                    pos.source_wallet,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def remove_position(self, symbol: str) -> None:
        connection = get_connection(self._db_path)

        try:
            connection.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
            connection.commit()
        finally:
            connection.close()

    def get_positions(self) -> list[Position]:
        connection = get_connection(self._db_path)

        try:
            rows = connection.execute(
                "SELECT symbol, quantity, avg_entry_price, entry_time, source_wallet FROM positions ORDER BY symbol ASC"
            ).fetchall()
        finally:
            connection.close()

        return [
            Position(
                symbol=row["symbol"],
                quantity=Decimal(str(row["quantity"])),
                avg_entry_price=Decimal(str(row["avg_entry_price"])),
                entry_time=datetime.fromisoformat(row["entry_time"]),
                source_wallet=row["source_wallet"],
            )
            for row in rows
        ]

    def get_daily_pnl(self, date: str) -> dict | None:
        connection = get_connection(self._db_path)

        try:
            row = connection.execute(
                """
                SELECT date, realized_pnl_usdt, unrealized_pnl_usdt, starting_equity_usdt
                FROM daily_pnl
                WHERE date = ?
                """,
                (date,),
            ).fetchone()
        finally:
            connection.close()

        return None if row is None else dict(row)

    def set_daily_pnl(
        self,
        date: str,
        realized_pnl_usdt: Decimal,
        unrealized_pnl_usdt: Decimal,
        starting_equity_usdt: Decimal,
    ) -> None:
        connection = get_connection(self._db_path)

        try:
            connection.execute(
                """
                INSERT INTO daily_pnl (
                    date, realized_pnl_usdt, unrealized_pnl_usdt, starting_equity_usdt
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    realized_pnl_usdt = excluded.realized_pnl_usdt,
                    unrealized_pnl_usdt = excluded.unrealized_pnl_usdt,
                    starting_equity_usdt = excluded.starting_equity_usdt
                """,
                (
                    date,
                    float(realized_pnl_usdt),
                    float(unrealized_pnl_usdt),
                    float(starting_equity_usdt),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def recent_trades(self, hours: int = 24, symbol: str | None = None) -> list[dict]:
        since = _serialize_datetime(_utc_now() - timedelta(hours=hours))
        query = "SELECT * FROM trades WHERE executed_at >= ?"
        params: list[object] = [since]

        if symbol is not None:
            query += " AND symbol = ?"
            params.append(symbol)

        query += " ORDER BY executed_at DESC"
        connection = get_connection(self._db_path)

        try:
            rows = connection.execute(query, tuple(params)).fetchall()
        finally:
            connection.close()

        return [dict(row) for row in rows]

    def get_traded_symbols(self) -> set[str]:
        connection = get_connection(self._db_path)

        try:
            rows = connection.execute("SELECT DISTINCT symbol FROM trades").fetchall()
        finally:
            connection.close()

        return {
            str(row["symbol"]).split("/USDT", maxsplit=1)[0]
            for row in rows
            if row["symbol"]
        }

    def record_snapshot(self, snapshot: DecisionSnapshot) -> int:
        technical = snapshot.technical
        indicators = snapshot.technical_indicators
        sentiment = snapshot.sentiment
        counts = snapshot.sentiment_counts
        risk = snapshot.risk
        cost = snapshot.cost
        connection = get_connection(self._db_path)

        try:
            cursor = connection.execute(
                """
                INSERT INTO decision_snapshots (
                    event_tx_hash, source_wallet, symbol, recorded_at,
                    trend, momentum, volatility, stat_arb, technical_confidence,
                    ema8, ema21, rsi, macd_hist, atr, atr_pct, bb_zscore, close_price,
                    sentiment_signal, sentiment_score, sentiment_source_count,
                    sentiment_positive, sentiment_negative, sentiment_neutral_count, mention_delta,
                    ai_confidence, ai_reasoning, ai_recommendation,
                    risk_passed, risk_multiplier, risk_reasons,
                    est_slippage_pct, est_fee_pct, est_total_cost_pct, est_expected_profit_pct,
                    btc_price_usdt, btc_24h_volatility_pct,
                    final_action, skip_reason, trade_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.event_tx_hash,
                    snapshot.source_wallet,
                    snapshot.symbol,
                    _serialize_datetime(snapshot.recorded_at),
                    None if technical is None else technical.trend,
                    None if technical is None else technical.momentum,
                    None if technical is None else technical.volatility,
                    None if technical is None else technical.stat_arb,
                    None if technical is None else technical.confidence,
                    None if indicators is None else indicators.ema8,
                    None if indicators is None else indicators.ema21,
                    None if indicators is None else indicators.rsi,
                    None if indicators is None else indicators.macd_hist,
                    None if indicators is None else indicators.atr,
                    None if indicators is None else indicators.atr_pct,
                    None if indicators is None else indicators.bb_zscore,
                    None if indicators is None else indicators.close_price,
                    None if sentiment is None else sentiment.signal,
                    None if sentiment is None else sentiment.score,
                    None if sentiment is None else sentiment.source_count,
                    None if counts is None else counts.positive,
                    None if counts is None else counts.negative,
                    None if counts is None else counts.neutral,
                    None if counts is None else counts.mention_delta,
                    snapshot.ai_confidence,
                    snapshot.ai_reasoning,
                    snapshot.ai_recommendation,
                    None if risk is None else int(risk.passed),
                    None if risk is None else risk.multiplier,
                    None if risk is None else ",".join(risk.reasons),
                    None if cost is None else cost.slippage_pct,
                    None if cost is None else cost.fee_pct,
                    None if cost is None else cost.total_cost_pct,
                    None if cost is None else cost.expected_profit_pct,
                    snapshot.btc_price_usdt,
                    snapshot.btc_24h_volatility_pct,
                    snapshot.final_action,
                    snapshot.skip_reason,
                    snapshot.trade_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        return int(cursor.lastrowid)

    def link_snapshot_to_trade(self, snapshot_id: int, trade_id: int) -> None:
        connection = get_connection(self._db_path)

        try:
            connection.execute(
                "UPDATE decision_snapshots SET trade_id = ? WHERE id = ?",
                (trade_id, snapshot_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_snapshots(
        self,
        *,
        symbol: str | None = None,
        source_wallet: str | None = None,
        final_action: SnapshotAction | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[DecisionSnapshot]:
        query = "SELECT * FROM decision_snapshots WHERE 1 = 1"
        params: list[object] = []

        if symbol is not None:
            query += " AND symbol = ?"
            params.append(symbol)
        if source_wallet is not None:
            query += " AND source_wallet = ?"
            params.append(source_wallet)
        if final_action is not None:
            query += " AND final_action = ?"
            params.append(final_action)
        if since is not None:
            query += " AND recorded_at >= ?"
            params.append(_serialize_datetime(since))

        query += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)

        connection = get_connection(self._db_path)

        try:
            rows = connection.execute(query, tuple(params)).fetchall()
        finally:
            connection.close()

        return [self._row_to_snapshot(row) for row in rows]

    def skip_reason_counts(self, since: datetime | None = None) -> dict[str, int]:
        query = """
            SELECT skip_reason, COUNT(*) AS count
            FROM decision_snapshots
            WHERE final_action = 'skip' AND skip_reason IS NOT NULL
        """
        params: list[object] = []

        if since is not None:
            query += " AND recorded_at >= ?"
            params.append(_serialize_datetime(since))

        query += " GROUP BY skip_reason ORDER BY skip_reason ASC"
        connection = get_connection(self._db_path)

        try:
            rows = connection.execute(query, tuple(params)).fetchall()
        finally:
            connection.close()

        return {row["skip_reason"]: row["count"] for row in rows}

    @staticmethod
    def _row_to_snapshot(row: dict) -> DecisionSnapshot:
        technical = None
        if row["trend"] is not None:
            technical = TechnicalSignal(
                trend=row["trend"],
                momentum=row["momentum"],
                volatility=row["volatility"],
                stat_arb=row["stat_arb"],
                confidence=row["technical_confidence"],
            )

        indicators = None
        if row["ema8"] is not None:
            indicators = TechnicalIndicators(
                ema8=row["ema8"],
                ema21=row["ema21"],
                rsi=row["rsi"],
                macd_hist=row["macd_hist"],
                atr=row["atr"],
                atr_pct=row["atr_pct"],
                bb_zscore=row["bb_zscore"],
                close_price=row["close_price"],
            )

        sentiment = None
        if row["sentiment_signal"] is not None:
            sentiment = SentimentSignal(
                signal=row["sentiment_signal"],
                score=row["sentiment_score"],
                source_count=row["sentiment_source_count"],
            )

        counts = None
        if row["sentiment_positive"] is not None:
            counts = SentimentCounts(
                positive=row["sentiment_positive"],
                negative=row["sentiment_negative"],
                neutral=row["sentiment_neutral_count"],
                mention_delta=row["mention_delta"],
            )

        risk = None
        if row["risk_passed"] is not None:
            risk = RiskSnapshotView(
                passed=bool(row["risk_passed"]),
                multiplier=row["risk_multiplier"],
                reasons=_parse_reasons(row["risk_reasons"]),
            )

        cost = None
        if row["est_slippage_pct"] is not None:
            cost = CostSnapshotView(
                slippage_pct=row["est_slippage_pct"],
                fee_pct=row["est_fee_pct"],
                total_cost_pct=row["est_total_cost_pct"],
                expected_profit_pct=row["est_expected_profit_pct"],
            )

        return DecisionSnapshot(
            event_tx_hash=row["event_tx_hash"],
            source_wallet=row["source_wallet"],
            symbol=row["symbol"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            technical=technical,
            technical_indicators=indicators,
            sentiment=sentiment,
            sentiment_counts=counts,
            ai_confidence=row["ai_confidence"],
            ai_reasoning=row["ai_reasoning"],
            ai_recommendation=row["ai_recommendation"],
            risk=risk,
            cost=cost,
            btc_price_usdt=row["btc_price_usdt"],
            btc_24h_volatility_pct=row["btc_24h_volatility_pct"],
            final_action=row["final_action"],
            skip_reason=row["skip_reason"],
            trade_id=row["trade_id"],
        )
