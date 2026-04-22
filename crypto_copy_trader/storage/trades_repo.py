from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from models.portfolio import Position
from models.signals import (
    SentimentCounts,
    SentimentSignal,
    TechnicalIndicators,
    TechnicalSignal,
)
from models.snapshot import CostSnapshotView, DecisionSnapshot, RiskSnapshotView
from storage.db import get_connection, init_trades_db


TradeAction = Literal["buy", "sell"]
TradeStatus = Literal["filled", "failed", "paper"]
SnapshotAction = Literal["buy", "sell", "hold", "skip"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
