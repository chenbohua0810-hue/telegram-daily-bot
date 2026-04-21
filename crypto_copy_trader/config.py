from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    BINANCE_API_KEY: str
    BINANCE_API_SECRET: str
    PAPER_TRADING: bool = True

    ANTHROPIC_API_KEY: str
    AI_SCORER_MODEL: str = "claude-haiku-4-5-20251001"

    ETHERSCAN_API_KEY: str
    SOLSCAN_API_KEY: str
    BSCSCAN_API_KEY: str

    CRYPTOPANIC_API_KEY: str

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    MIN_TRADE_USD: float = 10000.0
    MAX_POSITION_PCT: float = 0.10
    DAILY_LOSS_CIRCUIT: float = -0.05
    MAX_CONCURRENT_POSITIONS: int = 10
    POLL_INTERVAL_SECONDS: int = 60
    AI_SCORER_CONFIDENCE_THRESHOLD: int = 60

    ADDRESSES_DB_PATH: str = "data/addresses.db"
    TRADES_DB_PATH: str = "data/trades.db"
    EVENTS_LOG_PATH: str = "data/events.jsonl"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
