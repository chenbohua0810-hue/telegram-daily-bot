from __future__ import annotations

import sqlite3


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
